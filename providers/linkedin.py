from __future__ import annotations
import httpx
import asyncio
import time

"""Public LinkedIn first-page reader with no relevance filters."""


import logging
import random

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup  # type: ignore[import-untyped]
from curl_cffi import requests  # type: ignore[import-untyped]

from config import BotConfig
from models import JobItem
from providers.linkedin_common import (
    canonical_identity,
    canonical_job_url,
    exact_search_url,
    expanded_search_urls,
    merge_linkedin_jobs,
    normalise_job,
)

FetchState = Literal["ok", "empty", "partial", "blocked", "rate_limited", "failed"]

# The public guest endpoint normally returns results in ten-card fragments.
# Without a continuation request it cannot prove that such a fragment is the
# complete configured first page, so the browser remains the authority.
GUEST_FRAGMENT_SIZE = 10


@dataclass(frozen=True)
class LinkedInFetchResult:
    """Representa el resultado de una solicitud de obtención de empleos en LinkedIn.

    Atributos:
        search_url (str): La URL de búsqueda solicitada.
        endpoint_url (str): La URL del endpoint interno al que se realizó la solicitud.
        state (FetchState): Estado final de la solicitud (ok, empty, partial, blocked, etc.).
        http_status (int | None): Código de estado HTTP de la respuesta.
        jobs (tuple[JobItem, ...]): Tupla de trabajos extraídos exitosamente.
        raw_cards (int): Número bruto de tarjetas devueltas por la respuesta.
        parsed_cards (int): Número de tarjetas analizadas con éxito.
        incomplete_cards (int): Número de tarjetas que tenían información incompleta.
        error (str): Mensaje de error, si hubo alguno.
    """
    search_url: str
    endpoint_url: str
    state: FetchState
    http_status: int | None
    jobs: tuple[JobItem, ...]
    raw_cards: int
    parsed_cards: int
    incomplete_cards: int
    error: str = ""

    @property
    def complete(self) -> bool:
        """Indica si el resultado se obtuvo completamente sin errores ni bloqueos.

        Devuelve:
            bool: Verdadero si el estado es 'ok' o 'empty'.
        """
        return self.state in {"ok", "empty"}

    def as_dict(self) -> dict[str, object]:
        """Convierte los resultados en un diccionario para la serialización.

        Devuelve:
            dict[str, object]: Diccionario que contiene las propiedades del resultado.
        """
        return {
            "search_url": self.search_url,
            "endpoint_url": self.endpoint_url,
            "state": self.state,
            "http_status": self.http_status,
            "raw_cards": self.raw_cards,
            "parsed_cards": self.parsed_cards,
            "incomplete_cards": self.incomplete_cards,
            "jobs": len(self.jobs),
            "error": self.error,
            "complete": self.complete,
        }


class LinkedInProvider:
    """Proveedor que encapsula la lógica para extraer trabajos desde LinkedIn.

    Utiliza el endpoint de invitado (guest) público de LinkedIn y técnicas
    de evasión (stealth) para evitar bloqueos por límite de peticiones (Rate Limit).

    Atributos:
        source (str): Nombre del proveedor ("linkedin").
    """
    source = "linkedin"

    def __init__(
        self,
        config: BotConfig,
        logger: logging.Logger,
        playwright: object | None = None,
    ) -> None:
        """Inicializa el proveedor de LinkedIn.

        Argumentos:
            config (BotConfig): Objeto de configuración del bot.
            logger (logging.Logger): Logger para registrar información y errores.
            playwright (object | None, opcional): Referencia a Playwright.
                Mantenido por compatibilidad, aunque este proveedor usa 'requests'.
        """
        self.config = config
        self.logger = logger
        self.playwright = playwright  # Backwards-compatible constructor argument.
        self.last_blocked_reason = ""
        self.rate_limit_429_cycle = 0
        self.rate_limit_429_total = 0
        self._rate_limited_until = 0.0
        self.last_session_state = "not_checked"
        self.session = requests.Session(
            impersonate="chrome120",
            proxies={"http": getattr(config, "proxy_url", None), "https": getattr(config, "proxy_url", None)}
            if getattr(config, "proxy_url", None)
            else None,
        )
        from utils_stealth import get_stealth_headers

        self.session.headers.update(get_stealth_headers())

    def configured_urls(self) -> list[str]:
        """Obtiene y expande las URLs configuradas de LinkedIn.

        Inyecta parámetros necesarios como 'f_E=2%2C3' (filtros de experiencia)
        y expande las URLs en ventanas de tiempo.

        Devuelve:
            list[str]: Lista de URLs de búsqueda de LinkedIn listas para consultar.
        """
        # Recopila todas las URLs definidas en la configuración
        values = [
            *getattr(self.config, "linkedin_urls", ()),
            getattr(self.config, "linkedin_url", ""),
        ]

        import re

        injected = []
        for v in values:
            if not v or not isinstance(v, str):
                continue
            if "f_E=" in v:
                v = re.sub(r"([?&])f_E=[^&#]*", r"\g<1>f_E=2%2C3", v)
            else:
                v = f"{v}{'&' if '?' in v else '?'}f_E=2%2C3"
            injected.append(v)

        return expanded_search_urls(
            injected,
            getattr(self.config, "linkedin_time_windows_seconds", (1200, 3600)),
        )

    def _inter_search_delay_bounds(self) -> tuple[float, float]:
        """Calcula los límites de tiempo de espera entre búsquedas.

        Devuelve:
            tuple[float, float]: Una tupla con (mínimo, máximo) en segundos de retraso.
        """
        lower = max(
            0.0, float(getattr(self.config, "linkedin_inter_search_min_seconds", 3.0))
        )
        upper = max(
            lower, float(getattr(self.config, "linkedin_inter_search_max_seconds", 6.0))
        )
        return lower, upper

    @staticmethod
    def _guest_endpoint(search_url: str) -> str:
        """Transforma una URL de búsqueda normal en la URL del endpoint para invitados.

        Argumentos:
            search_url (str): La URL de búsqueda original.

        Devuelve:
            str: URL apuntando a la API pública de invitados de LinkedIn.
        """
        parts = urlsplit(search_url)
        return urlunsplit(
            (
                "https",
                "www.linkedin.com",
                "/jobs-guest/jobs/api/seeMoreJobPostings/search",
                parts.query,
                "",
            )
        )

    @staticmethod
    def _text(card: BeautifulSoup, selectors: tuple[str, ...], fallback: str) -> str:
        """Extrae el texto de un elemento HTML utilizando una lista de selectores.

        Argumentos:
            card (BeautifulSoup): El nodo HTML desde donde extraer.
            selectors (tuple[str, ...]): Selectores CSS a intentar.
            fallback (str): Valor de retorno si no se encuentra ningún selector.

        Devuelve:
            str: Texto extraído y limpio, o el valor de 'fallback' si falla.
        """
        for selector in selectors:
            node = card.select_one(selector)
            if node:
                text = " ".join(node.get_text(" ", strip=True).split())
                if text:
                    return text
        return fallback

    def _parse_cards(
        self, html: str, search_url: str = ""
    ) -> tuple[list[JobItem], int, int, int]:
        """Analiza el HTML de respuesta para extraer las tarjetas de empleo.

        Argumentos:
            html (str): Contenido HTML devuelto por LinkedIn.
            search_url (str, opcional): La URL de búsqueda usada, para referenciar.

        Devuelve:
            tuple[list[JobItem], int, int, int]: Una tupla conteniendo:
                - Lista de trabajos analizados sin duplicados.
                - Total de tarjetas HTML detectadas.
                - Total de tarjetas analizadas con éxito.
                - Total de tarjetas ignoradas por falta de información.
        """
        # Analiza el documento HTML buscando los contenedores de los empleos
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select("div.base-card, li.base-card, .job-search-card")
        if not cards:
            cards = [
                node
                for node in soup.select("li, div")
                if node.select_one("a[href*='/jobs/view/']")
            ]

        parsed: list[JobItem] = []
        incomplete = 0
        for card in cards:
            link = card.select_one("a.base-card__full-link[href]") or card.select_one(
                "a[href*='/jobs/view/']"
            )
            url = canonical_job_url(str(link.get("href", ""))) if link else ""
            title = self._text(
                card,
                ("h3.base-search-card__title", "h3", ".job-search-card__title"),
                "",
            )
            if not url or not title:
                incomplete += 1
                continue
            company = self._text(
                card,
                ("h4.base-search-card__subtitle", "h4", ".base-search-card__subtitle"),
                "Empresa no indicada",
            )
            location = self._text(
                card,
                (".job-search-card__location", ".base-search-card__metadata"),
                "Ubicación no indicada",
            )
            time_node = card.select_one("time")
            published_at = str(time_node.get("datetime", "")) if time_node else ""
            posted_text = time_node.get_text(" ", strip=True) if time_node else ""
            fresh = any(
                token in posted_text.lower()
                for token in ("min", "minute", "hora", "hour", "just now")
            )
            evidence = {
                "search_url": exact_search_url(search_url),
                "posted_text": posted_text,
                "published_at": published_at,
            }
            parsed.append(
                normalise_job(
                    JobItem(
                        id=str(card.get("data-entity-urn", "")),
                        title=title,
                        company=company,
                        location=location,
                        url=url,
                        source=self.source,
                        posted_within_1h=fresh,
                        published_at=published_at,
                        features={
                            "linkedin_search_urls": [exact_search_url(search_url)],
                            "linkedin_recency_evidence": [evidence],
                            "linkedin_posted_text": posted_text,
                            "linkedin_published_at_raw": published_at,
                        },
                    )
                )
            )

        unique: dict[str, JobItem] = {}
        for job in parsed:
            key = canonical_identity(job)
            unique[key] = (
                merge_linkedin_jobs(unique[key], job) if key in unique else job
            )
        return list(unique.values()), len(cards), len(parsed), incomplete

    async def fetch_url(self, search_url: str) -> LinkedInFetchResult:
        """Realiza la petición HTTP para una URL de búsqueda y extrae sus ofertas.

        Gestiona la paginación de la API de invitados (en fragmentos de 10) hasta
        alcanzar el límite configurado. Maneja códigos de error y límites de tasa.

        Argumentos:
            search_url (str): La URL de búsqueda de LinkedIn a consultar.

        Devuelve:
            LinkedInFetchResult: El resultado detallado de la consulta.
        """
        search_url = exact_search_url(search_url)

        if time.monotonic() < self._rate_limited_until:
            endpoint_url = self._guest_endpoint(search_url)
            return LinkedInFetchResult(
                search_url, endpoint_url, "rate_limited", 429, (), 0, 0, 0, "cooldown"
            )

        requested_cap = min(
            100, max(1, int(getattr(self.config, "linkedin_max_jobs", 10)) or 10)
        )

        all_jobs = []
        raw_total = 0
        parsed_total = 0
        inc_total = 0
        start = 0
        endpoint_url = ""

        while start < requested_cap:
            paginated_url = (
                f"{search_url}&start={start}"
                if "?" in search_url
                else f"{search_url}?start={start}"
            )
            endpoint_url = self._guest_endpoint(paginated_url)

            try:
                response = self.session.get(
                    endpoint_url, timeout=self.config.timeout_seconds
                )
            except Exception as exc:
                self.last_blocked_reason = "request_failed"
                return LinkedInFetchResult(
                    search_url,
                    endpoint_url,
                    "failed",
                    None,
                    tuple(all_jobs),
                    raw_total,
                    parsed_total,
                    inc_total,
                    str(exc),
                )

            if response.status_code == 429:
                self.rate_limit_429_cycle += 1
                self.rate_limit_429_total += 1
                self._rate_limited_until = time.monotonic() + max(
                    60, int(self.config.poll_seconds)
                )
                self.last_blocked_reason = "rate_limit_429"
                state = "rate_limited" if not all_jobs else "partial"
                return LinkedInFetchResult(
                    search_url,
                    endpoint_url,
                    state,
                    429,
                    tuple(all_jobs),
                    raw_total,
                    parsed_total,
                    inc_total,
                    "HTTP 429",
                )

            if response.status_code in {401, 403}:
                self.last_blocked_reason = f"http_{response.status_code}"
                state = "blocked" if not all_jobs else "partial"
                return LinkedInFetchResult(
                    search_url,
                    endpoint_url,
                    state,
                    response.status_code,
                    tuple(all_jobs),
                    raw_total,
                    parsed_total,
                    inc_total,
                    f"HTTP {response.status_code}",
                )

            if response.status_code != 200:
                self.last_blocked_reason = f"http_{response.status_code}"
                state = "failed" if not all_jobs else "partial"
                return LinkedInFetchResult(
                    search_url,
                    endpoint_url,
                    state,
                    response.status_code,
                    tuple(all_jobs),
                    raw_total,
                    parsed_total,
                    inc_total,
                    f"HTTP {response.status_code}",
                )

            lower_html = response.text.lower()
            if any(
                marker in lower_html
                for marker in ("captcha", "security check", "unusual activity")
            ):
                self.last_blocked_reason = "challenge"
                state = "blocked" if not all_jobs else "partial"
                return LinkedInFetchResult(
                    search_url,
                    endpoint_url,
                    state,
                    200,
                    tuple(all_jobs),
                    raw_total,
                    parsed_total,
                    inc_total,
                    "challenge page",
                )

            try:
                jobs, raw_cards, parsed_cards, incomplete_cards = self._parse_cards(
                    response.text, search_url
                )
            except (AttributeError, TypeError, ValueError) as exc:
                self.last_blocked_reason = "parse_error"
                state = "failed" if not all_jobs else "partial"
                return LinkedInFetchResult(
                    search_url,
                    endpoint_url,
                    state,
                    200,
                    tuple(all_jobs),
                    raw_total,
                    parsed_total,
                    inc_total,
                    f"parse error: {exc}",
                )

            if raw_cards == 0:
                break

            all_jobs.extend(jobs)
            raw_total += raw_cards
            parsed_total += parsed_cards
            inc_total += incomplete_cards

            # 10 is the guest api fragment size
            if raw_cards < 10:
                break

            start += 10

            import random

            await asyncio.sleep(random.uniform(1.0, 2.5))

        all_jobs = all_jobs[:requested_cap]

        state = "ok"
        if raw_total == 0:
            state = "empty"
        elif inc_total > 0 or parsed_total == 0:
            state = "partial"

        return LinkedInFetchResult(
            search_url,
            endpoint_url,
            state,
            200,
            tuple(all_jobs),
            raw_total,
            parsed_total,
            inc_total,
        )

    async def fetch_snapshots(self) -> list[LinkedInFetchResult]:
        """Obtiene instantáneas de todas las URLs configuradas iterativamente.

        Controla el tiempo de ejecución mínimo entre ciclos globales para
        evitar penalizaciones (Rate Limit 429) por peticiones excesivas.

        Devuelve:
            list[LinkedInFetchResult]: Lista de los resultados para cada URL de búsqueda.
        """
        now_ts = time.time()
        last_run = getattr(self, "_last_successful_run", 0)

        # Enforce 25-minute interval minimum (runs approx every 30 mins if bot runs every 15m)
        if now_ts - last_run < 1500:
            self.logger.info(
                "LinkedIn | Skipping cycle to enforce 30-minute interval (anti-429)."
            )
            # We return empty results so the bot thinks we found 0 jobs, keeping health OK but doing no requests
            return []

        self._last_successful_run = now_ts
        self.rate_limit_429_cycle = 0
        urls = self.configured_urls()
        if not urls:
            self.logger.warning("LinkedIn has no configured search URL.")
            return []
        results: list[LinkedInFetchResult] = []
        for index, url in enumerate(urls):
            if index:
                delay = random.uniform(*self._inter_search_delay_bounds())
                self.logger.info(
                    "LinkedIn API | waiting %.2fs before next configured search", delay
                )
                await asyncio.sleep(delay)
            result = await self.fetch_url(url)

            results.append(result)
            self.logger.info("LinkedIn API | %s", result.as_dict())
            if result.state == "rate_limited":
                break
        return results

    async def check_session(self) -> tuple[bool, str]:
        """Verifica el estado de la sesión consultando la primera URL disponible.
        
        Reporta el estado real del endpoint público sin generar un éxito falso.

        Devuelve:
            tuple[bool, str]: (Éxito, Mensaje con el estado detallado).
        """
        urls = self.configured_urls()
        if not urls:
            self.last_session_state = "failed"
            return False, "failed:no_configured_url"
        result = await self.fetch_url(urls[0])
        self.last_session_state = result.state
        return (
            result.state == "ok",
            f"{result.state}:http={result.http_status}:cards={len(result.jobs)}",
        )

    async def fetch_jobs(self, startup_deep_scan: bool = False) -> list[JobItem]:
        """Obtiene los trabajos combinados de todas las instantáneas (snapshots).

        Actúa como adaptador de compatibilidad: une todos los resultados de una
        sola página configurada por URL y elimina duplicados lógicos.

        Argumentos:
            startup_deep_scan (bool, opcional): Si es True, indica que es un escaneo
                inicial profundo.

        Devuelve:
            list[JobItem]: Lista unificada de todos los trabajos encontrados sin duplicados.
        """
        if startup_deep_scan:
            self.logger.info(
                "LinkedIn startup scan uses the same configured temporal cascade."
            )
        combined: dict[str, JobItem] = {}
        for snapshot in await self.fetch_snapshots():
            for job in snapshot.jobs:
                key = canonical_identity(job)
                combined[key] = (
                    merge_linkedin_jobs(combined[key], job) if key in combined else job
                )
        return list(combined.values())
