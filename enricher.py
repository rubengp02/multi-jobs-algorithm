from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

from models import JobItem

ENRICHMENT_CACHE: dict[str, str] = {}
LAST_DOMAIN_REQUEST: dict[str, float] = {}
# LinkedIn frequently lists its requirements after the introductory text.  This
# remains bounded for the cache while preserving a normal full description.
MAX_DESCRIPTION_CHARS = 12_000
# Listing cards normally contain only a teaser.  A shorter description is
# refreshed from the public detail page so every provider can expose the same
# requirements to matching, metrics and Telegram.
MIN_COMPLETE_DESCRIPTION_CHARS = 600

_PROVIDER_DESCRIPTION_SELECTORS: dict[str, tuple[str, ...]] = {
    "infojobs.net": (
        "[data-test='job-description']",
        "#job-description",
        ".ij-Description",
        ".job-description",
        "[class*='description']",
    ),
    "tecnoempleo.com": (
        "#detailOferta",
        ".ofertaDetalle",
        ".job-description",
        "[class*='detalle']",
    ),
    "indeed.com": (
        "#jobDescriptionText",
        "#jobDescription",
        "[data-testid='jobsearch-JobComponent-description']",
    ),
    "manfred.tech": (
        "[data-testid='job-description']",
        ".job-description",
        "[class*='description']",
    ),
    "getmanfred.com": (
        "[data-testid='job-description']",
        ".job-description",
        "[class*='description']",
        "article",
    ),
    "remoteok.com": (".description", "[class*='description']", "article"),
    "remotive.com": (".job-description", "[class*='job-description']", "article"),
    "weworkremotely.com": (".listing-container", ".job-description", "article"),
    "greenhouse.io": ("#content", ".content", ".job__description", "article"),
    "lever.co": (".posting-description", ".section-wrapper", ".posting", "article"),
    "experis.es": ("section.details-block.job", "section.details-block"),
    "accessiway.com": (
        ".job-description",
        "[class*='job-description']",
        "article",
        "main",
    ),
    "teamtailor.com": (
        "[data-testid='job-description']",
        ".job-description",
        "[class*='job-description']",
        "article",
    ),
}

# These conventions appear across the public ATS pages used by the remaining
# providers. They are deliberately tried only after a portal-specific block,
# so navigation and listing chrome never wins over a known offer description.
_COMMON_DESCRIPTION_SELECTORS: tuple[str, ...] = (
    "[itemprop='description']",
    "[data-testid='job-description']",
    "[data-test='job-description']",
    "[data-qa='job-description']",
    ".job-description",
    ".jobDescription",
    ".offer-description",
    ".vacancy-description",
    ".posting-description",
    "[class*='job-description']",
    "[class*='offer-description']",
)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
]


def _normalized_text(element: object) -> str:
    """Return compact visible text from a BeautifulSoup element."""
    return " ".join(element.get_text(" ", strip=True).split())


def _matching_selectors(hostname: str) -> tuple[str, ...]:
    hostname = hostname.lower().split(":", 1)[0]
    for domain, selectors in _PROVIDER_DESCRIPTION_SELECTORS.items():
        if hostname == domain or hostname.endswith(f".{domain}"):
            return selectors
    return ()


def _extract_selector_text(soup: BeautifulSoup, selectors: Iterable[str]) -> str:
    """Return the longest specific content block, not the first page fragment."""
    candidates: list[str] = []
    seen: set[int] = set()
    for selector in selectors:
        for element in soup.select(selector):
            marker = id(element)
            if marker in seen:
                continue
            seen.add(marker)
            text = _normalized_text(element)
            if len(text) >= 50:
                candidates.append(text)
    return max(candidates, key=len, default="")


def _iter_json_ld(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _iter_json_ld(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_json_ld(item)


def _extract_json_ld_jobposting(soup: BeautifulSoup) -> dict | None:
    """Extract the full JobPosting JSON-LD object."""
    for script in soup.select("script[type='application/ld+json']"):
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        for item in _iter_json_ld(payload):
            item_type = item.get("@type", "")
            types = item_type if isinstance(item_type, list) else [item_type]
            if any(str(entry).lower() == "jobposting" for entry in types):
                return item
    return None


def _extract_json_ld_job_description(soup: BeautifulSoup) -> str:
    item = _extract_json_ld_jobposting(soup)
    if not item:
        return ""
    description = item.get("description")
    if not isinstance(description, str):
        return ""
    text = _normalized_text(BeautifulSoup(description, "html.parser"))
    return text if len(text) >= 50 else ""


def _extract_linkedin_description(soup: BeautifulSoup) -> str:
    """Extract only LinkedIn's offer-description block, never page chrome.

    The public LinkedIn page contains sign-in and AI-assistant UI inside its
    ``main`` element.  Falling back to that broad element makes those labels
    look like requirements, so a missing description is preferable to a
    fabricated stack.
    """
    selectors = (
        ".show-more-less-html__markup",
        ".description__text",
        "[data-test-id='job-details'] .description",
        "[data-test-id='job-details'] [class*='description']",
        "section.description",
        "div.job-description",
    )
    seen: set[int] = set()
    for selector in selectors:
        for element in soup.select(selector):
            marker = id(element)
            if marker in seen:
                continue
            seen.add(marker)
            text = _normalized_text(element)
            if len(text) > 50:
                return text
    return ""


def _extract_experis_description(soup: BeautifulSoup) -> str:
    """Return Experis' offer body without the listing/navigation chrome."""
    for selector in ("section.details-block.job", "section.details-block"):
        for element in soup.select(selector):
            text = _normalized_text(element)
            if len(text) > 50:
                return text
    return ""


def _extract_page_text(
    soup: BeautifulSoup,
    is_linkedin: bool,
    is_experis: bool = False,
    hostname: str = "",
) -> str:
    """Get the meaningful page body, using provider-specific strictness."""
    if is_linkedin:
        return _extract_linkedin_description(soup)
    if is_experis:
        return _extract_experis_description(soup)

    provider_text = _extract_selector_text(soup, _matching_selectors(hostname))
    if provider_text:
        return provider_text

    common_text = _extract_selector_text(soup, _COMMON_DESCRIPTION_SELECTORS)
    if common_text:
        return common_text

    content_el = (
        soup.find("article")
        or soup.find("main")
        or soup.find(
            "div",
            class_=re.compile(
                r"description|job-details|offer-body|details|job-description|vacancy-details",
                re.IGNORECASE,
            ),
        )
        or soup.find(
            "section", class_=re.compile(r"description|body|content", re.IGNORECASE)
        )
        or soup.body
    )
    return _normalized_text(content_el) if content_el else _normalized_text(soup)


# A dictionary of locks per domain
DOMAIN_LOCKS: dict[str, asyncio.Lock] = {}


async def _get_domain_lock(domain: str) -> asyncio.Lock:
    if domain not in DOMAIN_LOCKS:
        DOMAIN_LOCKS[domain] = asyncio.Lock()
    return DOMAIN_LOCKS[domain]


async def enrich_job_description(
    job: JobItem, logger: logging.Logger | None = None, timeout: float = 3.5
) -> str:
    """
    Asynchronously/synchronously fetches and parses the full job description from the offer's URL.
    Includes in-memory LRU caching, domain throttling, realistic browser headers, and HTML tag sanitization.
    """
    # Detail pages are required for comparable feature extraction across sources.
    existing_desc = (getattr(job, "description", "") or "").strip()
    if len(existing_desc) >= MIN_COMPLETE_DESCRIPTION_CHARS:
        return existing_desc

    if not job.url or not job.url.startswith("http"):
        return existing_desc

    # 2. Check in-memory LRU cache
    if job.url in ENRICHMENT_CACHE:
        cached = ENRICHMENT_CACHE[job.url]
        job.description = cached
        return cached

    # 3. Domain rate limit safety (prevent rapid fire on same domain)
    try:
        domain = urlparse(job.url).netloc
        lock = await _get_domain_lock(domain)
        async with lock:
            now = time.time()
            last_req = LAST_DOMAIN_REQUEST.get(domain, 0.0)
            if now - last_req < 0.35:
                await asyncio.sleep(0.35 - (now - last_req))
            LAST_DOMAIN_REQUEST[domain] = time.time()
    except Exception:
        pass

    # 4. Fetch full page HTML defensively with realistic headers
    try:
        ua = USER_AGENTS[len(job.url) % len(USER_AGENTS)]
        headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }

        # Don't follow infinite redirects
        async with aiohttp.ClientSession() as session:
            async with session.get(
                job.url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
                allow_redirects=True,
            ) as r:
                if r.status == 200:
                    html_text = await r.text()
                    soup = BeautifulSoup(html_text, "html.parser")
            json_ld_text = _extract_json_ld_job_description(soup)

            # Parse Location/Modality from JSON-LD if missing
            jobposting = _extract_json_ld_jobposting(soup)
            if jobposting:
                # Always extract company from JSON-LD to fix extension scraping bugs (e.g. "Adelántate a solicitar el empleo")
                org = jobposting.get("hiringOrganization", {})
                if isinstance(org, dict):
                    org_name = org.get("name")
                    if org_name and isinstance(org_name, str):
                        job.company = org_name

                # Always extract location from JSON-LD to fix missing or garbled locations
                loc = jobposting.get("jobLocation", {})
                if isinstance(loc, dict):
                    addr = loc.get("address", {})
                    if isinstance(addr, dict):
                        parts = [addr.get("addressLocality"), addr.get("addressRegion")]
                        valid = [p for p in parts if p and str(p).strip()]
                        if valid:
                            job.location = ", ".join(valid)
                        # We removed loc.get("name") fallback because it often contains the job title!

            # Always override company from HTML to ensure accuracy
            html_comp = soup.select_one(".topcard__flavor")
            if html_comp:
                comp_text = html_comp.get_text(strip=True)
                if comp_text:
                    job.company = comp_text

            # Fallback to HTML if JSON-LD didn't provide a clean location
            html_loc = soup.select_one(".topcard__flavor--bullet")
            if html_loc:
                loc_text = html_loc.get_text(strip=True)
                if loc_text:
                    job.location = loc_text

            # Remove clutter tags
            for tag in soup(
                [
                    "script",
                    "style",
                    "nav",
                    "header",
                    "footer",
                    "svg",
                    "noscript",
                    "iframe",
                ]
            ):
                tag.decompose()

            is_linkedin = urlparse(job.url).netloc.lower().endswith("linkedin.com")
            is_experis = urlparse(job.url).netloc.lower().endswith("experis.es")
            hostname = urlparse(job.url).netloc.lower()
            page_text = _extract_page_text(soup, is_linkedin, is_experis, hostname)
            # LinkedIn requires its strict DOM block. Other public portals can
            # expose a cleaner, structured JobPosting payload than their UI.
            full_text = (
                page_text
                if is_linkedin or len(page_text) >= len(json_ld_text)
                else json_ld_text
            )

            # Keep enough of the actual description to retain late requirements.
            cleaned_text = (
                full_text[:MAX_DESCRIPTION_CHARS]
                if len(full_text) > MAX_DESCRIPTION_CHARS
                else full_text
            )

            if len(cleaned_text) > 50:
                # Maintain cache size limit
                if len(ENRICHMENT_CACHE) > 500:
                    ENRICHMENT_CACHE.pop(next(iter(ENRICHMENT_CACHE)))
                ENRICHMENT_CACHE[job.url] = cleaned_text
                job.description = cleaned_text
                return cleaned_text
    except Exception as exc:
        if logger:
            logger.debug(
                "Deep enrichment skipped for %s (%s): %s", job.id, job.url[:60], exc
            )

    return existing_desc
