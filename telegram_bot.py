from __future__ import annotations
import asyncio
import logging
import re
import threading
from pathlib import Path
from typing import Any
import json

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery

from shared_state import CURRENT_STATUS, CYCLE_LOGS
import shared_state

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
                "📌 */local* — Filtra solo las ofertas del *Área de tu área local*.\n"
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
            health_lines = ["🩺 *ESTADO DE PORTALES (ÚLTIMO CICLO)*\n"]
            if not CYCLE_LOGS:
                ctx.notifier.send_message(
                    "🩺 *Estado:* Esperando a que termine el primer ciclo de escaneo del bot..."
                )
                continue

            last_log = CYCLE_LOGS[0]
            cycle_num = last_log.get("cycle_num", 0)
            timestamp = last_log.get("timestamp", "")
            stats = last_log.get("by_provider", {})

            health_lines.append(f"_Ciclo #{cycle_num} finalizado a las {timestamp}_\n")

            for name, data in stats.items():
                detected = data.get("detected", 0)
                http_429 = data.get("http_429", 0)
                status_flag = data.get("validation_status")
                blocked = data.get("blocked_reason")

                if status_flag is False:
                    health_lines.append(
                        f"• *{name.title()}*: 🟠 PAUSADO `({blocked or 'Validación pendiente'})`"
                    )
                elif http_429 > 0:
                    health_lines.append(
                        f"• *{name.title()}*: 🔴 BLOQUEADO `(Rate Limit / Captcha)`"
                    )
                elif blocked:
                    health_lines.append(f"• *{name.title()}*: 🔴 ERROR `({blocked})`")
                elif detected > 0:
                    health_lines.append(
                        f"• *{name.title()}*: 🟢 OK `({detected} extraídas)`"
                    )
                else:
                    health_lines.append(f"• *{name.title()}*: 🟡 VACÍO `(0 extraídas)`")

            validation_store = ProviderValidationStore(
                ctx.config.provider_validation_dir
            )
            skipped = 0
            for source in CONSULTANCY_SOURCES:
                if (
                    source.source in ctx.config.enabled_providers
                    and source.source not in stats
                ):
                    val_state = validation_store.get(source.source)
                    status_reason = val_state.get("reason", "Pendiente de validación")
                    health_lines.append(
                        f"• *{source.source.title()}*: 🟠 CUARENTENA `({status_reason})`"
                    )
                    skipped += 1

            health_lines.append(
                f"\n_Total activos en ciclo: {len([s for s in stats.values() if s.get('validation_status') is not False])} | Cuarentena: {skipped}_"
            )
            ctx.notifier.send_message("\n".join(health_lines))
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

        if cmd in {"/local", "/local"}:
            if not LATEST_JOBS_CACHE:
                LATEST_JOBS_CACHE = load_all_recent_jobs_from_disk(base_dir)
            val_jobs = [
                j
                for j in LATEST_JOBS_CACHE
                if any(
                    v in j.location.lower() or v in j.title.lower()
                    for v in [
                        "tu área local",
                        "valència",
                        "paterna",
                        "almussafes",
                        "sagunto",
                    ]
                )
            ]
            if not val_jobs:
                ctx.notifier.send_message(
                    "ℹ️ No hay ofertas de tu área local en la caché actual."
                )
            else:
                lines = ["📍 *Ofertas en tu área local y Alrededores:*\n"]
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
            ctx.logger.info(
                f"Processing command {cmd} with arg {arg} and msg_id {msg_id}"
            )
            target_job, err_msg = find_target_job(arg, LATEST_JOBS_CACHE, base_dir)
            ctx.logger.info(f"Target job found: {target_job is not None}")
            if not target_job:
                ctx.notifier.send_message(
                    err_msg or "ℹ️ No se encontró la oferta solicitada.",
                    reply_to_message_id=msg_id,
                )
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
                if (
                    db_layer is None
                    and hasattr(ctx, "storage")
                    and hasattr(ctx.storage, "db")
                ):
                    db_layer = ctx.storage.db
                if db_layer and hasattr(db_layer, "record_interaction"):
                    db_layer.record_interaction(
                        target_job.id,
                        target_job.source,
                        target_job.title,
                        target_job.company,
                        target_job.location,
                        status_text,
                    )
            except Exception as exc:
                ctx.logger.error(f"Fallo al guardar interacción en SQLite: {exc}")

            emoji = "✅" if cmd == "/aplicada" else "❌"
            ctx.notifier.send_message(
                f"{emoji} Oferta marcada como *{status_text}* y guardada correctamente en el servidor.",
                reply_to_message_id=msg_id,
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
        from aiogram import Bot, Dispatcher, F
        from aiogram.types import CallbackQuery, Message

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
                ctx,
                base_dir,
                commands,
                providers_ref.get("providers"),
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
                ctx,
                base_dir,
                commands,
                providers_ref.get("providers"),
            )

        async def main_aiogram():
            ctx.logger.info("Starting Aiogram Polling Loop!")
            await dp.start_polling(bot, handle_signals=False)

        def thread_loop():
            while True:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(main_aiogram())
                except Exception as e:
                    ctx.logger.error(f"Aiogram thread crashed: {e}")
                finally:
                    try:
                        loop.close()
                    except Exception:
                        pass
                import time
                time.sleep(5)
                ctx.logger.info("Restarting Aiogram thread...")

        thread = threading.Thread(
            target=thread_loop, name="TelegramAiogramListener", daemon=True
        )
    thread.start()
    return thread
