from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import random
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import parse_qsl, urlsplit

from playwright.sync_api import Playwright, sync_playwright

from analytics import MetricsStorage
from audit_ledger import JobAuditLedger
from browser_profile_cleanup import cleanup_browser_storage
from config import BotConfig, load_config
from cv_generator import generate_cv_pdf
from daily_coverage_audit import (
    build_daily_coverage_report,
    format_telegram_summary,
    write_daily_coverage_report,
)
from enricher import MIN_COMPLETE_DESCRIPTION_CHARS, enrich_job_description
from extension_bridge import ExtensionBatch, ExtensionBridge
from linkedin_dual import LinkedInDualCoordinator
from matcher import (
    calculate_match_score,
    extract_job_features,
    is_job_geographically_viable,
)
from notifier import TelegramNotifier
from operational_retention import cleanup_operational_data, jsonl_file_lock
from project_prompt import build_project_buttons, build_project_prompt
from provider_validation import (
    ProviderValidationStore,
    provider_is_validated,
    record_runtime_observation,
    schedule_anomaly_audit,
)
from providers.accessiway import AccessiwayProvider
from models import JobItem, JobProvider
import asyncio
from providers.consultancies import CONSULTANCY_SOURCE_IDS, build_consultancy_provider
from providers.experis import ExperisProvider
from providers.greenhouse_spain import GreenhouseSpainProvider
from providers.indeed import IndeedProvider
from providers.infojobs import InfoJobsProvider
from providers.linkedin import LinkedInProvider
from providers.linkedin_common import linkedin_search_urls
from providers.linkedin_recency import evaluate_linkedin_recency
from providers.manfred import ManfredProvider
from providers.remoteok import RemoteOKProvider
from providers.remotive import RemotiveProvider
from providers.tecnoempleo import TecnoempleoProvider
from providers.upv_sie import UPVSIEProvider
from providers.wwr import WWRProvider
from relevance import (
    RelevanceDecision,
    decision_from_dict,
    evaluate_relevance,
    relevance_fingerprint,
)
from database import DatabaseStorage, SQLiteSeenStorage, SQLiteRelevanceCache
from tailor import (
    answer_custom_question,
    generate_cover_letter,
    generate_screening_answers,
)

DAILY_SEEN_CLEANUP_HOUR = 3
DAILY_DIGEST_HOUR = 20
RUNTIME_FILTERS_FILE = "runtime_filters.json"
RUNTIME_FILTER_POLICY_VERSION = 2
# These values were previously used as raw substrings.  They describe broad
# career levels or technologies, not a reliably unrelated vacancy, so they
# cannot be active blacklist entries.
BROAD_EXCLUDE_PHRASES = frozenset(
    {
        "senior",
        "lead",
        "manager",
        "analista",
        "data",
        "datos",
        "security",
        "qa",
        "power",
        "python",
        "golang",
        "rust",
    }
)
METRICS_DATA_FILE = "metrics_jobs.jsonl"
RATE_LIMIT_METRICS_FILE = "rate_limit_metrics.jsonl"
BOT_PAUSED = False
LATEST_JOBS_CACHE: list[JobItem] = []
TODAY_DISCOVERED_JOBS: list[JobItem] = []
TODAY_DISCOVERED_DATE: date | None = None
CYCLE_LOGS: list[dict[str, Any]] = []
CURRENT_STATUS: dict[str, Any] = {
    "is_scraping_now": False,
    "last_cycle_start": None,
    "last_cycle_end": None,
    "next_cycle_estimate": None,
    "total_cycles_completed": 0,
    "last_cycle_stats": {},
}


@dataclass
class RuntimeContext:
    config: BotConfig
    logger: logging.Logger
    notifier: TelegramNotifier
    storage: SeenStorage
    metrics: MetricsStorage
    audit_ledger: JobAuditLedger | None = field(default=None, repr=False)
    relevance_cache: RelevanceDecisionCache | None = field(default=None, repr=False)
    # A provider must never be scraped concurrently by /scan and the scheduler.
    scrape_lock: Any = field(default_factory=threading.RLock, repr=False)
    # Chromium ingestion, the public fallback and an inventory audit describe
    # the same LinkedIn cascade, so they need a narrower shared lock. Keeping
    # it separate lets the other portals continue while Chromium finishes.
    linkedin_lock: Any = field(default_factory=threading.RLock, repr=False)


def send_on_demand_coverage_audit(ctx: RuntimeContext, base_dir: Path) -> dict[str, Any]:
    """Create a read-only operational audit requested through Telegram."""
    report = build_daily_coverage_report(base_dir, ctx.config)
    output_dir = Path(ctx.config.daily_coverage_dir)
    if not output_dir.is_absolute():
        output_dir = base_dir / output_dir
    dated_path, _ = write_daily_coverage_report(report, output_dir)
    ctx.notifier.send_message(format_telegram_summary(report, dated_path))
    ctx.logger.info(
        "On-demand coverage audit | status=%s evidence=%s cycles=%s/%s report=%s",
        report["overall"]["status"],
        report["overall"]["operational_evidence_score"],
        report["scheduler"]["cycle_records"],
        report["scheduler"]["expected_cycles"],
        dated_path,
    )
    return report


def _normalize_words(raw: str) -> list[str]:
    out: list[str] = []
    for part in raw.split(","):
        word = normalize_text(part)
        if word:
            out.append(word)
    return out


def _partition_exclude_words(words: list[str]) -> tuple[list[str], list[str]]:
    """Keep only precise blacklist phrases active.

    A search-result source already controls the candidate scope.  One-word
    skills and seniority labels therefore create false negatives much more
    often than useful exclusions.
    """
    active: list[str] = []
    softened: list[str] = []
    for word in words:
        normalized = normalize_text(word)
        if not normalized:
            continue
        (softened if normalized in BROAD_EXCLUDE_PHRASES else active).append(normalized)
    return list(dict.fromkeys(active)), list(dict.fromkeys(softened))


def _runtime_filters_path(base_dir: Path) -> Path:
    return (base_dir / "data" / RUNTIME_FILTERS_FILE).resolve()


def load_runtime_exclude_words(
    base_dir: Path, fallback: list[str], logger: logging.Logger
) -> list[str]:
    path = _runtime_filters_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        words, softened = _partition_exclude_words(fallback)
        path.write_text(
            json.dumps(
                {
                    "filter_policy_version": RUNTIME_FILTER_POLICY_VERSION,
                    "exclude_words": words,
                    "softened_legacy_exclude_words": softened,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return words
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore") or "{}")
        if not isinstance(data, dict):
            raise TypeError("runtime filter payload must be an object")
        words = [
            normalize_text(w)
            for w in (data.get("exclude_words") or [])
            if normalize_text(w)
        ]
        words = list(dict.fromkeys(words))
        softened_history = [
            normalize_text(word)
            for word in (data.get("softened_legacy_exclude_words") or [])
            if normalize_text(word)
        ]
        active_words, softened_words = _partition_exclude_words(words)
        if int(data.get("filter_policy_version", 1)) < RUNTIME_FILTER_POLICY_VERSION:
            # Earlier versions stored generic terms such as "data" and "senior".
            # Preserve them for auditability, but require an explicit re-addition.
            softened = list(
                dict.fromkeys(
                    [
                        *(
                            softened_history
                        ),
                        *softened_words,
                        *active_words,
                    ]
                )
            )
            path.write_text(
                json.dumps(
                    {
                        "filter_policy_version": RUNTIME_FILTER_POLICY_VERSION,
                        "exclude_words": [],
                        "softened_legacy_exclude_words": softened,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            logger.warning(
                "Migrated broad legacy exclusions to informational history at %s; "
                "add only precise title/company phrases with /exclude_add.",
                path,
            )
            return []
        if softened_words:
            softened = list(dict.fromkeys([*softened_history, *softened_words]))
            path.write_text(
                json.dumps(
                    {
                        "filter_policy_version": RUNTIME_FILTER_POLICY_VERSION,
                        "exclude_words": active_words,
                        "softened_legacy_exclude_words": softened,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            logger.warning(
                "Deactivated broad exclusions at %s; use a specific multi-word "
                "title/company phrase instead.",
                path,
            )
        return active_words
    except (OSError, TypeError, ValueError) as exc:
        logger.warning("runtime_filters load failed, using fallback: %s", exc)
        return list(
            dict.fromkeys([normalize_text(w) for w in fallback if normalize_text(w)])
        )


def save_runtime_exclude_words(
    base_dir: Path, words: list[str], logger: logging.Logger
) -> None:
    path = _runtime_filters_path(base_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        unique_words, newly_softened = _partition_exclude_words(words)
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        existing_softened = (
            existing.get("softened_legacy_exclude_words") or []
            if isinstance(existing, dict)
            else []
        )
        softened = list(
            dict.fromkeys(
                normalize_text(word)
                for word in [*existing_softened, *newly_softened]
                if normalize_text(word)
            )
        )
        path.write_text(
            json.dumps(
                {
                    "filter_policy_version": RUNTIME_FILTER_POLICY_VERSION,
                    "exclude_words": unique_words,
                    "softened_legacy_exclude_words": softened,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except (OSError, TypeError, ValueError) as exc:
        logger.error("runtime_filters save failed: %s", exc)


def generate_daily_digest(jobs_today: list[JobItem]) -> str:
    """Generates a simpler, user-friendly summary digest."""
    if not jobs_today:
        return "📊 *Resumen Diario*\nHoy el mercado ha estado tranquilo. No hemos capturado nuevas ofertas válidas."

    # Ordenar por puntuación pero pasando la descripción para mayor precisión
    scored_jobs = []
    for j in jobs_today:
        score, *_ = calculate_match_score(
            j.title, getattr(j, 'description', '') or "", j.location, j.company, j.posted_within_1h
        )
        scored_jobs.append((score, j))

    scored_jobs.sort(key=lambda x: x[0], reverse=True)

    lines = [
        f"📊 *Resumen Diario* ({datetime.now().strftime('%d/%m/%Y')})",
        f"Has recibido un total de *{len(jobs_today)} ofertas* válidas hoy.\n",
        "🏆 *Las 3 mejores ofertas del día:*\n"
    ]

    medals = ["1️⃣", "2️⃣", "3️⃣"]
    
    for idx, (score, j) in enumerate(scored_jobs[:3]):
        medal = medals[idx] if idx < 3 else f"{idx+1}."
        lines.append(f"{medal} *{j.title}* en *{j.company}*")
        lines.append(f"📍 {j.location}")
        lines.append(f"🔗 [Abrir la oferta aquí]({j.url})\n")

    lines.append(
        "💡 *Tip:* Para generar una carta de presentación para la última oferta de hoy, escríbeme: `/tailor 1`"
    )
    return "\n".join(lines)


def _iter_lines_reverse(path: Path, block_size: int = 64 * 1024) -> Iterable[str]:
    """Yield UTF-8 text lines from a file tail-first without loading it all."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            position = handle.tell()
            pending = b""
            while position > 0:
                read_size = min(block_size, position)
                position -= read_size
                handle.seek(position)
                chunk = handle.read(read_size) + pending
                parts = chunk.split(b"\n")
                pending = parts[0]
                for raw_line in reversed(parts[1:]):
                    yield raw_line.decode("utf-8", errors="ignore").rstrip("\r")
            if pending:
                yield pending.decode("utf-8", errors="ignore").rstrip("\r")
    except OSError:
        return


def _metric_timestamp(value: Any) -> datetime | None:
    """Normalise legacy JSONL timestamps so the digest only keeps its time window."""
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def load_all_recent_jobs_from_disk(base_dir: Path, max_days: int = 2) -> list[JobItem]:
    """Load up to 300 unique jobs from the recent metrics window, tail first."""
    metrics_file = base_dir / "data" / METRICS_DATA_FILE
    if not metrics_file.exists():
        metrics_file = base_dir / METRICS_DATA_FILE
    if not metrics_file.exists():
        return []
    seen_ids: set[str] = set()
    jobs: list[JobItem] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(0, max_days))
    for line in _iter_lines_reverse(metrics_file):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            if not isinstance(d, dict):
                continue
            recorded_at = _metric_timestamp(d.get("timestamp"))
            if recorded_at is None or recorded_at < cutoff:
                continue
            jid = str(d.get("id", ""))
            if not jid or jid in seen_ids:
                continue
            seen_ids.add(jid)
            jobs.append(
                JobItem(
                    id=jid,
                    source=str(d.get("source", "linkedin")),
                    title=str(d.get("title", "")),
                    company=str(d.get("company", "")),
                    location=str(d.get("location", "")),
                    url=str(d.get("url", "")),
                    description=str(d.get("description", "")),
                )
            )
        except (AttributeError, TypeError, ValueError):
            continue
        if len(jobs) >= 300:
            break
    return jobs


def find_target_job(
    arg: str, jobs: list[JobItem], base_dir: Path
) -> tuple[JobItem | None, str]:
    """
    Intelligently resolves the target job from:
    1. Integer index (e.g. 1, 2, 10, 50).
    2. Exact or partial job ID (e.g. 4455785115, manfred_8398, bc8296fbb94a69a99c4da55574971e).
    3. Company name match (e.g. Amazon, Sopra, Fever, Sener).
    4. Title keyword match (e.g. Vision, RAG, Robot).
    5. Default to the most recent job if no arg is given.
    """
    if not jobs:
        jobs = load_all_recent_jobs_from_disk(base_dir)
    if not jobs:
        return None, "ℹ️ No hay ofertas registradas en los últimos 2 días."

    clean_arg = arg.strip()
    if not clean_arg:
        return jobs[0], ""

    # 1. Number index (e.g. 1, 2, 15) (ignore if it's a 10-digit LinkedIn ID)
    if clean_arg.isdigit() and len(clean_arg) < 6:
        num = int(clean_arg)
        if 1 <= num <= len(jobs):
            return jobs[num - 1], ""
        else:
            return (
                None,
                f"ℹ️ El número #{num} está fuera de rango. Hay {len(jobs)} ofertas registradas (usa /cv 1 hasta /cv {len(jobs)}).",
            )

    # 2. Exact or partial ID match
    for j in jobs:
        if j.id.lower() == clean_arg.lower() or clean_arg.lower() in j.id.lower():
            return j, ""

    # 3. Company match
    for j in jobs:
        if clean_arg.lower() in j.company.lower():
            return j, ""

    # 4. Title match
    for j in jobs:
        if clean_arg.lower() in j.title.lower():
            return j, ""

    return (
        None,
        f"ℹ️ No se encontró ninguna oferta que coincida con '{clean_arg}' en el registro de los últimos 2 días.",
    )


def fetch_provider_jobs(
    provider_name: str,
    provider: JobProvider,
    *,
    startup_deep_scan: bool = False,
) -> list[JobItem]:
    """Run a provider with its supported API and keep LinkedIn's deep sweep explicit."""
    if provider_name == "linkedin":
        return provider.fetch_jobs(startup_deep_scan=startup_deep_scan)  # type: ignore[call-arg]
    return provider.fetch_jobs()


def ordered_providers(
    providers: dict[str, JobProvider],
) -> list[tuple[str, JobProvider]]:
    """Leave LinkedIn last so a rate limit cannot delay every other source."""
    return [
        (name, provider) for name, provider in providers.items() if name != "linkedin"
    ] + [(name, provider) for name, provider in providers.items() if name == "linkedin"]


def provider_http_429_count(provider: JobProvider) -> int:
    """Return the exact provider counter, or a safe fallback for other providers."""
    value = getattr(provider, "rate_limit_429_cycle", None)
    if value is not None:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0
    return int("429" in str(getattr(provider, "last_blocked_reason", "")))


def provider_blocked_reason(provider: JobProvider) -> str:
    """Expose a provider-side reason in cycle metrics without assuming every API has it."""
    return str(getattr(provider, "last_blocked_reason", "") or "")


def append_rate_limit_metrics(
    base_dir: Path, logger: logging.Logger, cycle: dict[str, Any]
) -> None:
    """Persist per-provider cycle evidence for limits and the daily audit."""
    try:
        by_provider = cycle.get("by_provider", {})
        process_stat_fields = (
            "detected",
            "eligible",
            "discarded_time_window",
            "unverified_time_window",
            "discarded_location",
            "discarded_include",
            "discarded_exclude",
            "discarded_relevance",
            "relevance_warning",
            "description_unavailable",
            "discarded_description_unavailable",
            "duplicate_channels",
            "seen",
            "paused",
            "notification_limit",
            "alerts_disabled",
            "delivery_failed",
            "saved",
            "sent",
        )
        providers = {
            name: {
                **{
                    field: max(0, int(stats.get(field, 0)))
                    for field in process_stat_fields
                },
                "http_429": max(0, int(stats.get("http_429", 0))),
                "blocked_reason": str(stats.get("blocked_reason", "")),
                "validation_status": str(stats.get("validation_status", "")),
                "validation_visible_count": stats.get("validation_visible_count"),
                "validation_matches": stats.get("validation_matches"),
                "validation_eligible_missing": stats.get("validation_eligible_missing"),
                "validation_last_correct_at": stats.get("validation_last_correct_at"),
                "validation_ordering": str(stats.get("validation_ordering", "")),
                "validation_anomaly": stats.get("validation_anomaly"),
            }
            for name, stats in by_provider.items()
        }
        record = {
            # UTC makes daily evidence comparable regardless of host timezone.
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "cycle_num": int(cycle.get("cycle_num", 0)),
            "http_429": max(0, int(cycle.get("http_429", 0))),
            "providers": providers,
        }
        path = base_dir / "data" / RATE_LIMIT_METRICS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with jsonl_file_lock(path), path.open("a", encoding="utf-8") as file_handle:
            file_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError, AttributeError) as exc:
        logger.warning("Failed to persist rate-limit metrics: %s", exc)


def wait_between_providers(config: BotConfig, logger: logging.Logger) -> None:
    """Keep public portal traffic sequential and avoid request bursts."""
    lower = max(0.0, float(getattr(config, "provider_inter_request_min_seconds", 3.0)))
    upper = max(
        lower, float(getattr(config, "provider_inter_request_max_seconds", 6.0))
    )
    delay = random.uniform(lower, upper)
    logger.info("Inter-provider delay | seconds=%.1f", delay)
    time.sleep(delay)


def process_telegram_commands(
    ctx: RuntimeContext,
    base_dir: Path,
    commands: list[tuple[int, str, int]],
    providers_map: dict[str, JobProvider] | None = None,
) -> int | None:
    global \
        BOT_PAUSED, \
        LATEST_JOBS_CACHE, \
        TODAY_DISCOVERED_JOBS, \
        CYCLE_LOGS, \
        CURRENT_STATUS

    if not commands:
        return
    next_offset = 0

    if not LATEST_JOBS_CACHE:
        LATEST_JOBS_CACHE = load_all_recent_jobs_from_disk(base_dir)

    for _, raw_text, msg_id in commands:
        text = raw_text.strip()
        cmd, _, rest = text.partition(" ")
        cmd = cmd.split("@")[0].lower()
        arg = rest.strip()

        if cmd == "/help":
            help_text = (
                "🤖 *Comandos del Bot de Empleo*\n\n"
                "📌 */help* — Menú de ayuda.\n"
                "📌 */status* — 📊 Estado en tiempo real, tiempo a la próxima búsqueda y desglose de la última.\n"
                "📌 */history* — 📜 Historial de las últimas búsquedas ejecutadas y sus métricas.\n"
                "📌 */latest* — Últimas ofertas detectadas con su Match Score %.\n"
                "📌 */top* — Muestra las ofertas con *mayor afinidad* (Match Score más alto).\n"
                "📌 */cv <num/id/empresa>* — Genera tu *CV en PDF adaptado 1:1 (ATS 100%)* (ej: /cv 1, /cv Amazon o pulsar botón).\n"
                "📌 */tailor <num/id/empresa>* — Genera una *Carta de Presentación adaptada* por IA (ej: /tailor 1).\n"
                "📌 */qa <num/id/empresa>* — Preguntas y respuestas clave para *Solicitud Sencilla* (ej: /qa 1).\n"
                "📌 */project <num/id/empresa>* — Prompt para crear proyectos relevantes para una oferta.\n"
                "📌 */ask <pregunta>* — Redacta la *respuesta perfecta* a cualquier pregunta (ej: /ask ¿Qué experiencia tienes con RAG?).\n"
                "📌 */salary* — Filtra solo las ofertas con *salario publicado*.\n"
                "📌 */valencia* — Filtra solo las ofertas del *Área de Valencia*.\n"
                "📌 */remote* — Filtra solo las ofertas *100% Remotas* en España.\n"
                "📌 */metrics* — 📈 *Estudio de mercado:* empresas top, stack más demandado, experiencia y salarios.\n"
                "📌 */auditoria* — Comprueba ahora la evidencia operativa, sin rastrear portales.\n"
                "📌 */digest* — Resumen diario de mejores ofertas y tendencias.\n"
                "📌 */scan* — Fuerza un escaneo manual en los portales Python. LinkedIn se escanea desde la extensión.\n"
                "📌 */reset_seen* — Limpia la memoria de ofertas vistas para recibir todas de nuevo.\n"
                "📌 */stats* — Estadísticas de ofertas en memoria (limpieza auto > 2 días).\n"
                "📌 */pause* / */resume* — Pausa o reanuda las alertas de Telegram.\n"
                "📌 */exclude_list* — Lista de palabras excluidas.\n"
                "📌 */exclude_add palabra* — Añade palabras a la lista negra."
            )
            ctx.notifier.send_message(help_text)
            continue

        if cmd in {"/auditoria", "/audit", "/coverage"}:
            send_on_demand_coverage_audit(ctx, base_dir)
            continue
        if cmd in {"/health", "/salud", "/check"}:
            health_lines = ["🩺 *ESTADO DE PORTALES (ÚLTIMO CICLO)*", ""]
            if not CYCLE_LOGS:
                ctx.notifier.send_message("🩺 *Estado:* Esperando a que termine el primer ciclo de escaneo del bot...")
                continue
            
            last_log = CYCLE_LOGS[0]
            cycle_num = last_log.get("cycle_num", 0)
            timestamp = last_log.get("timestamp", "")
            stats = last_log.get("by_provider", {})
            
            health_lines.append(f"_Ciclo #{cycle_num} finalizado a las {timestamp}_")
            health_lines.append("")
            
            for name, data in stats.items():
                detected = data.get("detected", 0)
                http_429 = data.get("http_429", 0)
                status_flag = data.get("validation_status")
                blocked = data.get("blocked_reason")
                
                if status_flag is False:
                    health_lines.append(f"• *{name.title()}*: 🟠 PAUSADO `({blocked or 'Validación pendiente'})`")
                elif http_429 > 0:
                    health_lines.append(f"• *{name.title()}*: 🔴 BLOQUEADO `(Rate Limit / Captcha)`")
                elif blocked:
                    health_lines.append(f"• *{name.title()}*: 🔴 ERROR `({blocked})`")
                elif detected > 0:
                    health_lines.append(f"• *{name.title()}*: 🟢 OK `({detected} extraídas)`")
                else:
                    health_lines.append(f"• *{name.title()}*: 🟡 VACÍO `(0 extraídas)`")
                    
            validation_store = ProviderValidationStore(ctx.config.provider_validation_dir)
            skipped = 0
            for source in CONSULTANCY_SOURCES:
                if source.source in ctx.config.enabled_providers and source.source not in stats:
                    val_state = validation_store.get(source.source)
                    status_reason = val_state.get("reason", "Pendiente de validación")
                    health_lines.append(f"• *{source.source.title()}*: 🟠 CUARENTENA `({status_reason})`")
                    skipped += 1
                    
            health_lines.append("")
            health_lines.append(f"_Total activos en ciclo: {len([s for s in stats.values() if s.get('validation_status') is not False])} | Cuarentena: {skipped}_")
            ctx.notifier.send_message(chr(10).join(health_lines))
            continue
            
            last_log = CYCLE_LOGS[0]
            cycle_num = last_log.get("cycle_num", 0)
            timestamp = last_log.get("timestamp", "")
            stats = last_log.get("by_provider", {})
            
            health_lines.append(f"_Ciclo #{cycle_num} finalizado a las {timestamp}_
")
            
            for name, data in stats.items():
                detected = data.get("detected", 0)
                http_429 = data.get("http_429", 0)
                status_flag = data.get("validation_status")
                blocked = data.get("blocked_reason")
                
                if status_flag is False:
                    health_lines.append(f"• *{name.title()}*: 🟠 PAUSADO `({blocked or 'Validación pendiente'})`")
                elif http_429 > 0:
                    health_lines.append(f"• *{name.title()}*: 🔴 BLOQUEADO `(Rate Limit / Captcha)`")
                elif blocked:
                    health_lines.append(f"• *{name.title()}*: 🔴 ERROR `({blocked})`")
                elif detected > 0:
                    health_lines.append(f"• *{name.title()}*: 🟢 OK `({detected} extraídas)`")
                else:
                    health_lines.append(f"• *{name.title()}*: 🟡 VACÍO `(0 extraídas)`")
                    
            validation_store = ProviderValidationStore(ctx.config.provider_validation_dir)
            skipped = 0
            for source in CONSULTANCY_SOURCES:
                if source.source in ctx.config.enabled_providers and source.source not in stats:
                    val_state = validation_store.get(source.source)
                    status_reason = val_state.get("reason", "Pendiente de validación")
                    health_lines.append(f"• *{source.source.title()}*: 🟠 CUARENTENA `({status_reason})`")
                    skipped += 1
                    
            health_lines.append(f"
_Total activos en ciclo: {len([s for s in stats.values() if s.get('validation_status') is not False])} | Cuarentena: {skipped}_")
            ctx.notifier.send_message("
".join(health_lines))
            continue

            last_log = CYCLE_LOGS[0]
            cycle_num = last_log.get("cycle_num", 0)
            timestamp = last_log.get("timestamp", "")
            stats = last_log.get("by_provider", {})
            health_lines.append(f"_Ciclo #{cycle_num} finalizado a las {timestamp}_\\n")
            for name, data in stats.items():
                detected = data.get("detected", 0)
                http_429 = data.get("http_429", 0)
                status_flag = data.get("validation_status")
                blocked = data.get("blocked_reason")
                if status_flag is False:
                    health_lines.append(f"• *{name.title()}*: 🟠 PAUSADO `({blocked or 'Validación pendiente'})`")
                elif http_429 > 0:
                    health_lines.append(f"• *{name.title()}*: 🔴 BLOQUEADO `(Rate Limit / Captcha)`")
                elif blocked:
                    health_lines.append(f"• *{name.title()}*: 🔴 ERROR `({blocked})`")
                elif detected > 0:
                    health_lines.append(f"• *{name.title()}*: 🟢 OK `({detected} extraídas)`")
                else:
                    health_lines.append(f"• *{name.title()}*: 🟡 VACÍO `(0 extraídas)`")
            validation_store = ProviderValidationStore(ctx.config.provider_validation_dir)
            skipped = 0
            for source in CONSULTANCY_SOURCES:
                if source.source in ctx.config.enabled_providers and source.source not in stats:
                    val_state = validation_store.get(source.source)
                    status_reason = val_state.get("reason", "Pendiente de validación")
                    health_lines.append(f"• *{source.source.title()}*: 🟠 CUARENTENA `({status_reason})`")
                    skipped += 1
            health_lines.append(f"\\n_Total activos en ciclo: {len([s for s in stats.values() if s.get('validation_status') is not False])} | Cuarentena: {skipped}_")
            ctx.notifier.send_message("\\n".join(health_lines))
            continue
            
            last_log = CYCLE_LOGS[0]
            cycle_num = last_log.get("cycle_num", 0)
            timestamp = last_log.get("timestamp", "")
            stats = last_log.get("by_provider", {})
            
            health_lines.append(f"_Ciclo #{cycle_num} finalizado a las {timestamp}_
")
            
            for name, data in stats.items():
                detected = data.get("detected", 0)
                http_429 = data.get("http_429", 0)
                status_flag = data.get("validation_status")
                blocked = data.get("blocked_reason")
                
                if status_flag is False:
                    health_lines.append(f"• *{name.title()}*: 🟠 PAUSADO `({blocked or 'Validación pendiente'})`")
                elif http_429 > 0:
                    health_lines.append(f"• *{name.title()}*: 🔴 BLOQUEADO `(Rate Limit / Captcha)`")
                elif blocked:
                    health_lines.append(f"• *{name.title()}*: 🔴 ERROR `({blocked})`")
                elif detected > 0:
                    health_lines.append(f"• *{name.title()}*: 🟢 OK `({detected} extraídas)`")
                else:
                    health_lines.append(f"• *{name.title()}*: 🟡 VACÍO `(0 extraídas)`")
                    
            validation_store = ProviderValidationStore(ctx.config.provider_validation_dir)
            skipped = 0
            for source in CONSULTANCY_SOURCES:
                if source.source in ctx.config.enabled_providers and source.source not in stats:
                    val_state = validation_store.get(source.source)
                    status_reason = val_state.get("reason", "Pendiente de validación")
                    health_lines.append(f"• *{source.source.title()}*: 🟠 CUARENTENA `({status_reason})`")
                    skipped += 1
                    
            health_lines.append(f"
_Total activos en ciclo: {len([s for s in stats.values() if s.get('validation_status') is not False])} | Cuarentena: {skipped}_")
            ctx.notifier.send_message("
".join(health_lines))
            continue






        if cmd in {"/metrics", "/analytics", "/market", "/estudio"}:
            report = ctx.metrics.generate_analytics_report()
            dual_status = CURRENT_STATUS.get("linkedin_dual") or {}
            if getattr(ctx.config, "linkedin_extension_enabled", False):
                discrepancies = dual_status.get("last_discrepancies") or {}
                extension_age = dual_status.get("last_extension_complete_age_sec")
                api_age = dual_status.get("last_api_age_sec")
                extension_text = (
                    f"{int(extension_age // 60)} min"
                    if isinstance(extension_age, (int, float))
                    else "sin ciclo completo"
                )
                api_text = (
                    f"{int(api_age // 60)} min"
                    if isinstance(api_age, (int, float))
                    else "sin respaldo necesario"
                )
                channel_problems = [
                    f"{entry.get('extension', 'missing')}/{entry.get('api', 'not_queried')}"
                    for entry in dual_status.get("last_channel_states", [])
                    if entry.get("extension") != "complete"
                ]
                causes = (
                    ", ".join(channel_problems)
                    if channel_problems
                    else "sin fallos de canal"
                )
                report += (
                    "\n\n🔎 *Salud LinkedIn*\n"
                    f"Extensión completa: {extension_text} | respaldo API: {api_text}\n"
                    f"Coinciden DOM/producción: {discrepancies.get('matches', 0)} | "
                    f"solo producción: {discrepancies.get('only_production', 0)} | "
                    f"solo DOM de referencia: {discrepancies.get('only_reference', 0)}\n"
                    f"Ausencias elegibles: {discrepancies.get('eligible_absences', 0)}\n"
                    f"Respaldo API: {'activo' if dual_status.get('fallback_active') else 'inactivo'} | "
                    f"último lote parcial: {'sí' if dual_status.get('last_partial') else 'no'}\n"
                    f"Canales: {causes}"
                )
            ctx.notifier.send_message(report)
            continue

        if cmd in {"/ask", "/responder", "/answer", "/pregunta"}:
            if not arg:
                ctx.notifier.send_message(
                    "ℹ️ Escribe la pregunta del reclutador tras el comando.\n*Ejemplo:* `/ask ¿Qué experiencia tienes con RAG y FastAPI?`\nO indicando el número de oferta: `/ask 1 ¿Por qué te interesa nuestra empresa?`"
                )
                continue

            target_job = None
            clean_question = arg
            parts = arg.split(" ", 1)
            if len(parts) > 1 and (parts[0].isdigit() or len(parts[0]) > 5):
                target_job, _ = find_target_job(parts[0], LATEST_JOBS_CACHE, base_dir)
                clean_question = parts[1]
            else:
                target_job, _ = find_target_job("", LATEST_JOBS_CACHE, base_dir)

            ctx.notifier.send_message(
                "⏳ *Generando respuesta adaptada a tu perfil y proyectos reales...*"
            )
            ans_text = answer_custom_question(clean_question, target_job)
            ctx.notifier.send_message(ans_text)
            continue

        if cmd in {"/qa", "/questions", "/preguntas", "/answers", "/respuestas"}:
            target_job, err_msg = find_target_job(arg, LATEST_JOBS_CACHE, base_dir)
            if not target_job:
                ctx.notifier.send_message(
                    err_msg or "ℹ️ No se encontró la oferta solicitada."
                )
                continue

            ctx.notifier.send_message(
                f"⏳ *Generando Respuestas para Solicitud Sencilla:*\n*{target_job.title}* ({target_job.company})..."
            )
            qa_guide = generate_screening_answers(target_job)
            ctx.notifier.send_message(qa_guide)
            continue

        if cmd in {"/top", "/best"}:
            if not LATEST_JOBS_CACHE:
                LATEST_JOBS_CACHE = load_all_recent_jobs_from_disk(base_dir)
            if not LATEST_JOBS_CACHE:
                ctx.notifier.send_message("ℹ️ No hay ofertas en caché en este momento.")
            else:
                scored = []
                for j in LATEST_JOBS_CACHE[:50]:
                    score, tags, stack, sal, exp, mod, comp_type, fresh = (
                        calculate_match_score(
                            j.title, "", j.location, j.company, j.posted_within_1h
                        )
                    )
                    scored.append(
                        (score, j, tags, stack, sal, exp, mod, comp_type, fresh)
                    )
                scored.sort(key=lambda x: x[0], reverse=True)

                lines = ["🌟 *Top Ofertas con Mayor Afinidad (Últimos 2 Días):*\n"]
                for i, (
                    score,
                    j,
                    tags,
                    stack,
                    sal,
                    exp,
                    mod,
                    comp_type,
                    fresh,
                ) in enumerate(scored[:5], 1):
                    sal_str = f" | 💰 {sal}" if sal else ""
                    lines.append(
                        f"{i}. *{j.title}* ({j.company} - {comp_type})\n   🔥 Match: *{score}%*{sal_str} | 🎓 {exp} | 🏠 {mod}\n   📍 {j.location}\n   🔗 {j.url}\n"
                    )
                ctx.notifier.send_message("\n".join(lines))
            continue

        if cmd in {"/salary", "/salaries", "/sueldos"}:
            if not LATEST_JOBS_CACHE:
                LATEST_JOBS_CACHE = load_all_recent_jobs_from_disk(base_dir)
            with_salary = []
            for j in LATEST_JOBS_CACHE:
                score, tags, stack, sal, exp, mod, comp_type, fresh = (
                    calculate_match_score(
                        j.title, "", j.location, j.company, j.posted_within_1h
                    )
                )
                if sal and "Estimado" not in sal:
                    with_salary.append((score, j, sal, exp, mod, comp_type))

            if not with_salary:
                ctx.notifier.send_message(
                    "ℹ️ No hay ofertas con salario oficial explícito en la caché actual."
                )
            else:
                lines = ["💰 *Ofertas con Salario Oficial Publicado:*\n"]
                for i, (score, j, sal, exp, mod, comp_type) in enumerate(
                    with_salary[:5], 1
                ):
                    lines.append(
                        f"{i}. *{j.title}* ({j.company})\n   💰 *{sal}* | 🔥 Match: *{score}%* ({comp_type})\n   📍 {j.location} (🎓 {exp} | 🏠 {mod})\n   🔗 {j.url}\n"
                    )
                ctx.notifier.send_message("\n".join(lines))
            continue

        if cmd in {"/valencia", "/local"}:
            if not LATEST_JOBS_CACHE:
                LATEST_JOBS_CACHE = load_all_recent_jobs_from_disk(base_dir)
            val_jobs = [
                j
                for j in LATEST_JOBS_CACHE
                if any(
                    v in j.location.lower() or v in j.title.lower()
                    for v in [
                        "valencia",
                        "valència",
                        "paterna",
                        "almussafes",
                        "sagunto",
                    ]
                )
            ]
            if not val_jobs:
                ctx.notifier.send_message(
                    "ℹ️ No hay ofertas de Valencia en la caché actual."
                )
            else:
                lines = ["📍 *Ofertas en Valencia y Alrededores:*\n"]
                for i, j in enumerate(val_jobs[:5], 1):
                    score, _, _, sal, exp, mod, comp_type, fresh = (
                        calculate_match_score(
                            j.title, "", j.location, j.company, j.posted_within_1h
                        )
                    )
                    sal_str = f" | 💰 {sal}" if sal else ""
                    lines.append(
                        f"{i}. *{j.title}* ({j.company} - {comp_type})\n   🔥 Match: *{score}%*{sal_str} | 🎓 {exp} | 🏢 {mod}\n   📍 {j.location}\n   🔗 {j.url}\n"
                    )
                ctx.notifier.send_message("\n".join(lines))
            continue

        if cmd in {"/remote", "/remoto"}:
            if not LATEST_JOBS_CACHE:
                LATEST_JOBS_CACHE = load_all_recent_jobs_from_disk(base_dir)
            rem_jobs = [
                j
                for j in LATEST_JOBS_CACHE
                if "remoto" in j.location.lower()
                or "remoto" in j.title.lower()
                or "teletrabajo" in j.title.lower()
            ]
            if not rem_jobs:
                ctx.notifier.send_message(
                    "ℹ️ No hay ofertas 100% remotas en la caché actual."
                )
            else:
                lines = ["🏠 *Ofertas 100% Remotas en España:*\n"]
                for i, j in enumerate(rem_jobs[:5], 1):
                    score, _, _, sal, exp, mod, comp_type, fresh = (
                        calculate_match_score(
                            j.title, "", j.location, j.company, j.posted_within_1h
                        )
                    )
                    sal_str = f" | 💰 {sal}" if sal else ""
                    lines.append(
                        f"{i}. *{j.title}* ({j.company} - {comp_type})\n   🔥 Match: *{score}%*{sal_str} | 🎓 {exp} | 🏠 {mod}\n   📍 {j.location}\n   🔗 {j.url}\n"
                    )
                ctx.notifier.send_message("\n".join(lines))
            continue

        if cmd in {"/digest", "/summary"}:
            if not TODAY_DISCOVERED_JOBS and not LATEST_JOBS_CACHE:
                LATEST_JOBS_CACHE = load_all_recent_jobs_from_disk(base_dir)
            digest_msg = generate_daily_digest(
                TODAY_DISCOVERED_JOBS or LATEST_JOBS_CACHE
            )
            ctx.notifier.send_message(digest_msg)
            continue

        if cmd == "/project":
            target_job, err_msg = find_target_job(arg, LATEST_JOBS_CACHE, base_dir)
            if not target_job:
                ctx.notifier.send_message(
                    err_msg or "ℹ️ No se encontró la oferta solicitada."
                )
                continue

            ctx.notifier.send_message(build_project_prompt(target_job))
            continue

        if cmd in {"/aplicada", "/error"}:
            ctx.logger.info(f"Processing command {cmd} with arg {arg} and msg_id {msg_id}")
            target_job, err_msg = find_target_job(arg, LATEST_JOBS_CACHE, base_dir)
            ctx.logger.info(f"Target job found: {target_job is not None}")
            if not target_job:
                ctx.notifier.send_message(err_msg or "ℹ️ No se encontró la oferta solicitada.", reply_to_message_id=msg_id)
                continue
            
            status_file = base_dir / "data" / "ofertas_gestionadas.txt"
            status_text = "APLICADA" if cmd == "/aplicada" else "ERROR"
            
            # Escribir en txt (Legacy)
            with open(status_file, "a", encoding="utf-8") as f:
                f.write(f"\n--- {status_text} ---\n")
                f.write(f"Título: {target_job.title}\n")
                f.write(f"Empresa: {target_job.company}\n")
                f.write(f"Ubicación: {target_job.location}\n")
                f.write(f"URL: {target_job.url}\n")
                f.write(f"Fecha: {target_job.published_at}\n")
            
            # Guardar en SQLite (Nueva Arquitectura)
            try:
                db_layer = getattr(ctx, "db_storage", None)
                if db_layer is None and hasattr(ctx, "storage") and hasattr(ctx.storage, "db"):
                    db_layer = ctx.storage.db
                if db_layer and hasattr(db_layer, "record_interaction"):
                    db_layer.record_interaction(
                        target_job.id, 
                        target_job.source, 
                        target_job.title, 
                        target_job.company, 
                        target_job.location, 
                        status_text
                    )
            except Exception as exc:
                ctx.logger.error(f"Fallo al guardar interacción en SQLite: {exc}")

            emoji = "✅" if cmd == "/aplicada" else "❌"
            ctx.notifier.send_message(
                f"{emoji} Oferta marcada como *{status_text}* y guardada correctamente en el servidor.",
                reply_to_message_id=msg_id
            )
            continue

        if cmd in {"/tailor", "/cover"}:
            target_job, err_msg = find_target_job(arg, LATEST_JOBS_CACHE, base_dir)
            if not target_job:
                ctx.notifier.send_message(
                    err_msg or "ℹ️ No se encontró la oferta solicitada."
                )
                continue

            ctx.notifier.send_message(
                f"⏳ *Generando Carta de Presentación adaptada para:*\n*{target_job.title}* ({target_job.company})..."
            )
            letter = generate_cover_letter(target_job)
            ctx.notifier.send_message(
                f"📄 *CARTA DE PRESENTACIÓN ADAPTADA*\n\n{letter}"
            )
            continue

        if cmd in {"/cv", "/resume", "/curriculum"}:
            target_job, err_msg = find_target_job(arg, LATEST_JOBS_CACHE, base_dir)
            if not target_job:
                ctx.notifier.send_message(
                    err_msg or "ℹ️ No se encontró la oferta solicitada."
                )
                continue

            ctx.notifier.send_message(
                f"⏳ *Generando CV en PDF adaptado 1:1 (ATS 100%) para:*\n*{target_job.title}* ({target_job.company})..."
            )
            try:
                # If description is empty or short, perform fast deep enrichment
                if (
                    not getattr(target_job, "description", "")
                    or len(target_job.description) < 50
                ):
                    try:
                        target_job.description = enrich_job_description(
                            target_job, ctx.logger
                        )
                    except Exception:
                        pass

                pdf_file = generate_cv_pdf(
                    target_job, getattr(target_job, "description", "")
                )
                caption = (
                    f"📄 *CV PERSONALIZADO (ATS 100%)*\n"
                    f"💼 *Puesto:* {target_job.title}\n"
                    f"🏢 *Empresa:* {target_job.company}\n"
                    f"✨ *Proyectos y habilidades adaptados al 100% para superar filtros ATS.*"
                )
                sent_ok = ctx.notifier.send_document(pdf_file, caption=caption)
                if not sent_ok:
                    ctx.notifier.send_message(
                        f"✅ CV generado con éxito en el servidor: `{pdf_file}`"
                    )
            except Exception as exc:
                ctx.logger.error("Error generando CV PDF: %s", exc)
                ctx.notifier.send_message(f"❌ Error al compilar el CV en PDF: {exc}")
            continue

        if cmd == "/status":
            now = datetime.now()
            status_str = "PAUSADO ⏸️" if BOT_PAUSED else "ACTIVO 🟢"

            if CURRENT_STATUS.get("is_scraping_now"):
                start_dt = CURRENT_STATUS.get("last_cycle_start")
                elapsed_sec = int((now - start_dt).total_seconds()) if start_dt else 0
                time_str = start_dt.strftime("%H:%M:%S") if start_dt else "ahora"
                status_text = (
                    "📊 *ESTADO EN TIEMPO REAL DEL BOT*\n\n"
                    f"⚡ *Estado:* 🔍 *EJECUTANDO BÚSQUEDA AHORA MISMO en todos los portales...*\n"
                    f"⏱️ *Inicio del escaneo actual:* Hace {elapsed_sec}s ({time_str}h)\n"
                    f"🌐 *Portales en rastreo activo:* {', '.join([p.title() for p in ctx.config.enabled_providers])}\n"
                    "💬 *Telegram:* Hilo secundario independiente con long polling."
                )
            else:
                last_end = CURRENT_STATUS.get("last_cycle_end")
                next_est = CURRENT_STATUS.get("next_cycle_estimate")

                last_time_str = (
                    last_end.strftime("%H:%M:%S") if last_end else "Recién iniciado"
                )
                mins_ago = (
                    int((now - last_end).total_seconds() // 60) if last_end else 0
                )

                if next_est and next_est > now:
                    mins_next = int((next_est - now).total_seconds() // 60)
                    secs_next = int((next_est - now).total_seconds() % 60)
                    next_str = f"En ~{mins_next}m {secs_next}s ({next_est.strftime('%H:%M:%S')}h)"
                else:
                    next_str = "En breve..."

                last_stats = CURRENT_STATUS.get("last_cycle_stats") or {}
                cycle_num = last_stats.get(
                    "cycle_num", CURRENT_STATUS.get("total_cycles_completed", 0)
                )
                dur_sec = last_stats.get("duration_sec", 0)
                detected = last_stats.get("detected", 0)
                new_saved = last_stats.get("new_saved", 0)
                alerts_sent = last_stats.get("alerts_sent", 0)
                by_prov = last_stats.get("by_provider", {})

                prov_lines = []
                for p_name, p_stat in by_prov.items():
                    det_p = p_stat.get("detected", 0)
                    new_p = p_stat.get("saved", 0)
                    http_429 = p_stat.get("http_429", 0)
                    rate_note = f" | ⚠️ HTTP 429: {http_429}" if http_429 else ""
                    prov_lines.append(
                        f"  • *{p_name.title()}:* {det_p} evaluadas | ✨ {new_p} nuevas{rate_note}"
                    )

                prov_block = (
                    "\n".join(prov_lines) if prov_lines else "  • Escaneo completado."
                )
                extension_status = ""
                if getattr(ctx.config, "linkedin_extension_enabled", False):
                    extension_ingest = (
                        CURRENT_STATUS.get("last_linkedin_extension_ingest") or {}
                    )
                    dual_status = CURRENT_STATUS.get("linkedin_dual") or {}
                    ext_age = dual_status.get("last_extension_complete_age_sec")
                    api_age = dual_status.get("last_api_age_sec")
                    ext_age_text = (
                        f"{int(ext_age // 60)} min"
                        if isinstance(ext_age, (int, float))
                        else "sin dato"
                    )
                    api_age_text = (
                        f"{int(api_age // 60)} min"
                        if isinstance(api_age, (int, float))
                        else "sin dato"
                    )
                    comparison = dual_status.get("last_discrepancies") or {}
                    health = (
                        "degradado: respaldo API activo"
                        if dual_status.get("fallback_active")
                        else "extensión primaria; auditoría DOM activa"
                    )
                    if extension_ingest:
                        ingest_timestamp = extension_ingest.get("timestamp")
                        ingest_time = (
                            ingest_timestamp.strftime("%H:%M")
                            if isinstance(ingest_timestamp, datetime)
                            else "--:--"
                        )
                        extension_status = (
                            "\n\n🧩 *LinkedIn (extensión Chromium):* "
                            f"{extension_ingest.get('detected', 0)} evaluadas | "
                            f"✨ {extension_ingest.get('saved', 0)} nuevas | "
                            f"🔔 {extension_ingest.get('sent', 0)} alertas "
                            f"({ingest_time}h)\n"
                            f"  • Estado: {health}; extensión {ext_age_text}, respaldo API {api_age_text}\n"
                            f"  • Coinciden DOM/producción {comparison.get('matches', 0)} | "
                            f"solo producción {comparison.get('only_production', 0)} | "
                            f"solo DOM {comparison.get('only_reference', 0)} | "
                            f"parcial: {'sí' if dual_status.get('last_partial') else 'no'}"
                        )
                    else:
                        extension_status = (
                            "\n\n🧩 *LinkedIn (extensión Chromium):* todavía no ha recibido "
                            f"un lote completo. Estado: {health}; extensión {ext_age_text}, API {api_age_text}."
                        )

                status_text = (
                    "📊 *ESTADO EN TIEMPO REAL DEL BOT*\n\n"
                    f"• Estado general: *{status_str}* (escucha Telegram por long polling)\n"
                    f"• Última búsqueda realizada: *Hace {mins_ago} min* ({last_time_str}h)\n"
                    f"• Próxima búsqueda estimada: *{next_str}*\n"
                    f"• Total búsquedas completadas: *{CURRENT_STATUS.get('total_cycles_completed', 0)} ciclos*\n\n"
                    f"🔍 *Resultados de la Última Búsqueda (#{cycle_num}):*\n"
                    f"• Duración del escaneo: *{dur_sec}s*\n"
                    f"• Total ofertas evaluadas: *{detected}*\n"
                    f"• ✨ *Ofertas nuevas registradas:* *{new_saved}*\n"
                    f"• 🔔 *Alertas enviadas a Telegram:* *{alerts_sent}*\n\n"
                    f"🌐 *Desglose por Portal:*\n{prov_block}{extension_status}\n\n"
                    f"📜 Usa */history* para ver el historial de búsquedas o */latest* para ver las últimas ofertas."
                )
            ctx.notifier.send_message(status_text)
            continue

        if cmd in {"/history", "/cycles", "/historial"}:
            if not CYCLE_LOGS:
                ctx.notifier.send_message(
                    "ℹ️ El bot aún no ha completado su primer ciclo de búsqueda tras iniciarse. Usa /scan para forzar uno."
                )
            else:
                lines = ["📜 *REGISTRO HISTÓRICO DE BÚSQUEDAS RECIENTES*\n"]
                for i, log in enumerate(CYCLE_LOGS[:8], 1):
                    ts = log.get("timestamp", "--:--:--")
                    dur = log.get("duration_sec", 0)
                    det = log.get("detected", 0)
                    new_s = log.get("new_saved", 0)
                    sent_a = log.get("alerts_sent", 0)
                    http_429 = log.get("http_429", 0)
                    notif_str = (
                        f" | 🔔 *{sent_a} alertas*" if sent_a > 0 else " | 0 alertas"
                    )
                    rate_limit_str = f" | ⚠️ *{http_429} HTTP 429*" if http_429 else ""
                    lines.append(
                        f"{i}️⃣ *{ts}h* ({dur}s) — *{det}* evaluadas | ✨ *{new_s}* nuevas"
                        f"{notif_str}{rate_limit_str}"
                    )
                lines.append(
                    "\n💡 Usa */scan* para ejecutar un escaneo manual en tiempo real."
                )
                ctx.notifier.send_message("\n".join(lines))
            continue

        if cmd == "/latest":
            if not LATEST_JOBS_CACHE:
                ctx.notifier.send_message(
                    "ℹ️ No hay ofertas recientes en caché en este momento."
                )
            else:
                lines = ["🔥 *Últimas Ofertas Detectadas:*\n"]
                for i, j in enumerate(LATEST_JOBS_CACHE[:5], 1):
                    score, _, _, sal, exp, mod, comp_type, fresh = (
                        calculate_match_score(
                            j.title, "", j.location, j.company, j.posted_within_1h
                        )
                    )
                    sal_str = f" | 💰 {sal}" if sal else ""
                    lines.append(
                        f"{i}. *{j.title}* ({j.company} - {comp_type})\n   🔥 Match: *{score}%*{sal_str} | 🎓 {exp} | 🏠 {mod}\n   📍 {j.location}\n   🔗 {j.url}\n"
                    )
                lines.append(
                    "💡 *Tip:* Usa */tailor 1* para generar tu carta o */qa 1* para ver las respuestas."
                )
                ctx.notifier.send_message("\n".join(lines))
            continue

        if cmd == "/scan":
            scrape_lock = getattr(ctx, "scrape_lock", None)
            if scrape_lock is not None and not scrape_lock.acquire(blocking=False):
                ctx.notifier.send_message(
                    "⏳ Ya hay un ciclo automático en marcha. El /scan no se ejecuta en paralelo "
                    "para no bloquear ni duplicar las consultas. Inténtalo al terminar el ciclo."
                )
                continue

            extension_note = ""
            if getattr(ctx.config, "linkedin_extension_enabled", False):
                extension_note = (
                    "\n\n🧩 LinkedIn se recibe desde Chromium; para forzarlo ahora pulsa "
                    "*Escanear ahora* en la extensión de LinkedIn."
                )
            ctx.notifier.send_message(
                "🔄 *Iniciando escaneo manual con el mismo flujo y filtros del ciclo automático...*"
                + extension_note
            )
            total_sent = 0
            total_detected = 0
            total_http_429 = 0
            try:
                if providers_map:
                    # Preserve the scheduler's order as well as its filtering and
                    # delivery path, so /scan is a meaningful diagnostic.
                    for prov_name, provider in ordered_providers(providers_map):
                        try:
                            started = time.monotonic()
                            jobs = fetch_provider_jobs(
                                prov_name, provider, startup_deep_scan=False
                            )
                            stats = process_jobs(
                                jobs,
                                ctx,
                                send_alerts=True,
                                max_notifs=ctx.config.max_notifs_per_cycle,
                                first_cycle=False,
                                audit_origin="manual_scan",
                            )
                            total_detected += stats.detected
                            total_sent += stats.sent
                            http_429 = provider_http_429_count(provider)
                            total_http_429 += http_429
                            ctx.logger.info(
                                "Manual scan complete for %s | seconds=%.1f detected=%d eligible=%d "
                                "seen=%d saved=%d sent=%d http_429=%d blocked_reason=%s",
                                prov_name,
                                time.monotonic() - started,
                                stats.detected,
                                stats.eligible,
                                stats.seen,
                                stats.saved,
                                stats.sent,
                                http_429,
                                provider_blocked_reason(provider) or "none",
                            )
                        except Exception as exc:
                            ctx.logger.exception(
                                "Error scanning provider %s: %s", prov_name, exc
                            )
            finally:
                if scrape_lock is not None:
                    scrape_lock.release()

            rate_limit_note = ""
            if total_http_429:
                response_word = "respuesta" if total_http_429 == 1 else "respuestas"
                rate_limit_note = (
                    f" ⚠️ Se recibió {total_http_429} {response_word} HTTP 429."
                )
            ctx.notifier.send_message(
                f"✅ Escaneo manual completado. Se evaluaron {total_detected} ofertas y se enviaron {total_sent} nuevas."
                + rate_limit_note
                + (
                    " LinkedIn se procesa de forma independiente por la extensión."
                    if getattr(ctx.config, "linkedin_extension_enabled", False)
                    else ""
                )
            )
            continue

        if cmd in {"/reset_seen", "/clear_seen", "/reset"}:
            prev_count = ctx.storage.count()
            ctx.storage.purge_older_than_days(max_days=0)  # Purge all entries
            ctx.notifier.send_message(
                f"🧹 *Memoria de ofertas reiniciada con éxito.*\n"
                f"Se han eliminado *{prev_count}* registros previos de `seen_jobs.txt`.\n"
                f"El próximo ciclo o comando */scan* evaluará todas las ofertas activas como nuevas."
            )
            continue

        if cmd == "/stats":
            stats_text = (
                f"📈 *Estadísticas del Sistema*\n\n"
                f"• Ofertas registradas (últimos 2 días): *{ctx.storage.count()}*\n"
                f"• Límite de retención: *2 días / 48 horas* (limpieza automática activada)\n"
                f"• Palabras excluidas activas: *{len(ctx.config.exclude_words)}*"
            )
            ctx.notifier.send_message(stats_text)
            continue

        if cmd == "/pause":
            BOT_PAUSED = True
            ctx.notifier.send_message(
                "⏸️ *Notificaciones del bot PAUSADAS.* Usa /resume para reanudar."
            )
            continue

        if cmd == "/resume":
            BOT_PAUSED = False
            ctx.notifier.send_message("▶️ *Notificaciones del bot REANUDADAS.*")
            continue

        if cmd == "/exclude_list":
            words = (
                ", ".join(ctx.config.exclude_words)
                if ctx.config.exclude_words
                else "(vacio)"
            )
            ctx.notifier.send_message(f"Exclude words actuales:\n{words}")
            continue

        if cmd == "/exclude_add":
            add_words = _normalize_words(arg)
            if not add_words:
                ctx.notifier.send_message("Uso: /exclude_add palabra1,palabra2")
                continue
            active_additions, softened_additions = _partition_exclude_words(add_words)
            merged = list(dict.fromkeys(ctx.config.exclude_words + active_additions))
            ctx.config.exclude_words = merged
            save_runtime_exclude_words(
                base_dir, [*merged, *softened_additions], ctx.logger
            )
            messages: list[str] = []
            if active_additions:
                messages.append(
                    f"Añadidas a exclude_words: {', '.join(active_additions)}"
                )
            if softened_additions:
                messages.append(
                    "No activadas por ser demasiado generales: "
                    f"{', '.join(softened_additions)}. Usa una frase precisa de puesto o empresa."
                )
            ctx.notifier.send_message("\n".join(messages))
            continue

        if cmd == "/exclude_remove":
            rem_words = _normalize_words(arg)
            if not rem_words:
                ctx.notifier.send_message("Uso: /exclude_remove palabra1,palabra2")
                continue
            rem_set = set(rem_words)
            updated = [w for w in ctx.config.exclude_words if w not in rem_set]
            removed = [w for w in ctx.config.exclude_words if w in rem_set]
            ctx.config.exclude_words = updated
            save_runtime_exclude_words(base_dir, updated, ctx.logger)
            ctx.notifier.send_message(
                f"Eliminadas de exclude_words: {', '.join(removed) if removed else '(ninguna coincidencia)'}"
            )
            continue

        ctx.notifier.send_message(
            "Comando no reconocido. Usa /help para ver la lista de comandos disponibles."
        )

    return


def start_telegram_listener_thread(
    ctx: RuntimeContext,
    base_dir: Path,
    providers_ref: dict[str, dict[str, JobProvider]],
) -> threading.Thread:
    def _listener_loop():
        import asyncio
        from aiogram import Bot, Dispatcher, F
        from aiogram.types import Message, CallbackQuery
        
        bot = Bot(token=ctx.config.telegram_bot_token)
        dp = Dispatcher()

        @dp.message(F.text.startswith("/"))
        async def handle_message(message: Message):
            chat_id = str(message.chat.id)
            if chat_id != str(ctx.config.telegram_chat_id):
                return
            commands = [(message.message_id, message.text, message.message_id)]
            await asyncio.to_thread(
                process_telegram_commands,
                ctx, base_dir, commands, providers_ref.get("providers")
            )

        @dp.callback_query()
        async def handle_callback(callback: CallbackQuery):
            chat_id = str(callback.from_user.id)
            if chat_id != str(ctx.config.telegram_chat_id):
                return
            await callback.answer("⏳ Procesando...")
            msg_id = callback.message.message_id if callback.message else None
            commands = [(1, callback.data, msg_id)]
            await asyncio.to_thread(
                process_telegram_commands,
                ctx, base_dir, commands, providers_ref.get("providers")
            )

        async def main_aiogram():
            ctx.logger.info("Starting Aiogram Polling Loop!")
            await dp.start_polling(bot, handle_signals=False)

        # In a separate thread, we must create a new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(main_aiogram())
        except Exception as e:
            ctx.logger.error(f"Aiogram thread crashed: {e}")

    thread = threading.Thread(
        target=_listener_loop, name="TelegramAiogramListener", daemon=True
    )
    thread.start()
    return thread


def configure_logging(level: str) -> logging.Logger:
    logger = logging.getLogger("job-bot")
    logger.setLevel(level.upper())
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    handler.setFormatter(formatter)
    logger.handlers.clear()
    logger.addHandler(handler)
    return logger


def build_providers(
    config: BotConfig, logger: logging.Logger, playwright: Playwright | None = None
) -> dict[str, JobProvider]:
    providers: dict[str, JobProvider] = {}
    if "linkedin" in config.enabled_providers and not config.linkedin_extension_enabled:
        providers["linkedin"] = LinkedInProvider(config, logger, playwright)
    if "infojobs" in config.enabled_providers:
        providers["infojobs"] = InfoJobsProvider(config, logger, playwright)
    if "tecnoempleo" in config.enabled_providers:
        providers["tecnoempleo"] = TecnoempleoProvider(config, logger, playwright)
    if "manfred" in config.enabled_providers:
        providers["manfred"] = ManfredProvider(config, logger, playwright)
    if "indeed" in config.enabled_providers:
        providers["indeed"] = IndeedProvider(config, logger, playwright=playwright)
    if "remotive" in config.enabled_providers:
        providers["remotive"] = RemotiveProvider(config, logger, playwright)
    if (
        "wwr" in config.enabled_providers
        or "weworkremotely" in config.enabled_providers
    ):
        providers["wwr"] = WWRProvider(config, logger, playwright)
    if (
        "greenhouse_spain" in config.enabled_providers
        or "greenhouse" in config.enabled_providers
    ):
        providers["greenhouse_spain"] = GreenhouseSpainProvider(
            config, logger, playwright
        )
    if "remoteok" in config.enabled_providers:
        providers["remoteok"] = RemoteOKProvider(config, logger, playwright)
    if (
        "upv_sie" in config.enabled_providers
        or "upv" in config.enabled_providers
        or "sie" in config.enabled_providers
    ):
        providers["upv_sie"] = UPVSIEProvider(config, logger, playwright)
    if "experis" in config.enabled_providers:
        providers["experis"] = ExperisProvider(config, logger, playwright)
    if "accessiway" in config.enabled_providers:
        providers["accessiway"] = AccessiwayProvider(config, logger, playwright)
    if "sopra_steria" in config.enabled_providers:
        from providers.sopra_steria import SopraSteriaProvider
        providers["sopra_steria"] = SopraSteriaProvider(config, logger, playwright)
    if "systra" in config.enabled_providers:
        from providers.systra import SystraProvider
        providers["systra"] = SystraProvider(config, logger, playwright)
    if "accenture" in config.enabled_providers:
        from providers.accenture import AccentureProvider
        providers["accenture"] = AccentureProvider(config, logger, playwright)
    # Being listed in ENABLED_PROVIDERS is the explicit human activation step.
    # A consultancy also needs a successful, independently reviewed audit.
    validation_dir = getattr(
        config, "provider_validation_dir", "./data/provider_validation"
    )
    for source in CONSULTANCY_SOURCE_IDS:
        if source not in config.enabled_providers:
            continue
        if not provider_is_validated(source, validation_dir):
            logger.warning(
                "Consultancy source skipped pending validation | provider=%s", source
            )
            continue
        providers[source] = build_consultancy_provider(source, config, logger, playwright)
    return providers


def normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def _is_missing_location(location: str) -> bool:
    """Return true only for the explicit placeholders emitted by LinkedIn cards."""
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFD", normalize_text(location))
        if unicodedata.category(character) != "Mn"
    )
    return normalized in {"", "ubicacion no indicada", "location not specified"}


def _linkedin_extension_has_remote_search_scope(job: JobItem) -> bool:
    """Trust f_WT=2 only as location evidence from an authenticated card URL."""
    if normalize_text(job.source) != "linkedin":
        return False
    for search_url in linkedin_search_urls(job):
        parsed = urlsplit(search_url)
        hostname = (parsed.hostname or "").lower()
        if not hostname.endswith("linkedin.com"):
            continue
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            if key.lower() == "f_wt" and "2" in {item.strip() for item in value.split(",")}:
                return True
    return False


def _filter_phrase_matches(value: str, phrase: str) -> bool:
    """Match configured filters as whole normalized phrases, not substrings."""
    normalized_phrase = normalize_text(phrase)
    if not normalized_phrase:
        return False
    return bool(
        re.search(
            rf"(?<![\w]){re.escape(normalized_phrase)}(?![\w])",
            normalize_text(value),
        )
    )


def job_filter_reason(
    job: JobItem, config: BotConfig, description: str = ""
) -> str | None:
    # 0. Rechazar explícitamente roles de Senior o Lead por título
    if re.search(r"\b(?:senior|sr\.?|lead)\b", job.title, re.IGNORECASE):
        return "exclude"

    # 0.5. Rechazar por experiencia detectada en features (Generalist fix for Senior roles with generic titles)
    if getattr(job, "features", None) and isinstance(job.features, dict) and "experience" in job.features:
        exp = job.features["experience"]
        if isinstance(exp, dict):
            lvl = exp.get("level")
            min_y = exp.get("minimum_years")
            if lvl in ("Senior", "Lead / Principal") or (isinstance(min_y, (int, float)) and min_y >= 4):
                return "exclude"

    # 1. Filtro geográfico estricto para Rubén Gaona (Residencia: Valencia):
    # - Si es en Valencia y área metropolitana: Presencial, Híbrido o Remoto PERMITIDO.
    # - Si es fuera de Valencia (Madrid, Barcelona, Bilbao, etc.): SOLO 100% REMOTO PERMITIDO.
    location_viable = is_job_geographically_viable(job.location, job.title, description)
    is_linkedin_candidate = normalize_text(job.source) == "linkedin"
    # A configured LinkedIn remote search is stronger evidence than a card's
    # abbreviated location, which can be the employer HQ or "EMEA".
    if not location_viable and is_linkedin_candidate and _linkedin_extension_has_remote_search_scope(job):
        modality = ""
        if getattr(job, "features", None) and isinstance(job.features, dict) and "modality" in job.features:
            modality = job.features["modality"]
        else:
            from matcher import extract_modality
            modality = extract_modality(f"{job.title} {description} {job.location}", job.location)
            
        loc_lower = job.location.lower()
        # Si menciona otra ciudad de España explícitamente, NUNCA sobreescribir.
        import os
        import json
        RULES_PATH = os.path.join(os.path.dirname(__file__), 'config', 'rules.json')
        with open(RULES_PATH, 'r', encoding='utf-8') as f:
            OTHER_CITIES = json.load(f)['OTHER_CITIES']
        
        # Check location field and description text for explicit OTHER_CITIES
        desc_lower = (job.description or "").lower()
        is_explicit_other_city = False
        for city in OTHER_CITIES:
            if city in loc_lower or re.search(rf"\b{re.escape(city)}\b", desc_lower):
                is_explicit_other_city = True
                break

        # No sobreescribir si la descripción especifica explícitamente Presencial o Híbrido, ni si es el fallback
        if not is_explicit_other_city and "Presencial" not in modality and "Híbrido" not in modality:
            # GENERALIST FIX 2.0: If the location is a specific city (i.e. NOT a generic country/region), do NOT blindly trust the Remote search marker.
            is_generic_country = loc_lower in ("españa", "spain", "remote", "remoto", "teletrabajo", "emea", "europe", "europa", "iberia")
            if not is_generic_country and "Remoto" not in modality:
                pass # It's a specific city (like Illescas, Alcobendas). Don't override unless explicitly remote!
            else:
                location_viable = True
    if not location_viable:
        return "location"

    haystack = f"{job.title} {job.company} {job.location} {description}"
    # LinkedIn's configured URLs are the user-selected candidate scope. A
    # second generic keyword gate hid vacancies before relevance could assess
    # their title or enriched description.
    if (
        not is_linkedin_candidate
        and config.include_words
        and not any(_filter_phrase_matches(haystack, word) for word in config.include_words)
    ):
        return "include"
    # Exclusions are explicit overrides: restrict them to title/company rather
    # than incidental wording inside a long job description.
    title_and_company = f"{job.title} {job.company}"
    if config.exclude_words and any(
        _filter_phrase_matches(title_and_company, word) for word in config.exclude_words
    ):
        return "exclude"
    return None


def job_matches_filters(job: JobItem, config: BotConfig) -> bool:
    """Keep the previous boolean filter interface for callers outside the cycle."""
    return job_filter_reason(job, config, job.description) is None


@dataclass
class ProcessJobsStats:
    detected: int = 0
    eligible: int = 0
    discarded_time_window: int = 0
    unverified_time_window: int = 0
    discarded_location: int = 0
    discarded_include: int = 0
    discarded_exclude: int = 0
    discarded_relevance: int = 0
    relevance_warning: int = 0
    description_unavailable: int = 0
    # Kept for compatibility with existing metrics consumers. Missing detail
    # pages are now traceable but never silently discard an otherwise valid job.
    discarded_description_unavailable: int = 0
    duplicate_channels: int = 0
    seen: int = 0
    paused: int = 0
    notification_limit: int = 0
    alerts_disabled: int = 0
    delivery_failed: int = 0
    saved: int = 0
    sent: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "eligible": self.eligible,
            "discarded_time_window": self.discarded_time_window,
            "unverified_time_window": self.unverified_time_window,
            "discarded_location": self.discarded_location,
            "discarded_include": self.discarded_include,
            "discarded_exclude": self.discarded_exclude,
            "discarded_relevance": self.discarded_relevance,
            "relevance_warning": self.relevance_warning,
            "description_unavailable": self.description_unavailable,
            "discarded_description_unavailable": self.discarded_description_unavailable,
            "duplicate_channels": self.duplicate_channels,
            "seen": self.seen,
            "paused": self.paused,
            "notification_limit": self.notification_limit,
            "alerts_disabled": self.alerts_disabled,
            "delivery_failed": self.delivery_failed,
            "saved": self.saved,
            "sent": self.sent,
        }


from telegram_formatter import format_job_message


def process_jobs(
    jobs: Iterable[JobItem],
    ctx: RuntimeContext,
    send_alerts: bool,
    max_notifs: int,
    first_cycle: bool = False,
    channel_duplicates: int = 0,
    unlimited: bool = False,
    audit_origin: str = "scheduler",
    audit_run_id: str | None = None,
) -> ProcessJobsStats:
    global BOT_PAUSED, LATEST_JOBS_CACHE, TODAY_DISCOVERED_JOBS, TODAY_DISCOVERED_DATE
    stats = ProcessJobsStats()
    stats.duplicate_channels = channel_duplicates
    cycle_count = 0

    current_day = date.today()
    if TODAY_DISCOVERED_DATE != current_day:
        TODAY_DISCOVERED_JOBS.clear()
        TODAY_DISCOVERED_DATE = current_day

    jobs_list = list(jobs)
    
    # --- ASYNC BATCH ENRICHMENT (FISSURE 4 FIX) ---
    jobs_to_enrich = []
    for job in jobs_list:
        if normalize_text(job.source) == "linkedin":
            rec = evaluate_linkedin_recency(job)
            if rec.state in {"outside_window", "unverified"}:
                continue
        seen_ids = tuple(dict.fromkeys((job.id, *getattr(job, "aliases", ())) ))
        if hasattr(ctx.storage, "is_seen_any"):
            if ctx.storage.is_seen_any(job.source, seen_ids): continue
        else:
            if any(ctx.storage.is_seen(job.source, j_id) for j_id in seen_ids): continue
            
        initial_decision = evaluate_relevance(job, job.description)
        fingerprint = relevance_fingerprint(job)
        cached_decision = None
        if getattr(ctx, "relevance_cache", None) is not None:
            cached = ctx.relevance_cache.get(job.source, job.id, fingerprint)
            if cached: cached_decision = decision_from_dict(cached.get("decision"))
        decision = cached_decision or initial_decision
        if (
            cached_decision is None
            and decision.family not in {"rrhh_nominas", "cad_bim", "diseno_grafico", "mecanica_fabricacion", "plc_scada_puro", "rol_no_tecnico_o_gestion"}
            and len((job.description or "").strip()) < MIN_COMPLETE_DESCRIPTION_CHARS
        ):
            jobs_to_enrich.append(job)

    if jobs_to_enrich:
        async def _enrich_batch():
            import asyncio
            tasks = [enrich_job_description(j, ctx.logger) for j in jobs_to_enrich]
            return await asyncio.gather(*tasks, return_exceptions=True)
        
        import asyncio
        import concurrent.futures
        try:
            loop = asyncio.get_running_loop()
            is_running = loop.is_running()
        except RuntimeError:
            is_running = False
            
        if is_running:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, _enrich_batch())
                results = future.result()
        else:
            results = asyncio.run(_enrich_batch())
        for j, res in zip(jobs_to_enrich, results):
            if isinstance(res, str) and res:
                j.description = res
    # --- END ASYNC BATCH ---

    outcomes: dict[int, str] = {}
    try:
        for index, job in enumerate(jobs_list):
            stats.detected += 1
            if normalize_text(job.source) == "linkedin":
                recency = evaluate_linkedin_recency(job)
                source_features = dict(job.features or {})
                source_features["linkedin_recency"] = recency.as_dict()
                job.features = source_features
                # LinkedIn occasionally returns a card outside the f_TPR range.
                # Do not allow an ambiguous or stale card to reach seen/Telegram.
                if recency.state == "outside_window":
                    stats.discarded_time_window += 1
                    outcomes[index] = "discarded_time_window"
                    ctx.logger.info(
                        "LinkedIn discarded outside configured time window | id=%s "
                        "title=%r age_seconds=%s allowed_seconds=%s origins=%s",
                        job.id,
                        job.title,
                        recency.age_seconds,
                        recency.allowed_seconds,
                        ", ".join(recency.source_urls),
                    )
                    continue
                if recency.state == "unverified":
                    stats.unverified_time_window += 1
                    outcomes[index] = "unverified_time_window"
                    ctx.logger.warning(
                        "LinkedIn discarded because card age cannot be verified | id=%s "
                        "title=%r reason=%s origins=%s raw_ages=%s",
                        job.id,
                        job.title,
                        recency.reason,
                        ", ".join(recency.source_urls),
                        recency.raw_values,
                    )
                    continue
            seen_ids = tuple(dict.fromkeys((job.id, *getattr(job, "aliases", ()))))
            if hasattr(ctx.storage, "is_seen_any"):
                already_seen = ctx.storage.is_seen_any(job.source, seen_ids)
            else:
                already_seen = any(
                    ctx.storage.is_seen(job.source, job_id) for job_id in seen_ids
                )
            # Seen offers are deliberately checked before opening detail
            # pages, so a persistent card cannot generate repeated requests.
            if already_seen:
                stats.seen += 1
                outcomes[index] = "seen"
                continue

            initial_decision = evaluate_relevance(job, job.description)
            fingerprint = relevance_fingerprint(job)
            cached_decision: RelevanceDecision | None = None
            cache = getattr(ctx, "relevance_cache", None)
            if cache is not None:
                cached = cache.get(job.source, job.id, fingerprint)
                cached_decision = decision_from_dict(
                    cached.get("decision") if cached else None
                )

            # Clearly unrelated titles are rejected without a detail request.
            # New plausible and borderline cards are enriched before deciding.
            decision = cached_decision or initial_decision
            if (
                cached_decision is None
                and decision.family
                not in {"rrhh_nominas", "cad_bim", "diseno_grafico", "mecanica_fabricacion", "plc_scada_puro"}
                and len((job.description or "").strip()) < MIN_COMPLETE_DESCRIPTION_CHARS
            ):
                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _executor:
                        description = _executor.submit(
                            asyncio.run, enrich_job_description(job, ctx.logger)
                        ).result(timeout=15.0)
                except Exception as _enrich_err:
                    ctx.logger.warning("Enrichment failed for %s: %s", job.id, _enrich_err)
                    description = None
                if description:
                    job.description = description
                    decision = evaluate_relevance(job, description)
                else:
                    stats.description_unavailable += 1
            if decision.status in {"rejected", "warning"} and cache is not None:
                cache.put(
                    job.source,
                    job.id,
                    fingerprint,
                    decision.as_dict(),
                )
            source_features = dict(job.features or {})
            job.features = extract_job_features(job.title, job.description, job.location)
            for feature_key in (
                "extension_card",
                "linkedin_search_urls",
                "linkedin_recency_evidence",
                "linkedin_posted_text",
                "linkedin_published_at_raw",
                "linkedin_recency",
            ):
                if feature_key in source_features:
                    job.features[feature_key] = source_features[feature_key]
            job.features["relevance"] = decision.as_dict()
            if decision.status == "rejected":
                stats.discarded_relevance += 1
                outcomes[index] = f"discarded_relevance:{decision.family}"
                continue
            if decision.status == "warning":
                stats.relevance_warning += 1

            filter_reason = job_filter_reason(job, ctx.config, job.description)
            if filter_reason:
                if filter_reason == "location":
                    stats.discarded_location += 1
                    outcomes[index] = "discarded_location"
                elif filter_reason == "include":
                    stats.discarded_include += 1
                    outcomes[index] = "discarded_include"
                else:
                    stats.discarded_exclude += 1
                    outcomes[index] = "discarded_exclude"
                continue
            stats.eligible += 1

            # Update cache for /latest, /cv, and /tailor commands (keeping full 2-day history)
            LATEST_JOBS_CACHE = [job] + [j for j in LATEST_JOBS_CACHE if j.id != job.id][
                :300
            ]

            TODAY_DISCOVERED_JOBS = [job] + [
                j for j in TODAY_DISCOVERED_JOBS if j.id != job.id
            ][:150]

            # Record structured metrics in JSONL storage
            try:
                ctx.metrics.record_job(job)
            except Exception as exc:
                ctx.logger.warning("Failed to record metrics for job %s: %s", job.id, exc)

            should_alert = send_alerts or (
                first_cycle and getattr(job, "posted_within_1h", False)
            )

            if not should_alert:
                stats.alerts_disabled += 1
                outcomes[index] = "alerts_disabled"
                if first_cycle:
                    # If silent on start was requested, mark older baseline jobs as seen to avoid flood.
                    ctx.storage.add(job.source, job.id)
                    stats.saved += 1
                continue

            if BOT_PAUSED:
                stats.paused += 1
                outcomes[index] = "paused"
                continue

            # A zero cap means that every eligible, unseen offer is sent this cycle.
            if not unlimited and max_notifs > 0 and stats.sent >= max_notifs:
                stats.notification_limit += 1
                outcomes[index] = "notification_limit"
                continue

            if should_alert:
                cycle_count += 1
                
                # --- DEEP SCRAPE FOR LINKEDIN ---
                if job.source == "linkedin":
                    try:
                        import requests
                        from bs4 import BeautifulSoup
                        li_job_id = job.id.split("-")[-1] if "-" in job.id else job.id
                        li_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{li_job_id}"
                        r_desc = requests.get(li_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                        if r_desc.status_code == 200:
                            s_desc = BeautifulSoup(r_desc.text, "html.parser")
                            desc_div = s_desc.find("div", class_="show-more-less-html__markup")
                            if desc_div:
                                job.description = desc_div.get_text(separator=" ").strip()
                                ctx.logger.info("Deep scraped description for LinkedIn job %s", li_job_id)
                    except Exception as e:
                        ctx.logger.error(f"Deep fetch LinkedIn failed: {e}")
                # --------------------------------

                msg_text = format_job_message(
                    job, description=job.description, cycle_num=cycle_count
                )
                inline_buttons = {
                "inline_keyboard": [
                    [
                        {
                            "text": "✅ Aplicada",
                            "callback_data": f"/aplicada {job.id}",
                        },
                        {
                            "text": "❌ Error",
                            "callback_data": f"/error {job.id}",
                        },
                    ],
                ],
                }
                delivered = ctx.notifier.send_message(msg_text, reply_markup=inline_buttons)
                if delivered:
                    ctx.storage.add(job.source, job.id)
                    stats.saved += 1
                    stats.sent += 1
                    outcomes[index] = "sent"
                else:
                    # Keep it eligible for the next cycle if Telegram was unavailable.
                    stats.delivery_failed += 1
                    outcomes[index] = "delivery_failed"
    finally:
        ledger = getattr(ctx, "audit_ledger", None)
        if ledger is not None:
            try:
                ledger.record_jobs(jobs_list, outcomes, origin=audit_origin, run_id=audit_run_id)
            except Exception:
                ctx.logger.exception("Failed to persist per-job audit evidence")

    return stats


def maybe_run_daily_seen_cleanup(
    ctx: RuntimeContext, last_cleanup_date: date | None, base_dir: Path
) -> date | None:
    now = datetime.now()
    today = now.date()
    if last_cleanup_date == today:
        return last_cleanup_date

    # Automatically purge entries older than 7 days to prevent continuously repeated jobs
    removed = ctx.storage.purge_older_than_days(max_days=60)
    ctx.logger.info(
        "Daily 60-day seen cleanup executed | removed_older_than_60_days=%s remaining_in_memory=%s",
        removed,
        ctx.storage.count(),
    )
    retention = cleanup_operational_data(base_dir, ctx.config)
    ctx.logger.info("Operational retention cleanup | %s", retention)
    data_dir = base_dir / "data"
    browser_profiles = []
    for configured_path in (
        ctx.config.linkedin_session_dir,
        ctx.config.infojobs_session_dir,
        ctx.config.indeed_session_dir,
    ):
        candidate = Path(configured_path)
        browser_profiles.append(candidate if candidate.is_absolute() else base_dir / candidate)
    browser_cleanup = cleanup_browser_storage(
        data_dir,
        browser_profiles,
        ctx.config.browser_session_backup_retention_days,
    )
    ctx.logger.info("Browser storage cleanup | %s", browser_cleanup)
    return today


def maybe_send_daily_digest(
    ctx: RuntimeContext, last_digest_date: date | None
) -> date | None:
    global TODAY_DISCOVERED_DATE
    now = datetime.now()
    today = now.date()
    if TODAY_DISCOVERED_DATE != today:
        TODAY_DISCOVERED_JOBS.clear()
        TODAY_DISCOVERED_DATE = today
    if last_digest_date == today:
        return last_digest_date

    # Trigger at 20:00 PM
    if now.hour == DAILY_DIGEST_HOUR:
        ctx.logger.info("Sending scheduled Daily Digest report at 20:00...")
        digest_msg = generate_daily_digest(TODAY_DISCOVERED_JOBS)
        ctx.notifier.send_message(digest_msg)
        return today

    return last_digest_date


def run() -> None:
    global TODAY_DISCOVERED_JOBS, TODAY_DISCOVERED_DATE, LATEST_JOBS_CACHE, CYCLE_LOGS, CURRENT_STATUS
    config = load_config()
    config.poll_seconds = int(os.getenv("POLL_SECONDS", "900"))
    TODAY_DISCOVERED_JOBS = []
    TODAY_DISCOVERED_DATE = date.today()

    logger = configure_logging(config.log_level)
    notifier = TelegramNotifier(config, logger)
    base_dir = Path(__file__).resolve().parent
    db = DatabaseStorage(base_dir / "data" / "bot_memory.db")
    storage = SQLiteSeenStorage(db)
    metrics = MetricsStorage(base_dir / "data" / METRICS_DATA_FILE, logger)
    audit_ledger = JobAuditLedger(base_dir / "data", logger)
    ctx = RuntimeContext(
        config=config,
        logger=logger,
        notifier=notifier,
        storage=storage,
        metrics=metrics,
        audit_ledger=audit_ledger,
        relevance_cache=SQLiteRelevanceCache(db),
    )
    config.exclude_words = load_runtime_exclude_words(
        base_dir, config.exclude_words, logger
    )

    # The browser extension is intentionally hosted by this process, rather
    # than by a second Python service. This keeps pause state, seen IDs and
    # Telegram delivery identical to the normal provider flow.
    extension_bridge: ExtensionBridge | None = None
    linkedin_dual: LinkedInDualCoordinator | None = None
    extension_first_ingest = True
    if config.linkedin_extension_enabled:
        linkedin_provider = LinkedInProvider(config, logger)

        def deliver_linkedin_jobs(
            jobs: list[JobItem],
            send_alerts: bool,
            first_cycle: bool,
            channel_duplicates: int,
            run_id: str,
        ) -> dict[str, int]:
            """Deliver the reconciled LinkedIn union exactly once."""
            nonlocal extension_first_ingest
            started = time.monotonic()
            stats = process_jobs(
                jobs,
                ctx,
                send_alerts=send_alerts,
                max_notifs=0,
                first_cycle=first_cycle,
                channel_duplicates=channel_duplicates,
                unlimited=True,
                audit_origin="linkedin_dual",
                audit_run_id=run_id,
            )
            result = stats.as_dict()
            CURRENT_STATUS["last_linkedin_extension_ingest"] = {
                "timestamp": datetime.now(),
                "duration_sec": round(time.monotonic() - started, 1),
                **result,
            }
            logger.info(
                "LinkedIn reconciled cycle | seconds=%.1f detected=%d eligible=%d "
                "discarded_time_window=%d unverified_time_window=%d "
                "discarded_location=%d discarded_include=%d discarded_exclude=%d "
                "discarded_relevance=%d relevance_warning=%d "
                "description_unavailable=%d channel_duplicates=%d "
                "seen=%d paused=%d notification_limit=%d alerts_disabled=%d "
                "delivery_failed=%d saved=%d sent=%d",
                time.monotonic() - started,
                stats.detected,
                stats.eligible,
                stats.discarded_time_window,
                stats.unverified_time_window,
                stats.discarded_location,
                stats.discarded_include,
                stats.discarded_exclude,
                stats.discarded_relevance,
                stats.relevance_warning,
                stats.description_unavailable,
                stats.duplicate_channels,
                stats.seen,
                stats.paused,
                stats.notification_limit,
                stats.alerts_disabled,
                stats.delivery_failed,
                stats.saved,
                stats.sent,
            )
            return result

        def linkedin_audit_eligible(job: JobItem) -> bool:
            """Apply the same central eligibility rule without mutating seen state."""
            return (
                evaluate_linkedin_recency(job).state == "accepted"
                and
                evaluate_relevance(job, job.description).status != "rejected"
                and job_filter_reason(job, config, job.description) is None
            )

        linkedin_dual = LinkedInDualCoordinator(
            provider=linkedin_provider,
            data_dir=base_dir / "data",
            logger=logger,
            deliver=deliver_linkedin_jobs,
            audit_eligible=linkedin_audit_eligible,
        )

        def ingest_linkedin_extension_batch(batch: ExtensionBatch) -> dict[str, Any]:
            nonlocal extension_first_ingest
            started = time.monotonic()
            with ctx.linkedin_lock:
                result = linkedin_dual.ingest_extension(
                    batch,
                    send_alerts=not (extension_first_ingest and config.silent_on_start),
                    first_cycle=extension_first_ingest,
                )
                extension_first_ingest = False
            CURRENT_STATUS["linkedin_dual"] = linkedin_dual.status()
            logger.info(
                "LinkedIn extension batch reconciled | run_id=%s seconds=%.1f unique=%d matches=%d "
                "only_production=%d only_reference=%d partial=%s",
                batch.run_id,
                time.monotonic() - started,
                result.get("unique_jobs", 0),
                result.get("matches", 0),
                result.get("only_production", 0),
                result.get("only_reference", 0),
                result.get("partial", False),
            )
            return result

        extension_bridge = ExtensionBridge(
            config, logger, ingest_linkedin_extension_batch
        )
        extension_bridge.start()
        logger.info(
            "LinkedIn mode enabled: Chromium is primary; the public API is only a delayed fallback."
        )

    # Pre-cargar caché de ofertas de los últimos 2 días desde disco para respuesta inmediata
    LATEST_JOBS_CACHE = load_all_recent_jobs_from_disk(base_dir, max_days=2)
    logger.info(
        "Pre-loaded %d recent jobs (last 2 days) into memory cache.",
        len(LATEST_JOBS_CACHE),
    )

    enabled_lines = [f"- {p.title()}" for p in config.enabled_providers]
    enabled_block = "\n".join(enabled_lines)

    notifier.send_message(
        "🚀 *Bot de Empleo Iniciado y en Ejecución*\n\n"
        "Buscando activamente en:\n"
        f"{enabled_block}\n\n"
        f"🎯 *Match Scoring & Salario:* Activados\n"
        f"⏱️ Intervalo de sondeo: *{config.poll_seconds}s* (15 min)\n"
        f"📈 *Métricas de Mercado:* Guardando en `{METRICS_DATA_FILE}`\n"
        f"🧹 Limpieza automática: *Ofertas > 2 días*\n"
        f"📊 Resumen diario: *20:00h*\n"
        f"💬 Usa */help*, */metrics* o */tailor 1* en Telegram."
    )

    first_cycle = True
    last_cleanup_date: date | None = None
    last_digest_date: date | None = None

    # Start before scraping so commands remain available while providers are running.
    providers_ref: dict[str, Any] = {"providers": None, "linkedin_dual": linkedin_dual}
    start_telegram_listener_thread(ctx, base_dir, providers_ref)

    with sync_playwright() as p:
        providers = build_providers(config, logger, playwright=p)
        providers_ref["providers"] = providers

        # Check session health for active providers
        for name, provider in providers.items():
            if hasattr(provider, "check_session"):
                ok, detail = provider.check_session()
                logger.info("Provider %s session check: OK=%s (%s)", name, ok, detail)

        while True:
            should_send_alerts = (
                True  # Desactivado silent_on_start: enviar alertas desde el ciclo 1
            )
            cycle_start = datetime.now()
            CURRENT_STATUS["is_scraping_now"] = True
            CURRENT_STATUS["last_cycle_start"] = cycle_start

            total_detected = 0
            total_saved = 0
            total_sent = 0
            total_http_429 = 0
            prov_stats: dict[str, dict[str, Any]] = {}

            try:
                now = datetime.now()
                # 8:00 AM Morning Sweep: If it's 8:00 AM, force deep scan prioritizing 10h window
                is_morning_8am_sweep = (
                    now.hour == 8 and now.minute < 15
                ) or first_cycle

                if is_morning_8am_sweep and not first_cycle:
                    logger.info(
                        "☀️ Morning 8:00 AM Sweep triggered! Prioritizing 10h overnight window scan..."
                    )

                last_cleanup_date = maybe_run_daily_seen_cleanup(
                    ctx, last_cleanup_date, base_dir
                )
                last_digest_date = maybe_send_daily_digest(ctx, last_digest_date)

                # /scan and the scheduled cycle share this lock: overlapping requests
                # can trigger provider rate limits and corrupt the diagnostic comparison.
                with ctx.scrape_lock:
                    if linkedin_dual is not None:
                        # Keep the public fallback linear with a browser batch,
                        # without serializing unrelated provider requests.
                        with ctx.linkedin_lock:
                            fallback_result = linkedin_dual.fallback_if_due(
                                send_alerts=should_send_alerts,
                                first_cycle=extension_first_ingest,
                            )
                        CURRENT_STATUS["linkedin_dual"] = linkedin_dual.status()
                        if fallback_result is not None:
                            extension_first_ingest = False
                            linkedin_stats = fallback_result.get("delivery", {})
                            prov_stats["linkedin"] = dict(linkedin_stats)
                            total_detected += int(linkedin_stats.get("detected", 0))
                            total_saved += int(linkedin_stats.get("saved", 0))
                            total_sent += int(linkedin_stats.get("sent", 0))
                            total_http_429 += int(linkedin_stats.get("http_429", 0))
                    ordered = ordered_providers(providers)
                    for provider_index, (prov_name, provider) in enumerate(ordered):
                        # An asynchronous audit can downgrade a source after it was
                        # built. Do not keep delivering from it in later cycles.
                        if (
                            prov_name in CONSULTANCY_SOURCE_IDS
                            and not provider_is_validated(
                                prov_name, ctx.config.provider_validation_dir
                            )
                        ):
                            validation_state = ProviderValidationStore(
                                ctx.config.provider_validation_dir
                            ).get(prov_name)
                            provider_stats = ProcessJobsStats().as_dict()
                            provider_stats.update(
                                {
                                    "http_429": 0,
                                    "blocked_reason": str(
                                        validation_state.get("reason", "")
                                    ),
                                    "validation_status": str(
                                        validation_state.get(
                                            "status", "pending_validation"
                                        )
                                    ),
                                    "validation_visible_count": validation_state.get(
                                        "visible_count"
                                    ),
                                    "validation_matches": validation_state.get(
                                        "matches"
                                    ),
                                    "validation_eligible_missing": validation_state.get(
                                        "eligible_missing"
                                    ),
                                    "validation_last_correct_at": validation_state.get(
                                        "last_correct_at"
                                    ),
                                    "validation_ordering": validation_state.get(
                                        "ordering", ""
                                    ),
                                    "validation_anomaly": "skipped_not_validated",
                                }
                            )
                            prov_stats[prov_name] = provider_stats
                            logger.warning(
                                "Consultancy source skipped by validation state | provider=%s status=%s reason=%s",
                                prov_name,
                                provider_stats["validation_status"],
                                provider_stats["blocked_reason"] or "none",
                            )
                            if provider_index < len(ordered) - 1:
                                wait_between_providers(config, logger)
                            continue
                        try:
                            provider_started = time.monotonic()
                            logger.info(
                                "Provider cycle started | provider=%s", prov_name
                            )
                            jobs = fetch_provider_jobs(
                                prov_name,
                                provider,
                                startup_deep_scan=is_morning_8am_sweep,
                            )

                            stats = process_jobs(
                                jobs,
                                ctx,
                                send_alerts=should_send_alerts,
                                max_notifs=config.max_notifs_per_cycle,
                                first_cycle=first_cycle,
                                audit_origin="scheduler",
                            )
                            http_429 = provider_http_429_count(provider)
                            provider_stats = stats.as_dict()
                            provider_stats["http_429"] = http_429
                            provider_stats["blocked_reason"] = provider_blocked_reason(
                                provider
                            )
                            if prov_name in CONSULTANCY_SOURCE_IDS:
                                validation_store = ProviderValidationStore(
                                    ctx.config.provider_validation_dir
                                )
                                validation_state = validation_store.get(prov_name)
                                anomaly = record_runtime_observation(
                                    prov_name,
                                    ctx.config,
                                    count=stats.detected,
                                    blocked_reason=provider_stats["blocked_reason"],
                                )
                                provider_stats["validation_status"] = (
                                    validation_state.get("status", "pending_validation")
                                )
                                provider_stats["validation_visible_count"] = (
                                    validation_state.get("visible_count")
                                )
                                provider_stats["validation_matches"] = (
                                    validation_state.get("matches")
                                )
                                provider_stats["validation_eligible_missing"] = (
                                    validation_state.get("eligible_missing")
                                )
                                provider_stats["validation_last_correct_at"] = (
                                    validation_state.get("last_correct_at")
                                )
                                provider_stats["validation_ordering"] = (
                                    validation_state.get("ordering", "")
                                )
                                provider_stats["validation_anomaly"] = anomaly
                                if anomaly:
                                    schedule_anomaly_audit(
                                        prov_name,
                                        ctx.config,
                                        ctx.logger,
                                        lambda job: job_filter_reason(job, ctx.config),
                                        anomaly,
                                    )
                            prov_stats[prov_name] = provider_stats
                            total_detected += stats.detected
                            total_saved += stats.saved
                            total_sent += stats.sent
                            total_http_429 += http_429
                            logger.info(
                                "Cycle complete for %s | seconds=%.1f detected=%d eligible=%d "
                                "discarded_time_window=%d unverified_time_window=%d "
                                "discarded_location=%d discarded_include=%d discarded_exclude=%d "
                                "discarded_relevance=%d relevance_warning=%d "
                                "description_unavailable=%d "
                                "seen=%d paused=%d notification_limit=%d alerts_disabled=%d "
                                "delivery_failed=%d saved=%d sent=%d http_429=%d blocked_reason=%s",
                                prov_name,
                                time.monotonic() - provider_started,
                                stats.detected,
                                stats.eligible,
                                stats.discarded_time_window,
                                stats.unverified_time_window,
                                stats.discarded_location,
                                stats.discarded_include,
                                stats.discarded_exclude,
                                stats.discarded_relevance,
                                stats.relevance_warning,
                                stats.description_unavailable,
                                stats.seen,
                                stats.paused,
                                stats.notification_limit,
                                stats.alerts_disabled,
                                stats.delivery_failed,
                                stats.saved,
                                stats.sent,
                                http_429,
                                provider_stats["blocked_reason"] or "none",
                            )
                        except Exception as exc:
                            logger.exception(
                                "Error executing provider %s: %s", prov_name, exc
                            )
                        if provider_index < len(ordered) - 1:
                            wait_between_providers(config, logger)

                first_cycle = False

            except Exception as exc:
                logger.exception("Error in main loop cycle: %s", exc)

            cycle_end = datetime.now()
            dur_sec = round((cycle_end - cycle_start).total_seconds(), 1)
            CURRENT_STATUS["is_scraping_now"] = False
            CURRENT_STATUS["last_cycle_end"] = cycle_end
            CURRENT_STATUS["total_cycles_completed"] += 1

            jitter = random.randint(-config.jitter_seconds, config.jitter_seconds)
            sleep_time = max(10, config.poll_seconds + jitter)
            CURRENT_STATUS["next_cycle_estimate"] = cycle_end + timedelta(
                seconds=sleep_time
            )

            log_entry = {
                "cycle_num": CURRENT_STATUS["total_cycles_completed"],
                "timestamp": cycle_end.strftime("%H:%M:%S"),
                "date": cycle_end.strftime("%d/%m/%Y"),
                "duration_sec": dur_sec,
                "detected": total_detected,
                "new_saved": total_saved,
                "alerts_sent": total_sent,
                "http_429": total_http_429,
                "by_provider": prov_stats,
            }
            CURRENT_STATUS["last_cycle_stats"] = log_entry
            CYCLE_LOGS.insert(0, log_entry)
            CYCLE_LOGS = CYCLE_LOGS[:20]

            append_rate_limit_metrics(base_dir, logger, log_entry)
            logger.info(
                "Cycle summary | cycle=%d detected=%d saved=%d sent=%d http_429=%d",
                log_entry["cycle_num"],
                total_detected,
                total_saved,
                total_sent,
                total_http_429,
            )

            logger.info("Sleeping for %d seconds (~15 min)...", sleep_time)
            time.sleep(sleep_time)


if __name__ == "__main__":
    run()
