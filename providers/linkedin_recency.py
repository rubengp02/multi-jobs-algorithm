from __future__ import annotations
import asyncio

"""Strict, explainable validation of LinkedIn's configured time window."""


import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlsplit

from models import JobItem
from providers.linkedin_common import linkedin_recency_evidence, linkedin_search_urls

_RELATIVE_AGE = re.compile(
    r"(?:hace\s*)?(\d+)\s*(min(?:uto)?s?|minutes?|m|horas?|hours?|h|d[ií]as?|days?|semanas?|weeks?)\b",
    re.IGNORECASE,
)
_WINDOW = re.compile(r"^r(\d+)$", re.IGNORECASE)


@dataclass(frozen=True)
class LinkedInRecencyDecision:
    state: str
    reason: str
    age_seconds: int | None = None
    allowed_seconds: int | None = None
    source_urls: tuple[str, ...] = ()
    raw_values: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "reason": self.reason,
            "age_seconds": self.age_seconds,
            "allowed_seconds": self.allowed_seconds,
            "source_urls": list(self.source_urls),
            "raw_values": list(self.raw_values),
        }


def _window_seconds(search_url: str) -> int | None:
    for key, value in parse_qsl(urlsplit(search_url).query, keep_blank_values=True):
        if key.lower() != "f_tpr":
            continue
        match = _WINDOW.match(value.strip())
        if match and int(match.group(1)) > 0:
            return int(match.group(1))
    return None


def _relative_age_seconds(value: str) -> int | None:
    normalized = " ".join(value.lower().split())
    if normalized in {"ahora", "just now", "moments ago"}:
        return 0
    match = _RELATIVE_AGE.search(normalized)
    if not match:
        return None
    quantity = int(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith(("m", "min")):
        return quantity * 60
    if unit.startswith(("h", "hora", "hour")):
        return quantity * 3600
    if unit.startswith(("d", "día", "dia", "day")):
        return quantity * 86400
    return quantity * 7 * 86400


def _published_age_seconds(value: str, now: datetime) -> int | None:
    raw = value.strip()
    # LinkedIn frequently exposes a date-only ``datetime`` attribute alongside
    # a precise visible label (for example, "Hace 12 minutos").  A calendar
    # date does not prove an hour of publication, so treating it as midnight
    # would turn a fresh card into a false stale result.
    if not raw or not re.search(r"[Tt ]\d{1,2}:\d{2}", raw):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0, int((now - parsed.astimezone(timezone.utc)).total_seconds()))


def evaluate_linkedin_recency(
    job: JobItem, *, now: datetime | None = None
) -> LinkedInRecencyDecision:
    """Accept a card only when its shown age proves it fits its narrowest URL."""
    if job.source.strip().lower() != "linkedin":
        return LinkedInRecencyDecision("not_applicable", "not_linkedin")

    source_urls = linkedin_search_urls(job)
    windows = [
        seconds for url in source_urls if (seconds := _window_seconds(url)) is not None
    ]
    if not source_urls or not windows:
        return LinkedInRecencyDecision(
            "unverified", "missing_f_tpr_source", source_urls=source_urls
        )

    checked_at = now or datetime.now(timezone.utc)
    ages: list[int] = []
    raw_values: list[str] = []
    for evidence in linkedin_recency_evidence(job):
        posted_text = evidence["posted_text"]
        published_at = evidence["published_at"]
        for value in (posted_text, published_at):
            if value and value not in raw_values:
                raw_values.append(value)
        relative = _relative_age_seconds(posted_text)
        if relative is not None:
            ages.append(relative)
        published = _published_age_seconds(published_at, checked_at)
        if published is not None:
            ages.append(published)

    allowed = min(windows)
    if not ages:
        return LinkedInRecencyDecision(
            "unverified",
            "card_has_no_parseable_age",
            allowed_seconds=allowed,
            source_urls=source_urls,
            raw_values=tuple(raw_values),
        )
    age = max(ages)
    if age > allowed:
        return LinkedInRecencyDecision(
            "outside_window",
            "card_age_exceeds_narrowest_f_tpr",
            age_seconds=age,
            allowed_seconds=allowed,
            source_urls=source_urls,
            raw_values=tuple(raw_values),
        )
    return LinkedInRecencyDecision(
        "accepted",
        "card_age_within_narrowest_f_tpr",
        age_seconds=age,
        allowed_seconds=allowed,
        source_urls=source_urls,
        raw_values=tuple(raw_values),
    )
