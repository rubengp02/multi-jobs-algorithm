from __future__ import annotations
import asyncio

"""Stable LinkedIn identities shared by its public and extension channels."""


import hashlib
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from models import JobItem


def exact_search_url(value: str) -> str:
    """Keep configured query parameters byte-for-byte, removing only a fragment."""
    parts = urlsplit(value.strip())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def search_url_with_time_window(value: str, seconds: int) -> str:
    """Set only ``f_TPR`` while retaining every other configured parameter."""
    if seconds <= 0:
        raise ValueError("LinkedIn time window must be positive")

    search_url = exact_search_url(value)
    replacement = f"f_TPR=r{seconds}"
    if re.search(r"([?&])f_TPR=[^&#]*", search_url):
        return re.sub(
            r"([?&])f_TPR=[^&#]*",
            lambda match: f"{match.group(1)}{replacement}",
            search_url,
            count=1,
        )
    return f"{search_url}{'&' if '?' in search_url else '?'}{replacement}"


def expanded_search_urls(values: Iterable[str], windows: Iterable[int]) -> list[str]:
    """Expand each base URL in order for each recent-time window."""
    normalized_windows: list[int] = []
    for candidate in windows:
        try:
            seconds = int(candidate)
        except (TypeError, ValueError):
            continue
        if seconds > 0 and seconds not in normalized_windows:
            normalized_windows.append(seconds)

    expanded: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        for seconds in normalized_windows:
            search_url = search_url_with_time_window(value, seconds)
            if search_url not in expanded:
                expanded.append(search_url)
    return expanded


def canonical_job_url(value: str) -> str:
    parts = urlsplit(value.strip())
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def linkedin_job_id(value: str, url: str = "") -> str:
    for candidate in (value, url):
        match = re.search(
            r"(?:jobPosting:|/jobs/view/(?:[^/?#]*-)?)(\d{6,})", candidate or ""
        )
        if match:
            return match.group(1)
    return ""


def legacy_url_id(url: str) -> str:
    canonical = canonical_job_url(url)
    return (
        hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24] if canonical else ""
    )


def canonical_identity(job: JobItem) -> str:
    job_id = linkedin_job_id(job.id, job.url)
    if job_id:
        return f"id:{job_id}"
    return f"url:{canonical_job_url(job.url)}"


def normalise_job(item: JobItem) -> JobItem:
    canonical_url = canonical_job_url(item.url)
    numeric_id = linkedin_job_id(item.id, canonical_url)
    canonical_id = numeric_id or legacy_url_id(canonical_url) or item.id
    aliases = tuple(
        dict.fromkeys(
            alias
            for alias in (*item.aliases, item.id, legacy_url_id(canonical_url))
            if alias and alias != canonical_id
        )
    )
    return JobItem(
        id=canonical_id,
        title=item.title.strip() or "Oferta",
        company=item.company.strip() or "Empresa no indicada",
        location=item.location.strip() or "Ubicación no indicada",
        url=canonical_url,
        source="linkedin",
        posted_within_1h=item.posted_within_1h,
        description=item.description,
        published_at=item.published_at,
        aliases=aliases,
        features=dict(item.features),
    )


def linkedin_search_urls(job: JobItem) -> tuple[str, ...]:
    """Return every configured search that produced a LinkedIn card."""
    features = job.features if isinstance(job.features, dict) else {}
    candidates: list[object] = []
    raw_urls = features.get("linkedin_search_urls")
    if isinstance(raw_urls, (list, tuple, set)):
        candidates.extend(raw_urls)
    elif isinstance(raw_urls, str):
        candidates.append(raw_urls)
    raw_evidence = features.get("linkedin_recency_evidence")
    if isinstance(raw_evidence, dict):
        raw_evidence = [raw_evidence]
    if isinstance(raw_evidence, list):
        candidates.extend(
            value.get("search_url") for value in raw_evidence if isinstance(value, dict)
        )
    extension_card = features.get("extension_card")
    if isinstance(extension_card, dict):
        candidates.append(extension_card.get("searchUrl"))

    urls: list[str] = []
    for value in candidates:
        if not isinstance(value, str) or not value.strip():
            continue
        search_url = exact_search_url(value)
        if search_url not in urls:
            urls.append(search_url)
    return tuple(urls)


def linkedin_recency_evidence(job: JobItem) -> tuple[dict[str, str], ...]:
    """Return de-duplicated raw age evidence without inventing timestamps."""
    features = job.features if isinstance(job.features, dict) else {}
    raw_evidence: object = features.get("linkedin_recency_evidence")
    if isinstance(raw_evidence, dict):
        raw_evidence = [raw_evidence]

    evidence: list[dict[str, str]] = []
    if isinstance(raw_evidence, list):
        for raw in raw_evidence:
            if not isinstance(raw, dict):
                continue
            search_url = raw.get("search_url") or raw.get("searchUrl")
            if not isinstance(search_url, str) or not search_url.strip():
                continue
            evidence.append(
                {
                    "search_url": exact_search_url(search_url),
                    "posted_text": str(
                        raw.get("posted_text") or raw.get("posted") or ""
                    ).strip(),
                    "published_at": str(
                        raw.get("published_at") or raw.get("publishedAt") or ""
                    ).strip(),
                }
            )

    if not evidence:
        posted_text = str(features.get("linkedin_posted_text") or "").strip()
        published_at = str(
            features.get("linkedin_published_at_raw") or job.published_at or ""
        ).strip()
        evidence.extend(
            {
                "search_url": search_url,
                "posted_text": posted_text,
                "published_at": published_at,
            }
            for search_url in linkedin_search_urls(job)
        )

    unique: list[dict[str, str]] = []
    for value in evidence:
        if value not in unique:
            unique.append(value)
    return tuple(unique)


def merge_linkedin_jobs(existing: JobItem, incoming: JobItem) -> JobItem:
    """Merge duplicate cards while retaining evidence from every time window."""
    left = normalise_job(existing)
    right = normalise_job(incoming)
    features: dict[str, Any] = dict(left.features)
    features.update(right.features)

    search_urls = list(linkedin_search_urls(left))
    for search_url in linkedin_search_urls(right):
        if search_url not in search_urls:
            search_urls.append(search_url)
    evidence = list(linkedin_recency_evidence(left))
    for value in linkedin_recency_evidence(right):
        if value not in evidence:
            evidence.append(value)
    if search_urls:
        features["linkedin_search_urls"] = search_urls
    if evidence:
        features["linkedin_recency_evidence"] = evidence
        features["linkedin_posted_text"] = evidence[0]["posted_text"]
        features["linkedin_published_at_raw"] = evidence[0]["published_at"]

    return normalise_job(
        JobItem(
            id=left.id,
            title=right.title if right.title != "Oferta" else left.title,
            company=right.company
            if right.company != "Empresa no indicada"
            else left.company,
            location=right.location
            if right.location != "Ubicación no indicada"
            else left.location,
            url=right.url or left.url,
            source="linkedin",
            posted_within_1h=left.posted_within_1h or right.posted_within_1h,
            description=right.description
            if len(right.description) > len(left.description)
            else left.description,
            published_at=right.published_at or left.published_at,
            aliases=tuple(
                dict.fromkeys((*left.aliases, *right.aliases, left.id, right.id))
            ),
            features=features,
        )
    )
