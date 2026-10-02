from __future__ import annotations
import httpx
import asyncio

"""Public, non-authenticated job-board adapters for recruitment consultancies.

The registry deliberately contains *only* public listing URLs.  It does not
attempt to log in, solve challenges, or fetch an offer detail page.  A source
is allowed into the production scheduler only after the separate validation
tool has recorded a successful comparison and a maintainer has enabled it.
"""

import hashlib
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, Tag

from config import BotConfig
from models import JobItem
from utils_stealth import get_stealth_headers

TRACKING_QUERY_KEYS = {"gclid", "fbclid", "mc_cid", "mc_eid", "ref", "source"}
CHALLENGE_MARKERS = (
    "captcha",
    "cf-chl-",
    "cloudflare",
    "access denied",
    "just a moment",
    "unusual traffic",
    "robot check",
)


def normalize_listing_text(value: str) -> str:
    return " ".join((value or "").split())


def canonical_job_url(value: str) -> str:
    """Keep stable job URLs while dropping fragments and tracking parameters."""
    parsed = urlsplit(value)
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS and not key.lower().startswith("utm_")
    ]
    path = re.sub(r"/+", "/", parsed.path or "/")
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), path, urlencode(query), "")
    )


def stable_job_id(
    source: str, url: str, title: str = "", company: str = "", location: str = ""
) -> str:
    """Use the canonical URL when possible, otherwise a deterministic card fingerprint."""
    identity = (
        canonical_job_url(url)
        if url
        else "|".join(
            normalize_listing_text(part).lower() for part in (title, company, location)
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"{source}_{digest}"


def listing_fingerprint(job: JobItem) -> str:
    return "|".join(
        normalize_listing_text(value).lower()
        for value in (job.title, job.company, job.location)
    )


def normalize_publication_datetime(value: str) -> str:
    """Return an ISO UTC timestamp only for a date exposed by a public card."""
    candidate = normalize_listing_text(value)
    if not candidate:
        return ""
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(candidate)
        except (TypeError, ValueError, IndexError):
            return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ConsultancySource:
    """A source-specific adapter contract, kept separate from runtime status."""

    source: str
    label: str
    index_url: str
    company: str
    job_path_patterns: tuple[str, ...]
    card_selectors: tuple[str, ...]
    location_selectors: tuple[str, ...] = ()
    next_selectors: tuple[str, ...] = ("a[rel='next']", ".pagination a.next", "a.next")
    published_at_selectors: tuple[str, ...] = (
        "time[datetime]",
        "[itemprop='datePosted']",
        "[data-published-at]",
        "[data-date-posted]",
    )
    strategy: str = "public_html"
    initial_status: str = "pending_validation"


class _ListingPage(Protocol):
    """Minimum response shape shared by requests and public browser renders."""

    text: str
    url: str


@dataclass(frozen=True)
class _RenderedListingPage:
    text: str
    url: str


# Each entry owns its matching patterns/selectors.  The conservative patterns
# avoid treating navigation links as offers; validation catches site changes.
CONSULTANCY_SOURCES: tuple[ConsultancySource, ...] = (
    ConsultancySource(
        "bo_growth",
        "Bo Growth",
        "https://jobsite.bogrowth.es/jobs",
        "Bo Growth",
        (r"/jobs/[^/?#]+",),
        ("a[href*='/jobs/']",),
        (".location", ".job-location"),
    ),
    ConsultancySource(
        "avansel",
        "Avansel",
        "https://ofertasdeempleo.avanselseleccion.es/jobs",
        "Avansel Seleccion",
        (r"/jobs/[^/?#]+",),
        ("a[href*='/jobs/']",),
        (".location", ".job-location"),
    ),
    ConsultancySource(
        "etalentum",
        "Etalentum",
        "https://www.etalentum.com/es/candidatos/encuentra-trabajo.html",
        "Etalentum",
        (r"/(ofertas?-empleo|ofertas?-trabajo|ofertas?)/[^/?#]+",),
        ("a[href*='oferta']", "a[href*='empleo']"),
        (".location", ".localidad", ".job-location"),
    ),
    ConsultancySource(
        "ayanet",
        "Ayanet",
        "https://empleo.ayanet.es/jobs",
        "Ayanet",
        (r"/jobs/[^/?#]+",),
        ("a[href*='/jobs/']",),
        (".location", ".job-location"),
    ),
    ConsultancySource(
        "grupo_brio",
        "Grupo Brio / Asemwork",
        "https://www.grupobrio.es/ofertas-de-trabajo",
        "Grupo Brio",
        (r"/ofertas?[-/][^?#]+", r"/oferta/[^?#]+"),
        ("a[href*='oferta']",),
        (".location", ".localidad"),
    ),
    ConsultancySource(
        "w_hunt",
        "W Hunt",
        "https://whunt.es/vacantes/",
        "W Hunt",
        (r"/vacantes?/[^?#]+",),
        ("a[href*='vacante']",),
        (".location", ".job-location"),
    ),
    ConsultancySource(
        "habemus",
        "Habemus",
        "https://habemus.net/es/ofertas-de-trabajo",
        "Habemus",
        (r"/oferta/[^?#]+",),
        ("a[href*='oferta']",),
        (".location", ".localidad"),
    ),
    ConsultancySource(
        "grupo_noas",
        "Grupo Noa's",
        "https://www.gruponoas.es/ofertas-de-trabajo/",
        "Grupo Noa's",
        (r"/oferta/[^?#]+",),
        ("a[href*='oferta']",),
        (".location", ".localidad"),
    ),
    ConsultancySource(
        "prosolbia",
        "Prosolbia",
        "https://prosolbia.com/ofertas/",
        "Prosolbia",
        (r"/ofertas?/[^?#]+",),
        ("a[href*='oferta']",),
        (".location", ".localidad"),
    ),
    ConsultancySource(
        "melt_group",
        "Melt Group",
        "https://meltgroup.com/ofertas-de-empleo/",
        "Melt Group",
        (r"/ofertas?-de-empleo/[^?#]+", r"/oferta/[^?#]+"),
        ("a[href*='oferta']",),
        (".location", ".localidad"),
        strategy="public_dynamic",
    ),
    ConsultancySource(
        "personal7",
        "Personal 7",
        "https://personal7.es/ofertas-de-empleo/",
        "Personal 7",
        (r"/ofertas?-de-empleo/[^?#]+", r"/oferta/[^?#]+"),
        ("a[href*='oferta']",),
        (".location", ".localidad"),
    ),
    ConsultancySource(
        "montaner",
        "Montaner",
        "https://montaner.com/candidatos/",
        "Montaner",
        (r"/ofertas?[-/][^?#]+", r"/oferta/[^?#]+"),
        ("a[href*='oferta']",),
        (".location", ".localidad"),
    ),
    ConsultancySource(
        "quality_temporal",
        "Quality Temporal",
        "https://qualitytemporal.com/ofertas-de-trabajo/",
        "Quality Temporal",
        (r"/oferta/[^?#]+",),
        ("a[href*='oferta']",),
        (".location", ".localidad"),
    ),
    ConsultancySource(
        "adecco",
        "Adecco",
        "https://www.adecco.com/es-es/ofertas-trabajo",
        "Adecco",
        (r"/(ofertas?-trabajo|job)/[^?#]+",),
        ("a[href*='oferta']", "a[href*='job']"),
        (".location", ".job-location"),
        strategy="public_dynamic",
    ),
    ConsultancySource(
        "randstad",
        "Randstad",
        "https://www.randstad.es/candidatos/ofertas-empleo/",
        "Randstad",
        (r"/ofertas?-empleo/[^?#]+", r"/job/[^?#]+"),
        ("a[href*='oferta']", "a[href*='/job/']"),
        (".location", ".localidad"),
        strategy="public_dynamic",
    ),
    ConsultancySource(
        "gigroup",
        "Gi Group",
        "https://es.gigroup.com/ofertas-de-trabajo/",
        "Gi Group",
        (r"/ofertas?-de-trabajo/[^?#]+", r"/job/[^?#]+"),
        ("a[href*='oferta']", "a[href*='/job/']"),
        (".location", ".localidad"),
    ),
    ConsultancySource(
        "faster",
        "Faster",
        "https://faster.es/portal-de-empleo/",
        "Faster",
        (r"/ofertas?[-/][^?#]+", r"/oferta/[^?#]+"),
        ("a[href*='oferta']",),
        (".location", ".localidad"),
    ),
    ConsultancySource(
        "iman",
        "IMAN",
        "https://empleo.imancorp.es/",
        "IMAN",
        (r"/ofertas?[-/][^?#]+", r"/oferta/[^?#]+", r"/jobs?/[^?#]+"),
        ("a[href*='oferta']", "a[href*='job']"),
        (".location", ".localidad"),
        strategy="public_dynamic",
    ),
    ConsultancySource(
        "grupo_crit",
        "Grupo Crit",
        "https://empleo.grupo-crit.com/",
        "Grupo Crit",
        (r"/ofertas?[-/][^?#]+", r"/oferta/[^?#]+", r"/jobs?/[^?#]+"),
        ("a[href*='oferta']", "a[href*='job']"),
        (".location", ".localidad"),
        strategy="public_dynamic",
    ),
    ConsultancySource(
        "synergie",
        "Synergie",
        "https://www.synergie.es/busco-trabajo/",
        "Synergie",
        (r"/ofertas?[-/][^?#]+", r"/oferta/[^?#]+"),
        ("a[href*='oferta']",),
        (".location", ".localidad"),
        strategy="public_dynamic",
    ),
    ConsultancySource(
        "nortempo",
        "Nortempo",
        "https://empleo.nortempo.com/search_offers/0/",
        "Nortempo",
        (r"/search_offers/[^?#]+", r"/offer/[^?#]+"),
        ("a[href*='search_offers']", "a[href*='/offer/']"),
        (".location", ".localidad"),
    ),
    ConsultancySource(
        "ananda",
        "Ananda",
        "https://www.ananda.es/ofertas-de-empleo/",
        "Ananda",
        (r"/ofertas?-de-empleo/[^?#]+", r"/oferta/[^?#]+"),
        ("a[href*='oferta']",),
        (".location", ".localidad"),
    ),
    ConsultancySource(
        "hays",
        "Hays",
        "https://www.hays.es/busqueda-empleo",
        "Hays",
        (r"/job-detail/[^?#]+", r"/jobs?/[^?#]+"),
        ("a[href*='job-detail']", "a[href*='/job/']"),
        (".location", ".job-location"),
        strategy="public_dynamic",
    ),
    ConsultancySource(
        "michael_page",
        "Michael Page",
        "https://www.michaelpage.es/jobs",
        "Michael Page",
        (r"/job-detail/[^?#]+", r"/job/[^?#]+"),
        ("a[href*='job-detail']", "a[href*='/job/']"),
        (".location", ".job-location"),
        strategy="public_static",
    ),
    ConsultancySource(
        "talent_search_people",
        "Talent Search People",
        "https://www.talentsearchpeople.com/es/ofertas-de-empleo/",
        "Talent Search People",
        (r"/ofertas?-de-empleo/[^?#]+", r"/oferta/[^?#]+"),
        ("a[href*='oferta']",),
        (".location", ".localidad"),
    ),
    ConsultancySource(
        "marlex",
        "Marlex",
        "https://www.marlex.net/es/candidaturas",
        "Marlex",
        (r"/ofertas?[-/][^?#]+", r"/oferta/[^?#]+", r"/jobs?/[^?#]+"),
        ("a[href*='oferta']", "a[href*='job']"),
        (".location", ".localidad"),
        strategy="public_dynamic",
    ),
    ConsultancySource(
        "manpower",
        "Manpower",
        "https://www.manpower.es/es/candidatos",
        "Manpower",
        (r"/ofertas?[-/][^?#]+", r"/oferta/[^?#]+", r"/jobs?/[^?#]+"),
        ("a[href*='oferta']", "a[href*='job']"),
        (".location", ".localidad"),
        strategy="public_dynamic",
    ),
    ConsultancySource(
        "eurofirms",
        "Eurofirms",
        "https://jobs.eurofirms.com/es/es/",
        "Eurofirms",
        (r"/ofertas?[-/][^?#]+", r"/oferta/[^?#]+", r"/job/[^?#]+"),
        ("a[href*='oferta']", "a[href*='/job/']"),
        (".location", ".localidad"),
        strategy="public_dynamic",
    ),
)
CONSULTANCY_SOURCE_IDS = tuple(source.source for source in CONSULTANCY_SOURCES)
_SOURCES_BY_ID = {source.source: source for source in CONSULTANCY_SOURCES}


def get_consultancy_source(source: str) -> ConsultancySource:
    try:
        return _SOURCES_BY_ID[source]
    except KeyError as exc:
        raise ValueError(f"Unknown consultancy source: {source}") from exc


class PublicConsultancyProvider:
    """Fetch a bounded number of public list pages for one source adapter."""

    def __init__(
        self,
        source: ConsultancySource,
        config: BotConfig,
        logger: logging.Logger,
        playwright: Playwright | None = None,
    ) -> None:
        self.playwright = playwright
        self.definition = source
        self.source = source.source
        self.config = config
        self.logger = logger
        self.last_blocked_reason = ""
        self.rate_limit_429_cycle = 0
        self.last_fetch_pages = 0
        self.last_fetch_count = 0
        self.last_http_status: int | None = None
        self.last_ordering = "portal_order_unverified"
        self.session = requests.Session()
        self.session.headers.update(get_stealth_headers())

    def _is_job_url(self, url: str) -> bool:
        parsed = urlsplit(url)
        index = urlsplit(self.definition.index_url)
        if parsed.netloc and parsed.netloc.lower() != index.netloc.lower():
            return False
        return any(
            re.search(pattern, parsed.path, flags=re.IGNORECASE)
            for pattern in self.definition.job_path_patterns
        )

    def _find_cards(
        self, soup: BeautifulSoup, base_url: str
    ) -> Iterable[tuple[Tag, str]]:
        seen_links: set[str] = set()
        for selector in self.definition.card_selectors:
            for link in soup.select(selector):
                href = str(link.get("href") or "").strip()
                if not href:
                    continue
                url = canonical_job_url(urljoin(base_url, href))
                if url in seen_links or not self._is_job_url(url):
                    continue
                seen_links.add(url)
                # Smart card detection: if the link already contains the title or location, it is the card itself.
                card = link
                if not any(
                    link.select(s) for s in self.definition.location_selectors
                ) and not link.select(
                    "h2, h3, h4, .title, .job-title, .titulo, strong, .regular-dark-blue-18"
                ):
                    card = (
                        link.find_parent("article")
                        or link.find_parent("li")
                        or link.find_parent("div")
                        or link
                    )
                yield card, url

    def _extract_location(self, card: Tag, title: str) -> str:
        for selector in self.definition.location_selectors:
            value = card.select_one(selector)
            if value:
                text = normalize_listing_text(value.get_text(" ", strip=True))
                if text:
                    return text
        card_text = normalize_listing_text(card.get_text(" ", strip=True))
        if title and card_text.startswith(title):
            card_text = card_text[len(title) :].strip(" -|·")
        return card_text[:300] or "Ubicación no especificada"

    def _extract_published_at(self, card: Tag) -> str:
        nodes = [card]
        nodes.extend(
            card.select(selector) for selector in self.definition.published_at_selectors
        )
        for node_or_nodes in nodes:
            candidates = (
                node_or_nodes if isinstance(node_or_nodes, list) else [node_or_nodes]
            )
            for node in candidates:
                for attribute in (
                    "datetime",
                    "content",
                    "data-published-at",
                    "data-date-posted",
                ):
                    value = node.get(attribute)
                    normalized = normalize_publication_datetime(str(value or ""))
                    if normalized:
                        return normalized
        return ""

    def _ordered_jobs(self, found: dict[str, JobItem]) -> list[JobItem]:
        jobs = list(found.values())
        # A partial timestamp set cannot prove that undated cards are older.
        if jobs and all(job.published_at for job in jobs):
            self.last_ordering = "publication_date_desc"
            return sorted(jobs, key=lambda job: job.published_at, reverse=True)
        self.last_ordering = "portal_order_unverified"
        return jobs

    def _parse_page(self, response: _ListingPage) -> tuple[list[JobItem], str | None]:
        soup = BeautifulSoup(response.text, "html.parser")
        jobs: list[JobItem] = []
        seen: set[str] = set()
        for card, url in self._find_cards(soup, response.url):
            link = card.find("a", href=True)
            # The matching link, not an incidental card link, supplies title.
            matching = next(
                (
                    item
                    for item in card.select("a[href]")
                    if self._is_job_url(urljoin(response.url, str(item.get("href"))))
                ),
                link,
            )
            t_node = matching or card

            # Smart title extraction
            title_node = t_node.select_one(
                "h2, h3, h4, .title, .job-title, .titulo, strong, .regular-dark-blue-18"
            )
            if title_node:
                title = normalize_listing_text(title_node.get_text(" ", strip=True))
            else:
                title = normalize_listing_text(t_node.get_text(" ", strip=True))

            if not title or len(title) > 300:
                continue
            location = self._extract_location(card, title)
            published_at = self._extract_published_at(card)
            job = JobItem(
                id=stable_job_id(
                    self.source, url, title, self.definition.company, location
                ),
                title=title,
                company=self.definition.company,
                location=location,
                url=url,
                source=self.source,
                published_at=published_at,
            )
            if job.id not in seen:
                seen.add(job.id)
                jobs.append(job)

        next_url: str | None = None
        for selector in self.definition.next_selectors:
            element = soup.select_one(selector)
            href = str(element.get("href") or "").strip() if element else ""
            if href:
                candidate = canonical_job_url(urljoin(response.url, href))
                if candidate != canonical_job_url(response.url):
                    next_url = candidate
                    break
        return jobs, next_url

    def check_session(self) -> tuple[bool, str]:
        try:
            import requests

            from utils_stealth import get_stealth_headers

            r = requests.get(
                self.definition.index_url, headers=get_stealth_headers(), timeout=15
            )
            if r.status_code == 200:
                return True, "ok"
            return False, f"http_{r.status_code}"
        except Exception as e:
            return False, f"error_{str(e)[:20]}"

    def fetch_jobs(
        self, *, max_pages: int | None = None, max_results: int | None = None
    ) -> list[JobItem]:
        

        now_ts = time.time()
        last_run = getattr(self, "_last_successful_run", 0)
        if now_ts - last_run < 14000:
            self.logger.info(
                "%s | Skipping cycle to enforce 4-hour interval.", self.source
            )
            return []
        self._last_successful_run = now_ts
        self.last_blocked_reason = ""
        self.rate_limit_429_cycle = 0
        self.last_fetch_pages = 0
        self.last_fetch_count = 0
        self.last_ordering = "portal_order_unverified"
        page_limit = max(
            1,
            max_pages
            if max_pages is not None
            else getattr(self.config, "consultancy_max_pages", 2),
        )
        result_limit = max(
            1,
            max_results
            if max_results is not None
            else getattr(self.config, "consultancy_max_results", 50),
        )

        # These portals render the public listing client-side. Use one bounded
        # browser traversal instead of duplicating the same scope via HTTP.
        if self.definition.strategy == "public_dynamic":
            found = self._fetch_dynamic_listing(page_limit, result_limit)
            self.last_fetch_count = len(found)
            jobs = self._ordered_jobs(found)
            self.logger.info(
                "%s public listing complete | pages=%d jobs=%d ordering=%s",
                self.source,
                self.last_fetch_pages,
                self.last_fetch_count,
                self.last_ordering,
            )
            return jobs

        current_url = self.definition.index_url
        visited_pages: set[str] = set()
        found: dict[str, JobItem] = {}
        try:
            while (
                current_url
                and len(visited_pages) < page_limit
                and len(found) < result_limit
            ):
                current_url = canonical_job_url(current_url)
                if current_url in visited_pages:
                    break
                visited_pages.add(current_url)
                response = self.session.get(
                    current_url, timeout=getattr(self.config, "timeout_seconds", 25)
                )
                self.last_http_status = response.status_code
                self.last_fetch_pages += 1
                body_l = response.text[:100_000].lower()
                if response.status_code == 429:
                    self.rate_limit_429_cycle += 1
                if response.status_code in {403, 429} or (
                    any(marker in body_l for marker in CHALLENGE_MARKERS)
                    and not (
                        self.source == "grupo_noas"
                        and "captcha" in body_l
                        and "cloudflare" not in body_l
                    )
                ):
                    self.last_blocked_reason = (
                        f"{self.source}_http_{response.status_code}"
                        if response.status_code != 200
                        else f"{self.source}_challenge"
                    )
                    self.logger.warning(
                        "%s blocked public listing | reason=%s",
                        self.source,
                        self.last_blocked_reason,
                    )
                    break
                if response.status_code != 200:
                    self.last_blocked_reason = (
                        f"{self.source}_http_{response.status_code}"
                    )
                    self.logger.warning(
                        "%s returned HTTP %s", self.source, response.status_code
                    )
                    break
                page_jobs, current_url = self._parse_page(response)
                for job in page_jobs:
                    found.setdefault(job.id, job)
                    if len(found) >= result_limit:
                        break
        except requests.RequestException as exc:
            self.last_blocked_reason = f"{self.source}_request_error"
            self.logger.warning("%s public request failed: %s", self.source, exc)
        except Exception as exc:
            self.last_blocked_reason = f"{self.source}_parse_error"
            self.logger.warning("%s listing parsing failed: %s", self.source, exc)

        self.last_fetch_count = len(found)
        jobs = self._ordered_jobs(found)
        self.logger.info(
            "%s public listing complete | pages=%d jobs=%d ordering=%s",
            self.source,
            self.last_fetch_pages,
            self.last_fetch_count,
            self.last_ordering,
        )
        return jobs

    async def _fetch_dynamic_listing(
        self, page_limit: int, result_limit: int
    ) -> dict[str, JobItem]:
        """Render only a public listing when the documented HTML has no cards."""
        try:
            from playwright.async_api import Error as PlaywrightError
            from playwright.async_api import sync_playwright
        except ImportError:
            self.last_blocked_reason = f"{self.source}_browser_unavailable"
            return {}

        if self.source == "adecco":
            return self._fetch_adecco_dynamic(
                page_limit, result_limit, None, PlaywrightError
            )

        found: dict[str, JobItem] = {}
        current_url = self.definition.index_url
        visited: set[str] = set()
        try:
            from utils_stealth import apply_playwright_stealth

            if True:
                playwright = self.playwright
                if not playwright:
                    return {}
                browser = playwright.chromium.launch(headless=True)
                context, page = apply_playwright_stealth(browser)
                # Virtualised listing cards can disappear between interactions.
                page.set_default_timeout(1_000)
                try:
                    while (
                        current_url
                        and len(visited) < page_limit
                        and len(found) < result_limit
                    ):
                        current_url = canonical_job_url(current_url)
                        if current_url in visited:
                            break
                        visited.add(current_url)
                        response = await page.goto(
                            current_url,
                            wait_until="domcontentloaded",
                            timeout=max(
                                5_000,
                                int(getattr(self.config, "timeout_seconds", 25)) * 1000,
                            ),
                        )
                        self.last_fetch_pages += 1
                        self.last_http_status = response.status if response else None
                        await page.wait_for_timeout(750)
                        body = await page.content()
                        body_l = body[:100_000].lower()
                        if self.last_http_status in {403, 429}:
                            if self.last_http_status == 429:
                                self.rate_limit_429_cycle += 1
                            self.last_blocked_reason = (
                                f"{self.source}_http_{self.last_http_status}"
                            )
                            break
                        if any(
                            marker in body_l for marker in CHALLENGE_MARKERS
                        ) and not (
                            self.source == "grupo_noas"
                            and "captcha" in body_l
                            and "cloudflare" not in body_l
                        ):
                            self.last_blocked_reason = f"{self.source}_challenge"
                            break
                        if self.last_http_status and self.last_http_status >= 400:
                            self.last_blocked_reason = (
                                f"{self.source}_http_{self.last_http_status}"
                            )
                            break
                        page_jobs, current_url = self._parse_page(
                            _RenderedListingPage(body, page.url)
                        )
                        for job in page_jobs:
                            found.setdefault(job.id, job)
                            if len(found) >= result_limit:
                                break
                finally:
                    await context.close()
                    await browser.close()
        except PlaywrightError as exc:
            self.last_blocked_reason = f"{self.source}_browser_error"
            self.logger.warning(
                "%s public browser rendering failed: %s", self.source, exc
            )
        except Exception as exc:
            self.last_blocked_reason = f"{self.source}_parse_error"
            self.logger.warning(
                "%s dynamic listing parsing failed: %s", self.source, exc
            )
        return found

    async def _fetch_adecco_dynamic(
        self,
        page_limit: int,
        result_limit: int,
        sync_playwright: object,
        playwright_error: type[Exception],
    ) -> dict[str, JobItem]:
        """Read Adecco's public cards and activate each accessible card for its URL.

        Adecco renders the ten cards without links; keyboard activation of their
        documented ``role=button`` exposes the public detail URL.  This is normal
        page interaction, not a login or a challenge bypass.
        """
        found: dict[str, JobItem] = {}
        try:
            if True:
                playwright = self.playwright
                if not playwright:
                    return {}  # type: ignore[operator]
                browser = playwright.chromium.launch(headless=True)
                context = await browser.new_context(locale="es-ES")
                page = await context.new_page()
                page.set_default_timeout(1_000)
                try:
                    response = await page.goto(
                        self.definition.index_url,
                        wait_until="domcontentloaded",
                        timeout=max(
                            5_000,
                            int(getattr(self.config, "timeout_seconds", 25)) * 1000,
                        ),
                    )
                    self.last_http_status = response.status if response else None
                    if self.last_http_status in {403, 429}:
                        if self.last_http_status == 429:
                            self.rate_limit_429_cycle += 1
                        self.last_blocked_reason = (
                            f"{self.source}_http_{self.last_http_status}"
                        )
                        return found

                    # This is the ordinary public cookie-consent dialog, not a challenge.
                    for consent_selector in (
                        "#onetrust-accept-btn-handler",
                        "button:has-text('Aceptar todas')",
                        "button:has-text('Aceptar')",
                    ):
                        try:
                            consent = page.locator(consent_selector).first
                            if await consent.count() and await consent.is_visible():
                                await consent.click(no_wait_after=True, timeout=1_000)
                                break
                        except playwright_error:
                            continue

                    for page_number in range(page_limit):
                        await page.wait_for_timeout(750)
                        body_l = await page.content()[:100_000].lower()
                        if any(
                            marker in body_l for marker in CHALLENGE_MARKERS
                        ) and not (
                            self.source == "grupo_noas"
                            and "captcha" in body_l
                            and "cloudflare" not in body_l
                        ):
                            self.last_blocked_reason = f"{self.source}_challenge"
                            break
                        cards = page.locator(
                            "section.scrollbar-box article [role='button']"
                        )
                        card_count = await cards.count()
                        self.last_fetch_pages += 1
                        if not card_count:
                            break
                        for index in range(card_count):
                            card = cards.nth(index)
                            details = await card.evaluate(
                                """element => {
                                    const title = element.querySelector('.card-header p')?.innerText || '';
                                    const values = [...element.querySelectorAll('.card-body p')]
                                        .map(item => item.innerText.trim()).filter(Boolean);
                                    return { title, location: values[2] || values.at(-1) || '' };
                                }"""
                            )
                            title = normalize_listing_text(
                                str(details.get("title", ""))
                            )
                            location = (
                                normalize_listing_text(str(details.get("location", "")))
                                or "Ubicación no especificada"
                            )
                            if not title:
                                continue
                            # The site implements card selection as a keyboard-accessible button.
                            try:
                                await card.focus(timeout=1_000)
                                # The public card updates the detail pane without navigation.
                                await card.press("Enter", no_wait_after=True, timeout=1_000)
                            except playwright_error:
                                continue
                            try:
                                await page.wait_for_timeout(120)
                                detail = page.locator(
                                    "a.static_jobdetailpage_url"
                                ).first
                                href = (
                                    await detail.get_attribute("href", timeout=1_000)
                                    if await detail.count()
                                    else ""
                                )
                            except playwright_error:
                                href = ""
                            url = canonical_job_url(urljoin(page.url, href))
                            if not href or not self._is_job_url(url):
                                continue
                            job = JobItem(
                                id=stable_job_id(
                                    self.source,
                                    url,
                                    title,
                                    self.definition.company,
                                    location,
                                ),
                                title=title,
                                company=self.definition.company,
                                location=location,
                                url=url,
                                source=self.source,
                            )
                            found.setdefault(job.id, job)
                            if len(found) >= result_limit:
                                break
                        if len(found) >= result_limit or page_number + 1 >= page_limit:
                            break
                        first_title = normalize_listing_text(
                            await cards.first.inner_text().split("\n", 1)[0]
                        )
                        next_button = page.locator(
                            "button[aria-label='Navigate next']"
                        ).first
                        if not await next_button.count() or not await next_button.is_enabled():
                            break
                        try:
                            await next_button.click(no_wait_after=True, timeout=1_000)
                        except playwright_error:
                            self.last_blocked_reason = (
                                f"{self.source}_pagination_incomplete"
                            )
                            break
                        try:
                            page.wait_for_function(
                                "previous => { const current = document.querySelector(\"section.scrollbar-box article [role='button']\"); return current && current.innerText.split('\\n')[0].trim() !== previous; }",
                                first_title,
                                timeout=3_000,
                            )
                        except playwright_error:
                            break
                finally:
                    await context.close()
                    await browser.close()
        except playwright_error as exc:
            self.last_blocked_reason = f"{self.source}_browser_error"
            self.logger.warning(
                "%s public browser rendering failed: %s", self.source, exc
            )
        except Exception as exc:
            self.last_blocked_reason = f"{self.source}_parse_error"
            self.logger.warning(
                "%s dynamic listing parsing failed: %s", self.source, exc
            )
        return found


from playwright.async_api import Playwright


def build_consultancy_provider(
    source: str,
    config: BotConfig,
    logger: logging.Logger,
    playwright: Playwright | None = None,
) -> PublicConsultancyProvider:
    return PublicConsultancyProvider(
        get_consultancy_source(source), config, logger, playwright
    )
