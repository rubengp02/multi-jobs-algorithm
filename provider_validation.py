"""Independent coverage audit for public consultancy job boards.

This module intentionally never receives the notifier or SeenStorage.  It can
therefore be run from the CLI or after a source anomaly without sending alerts
or changing the production deduplication state.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import threading
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from config import BotConfig, load_config
from models import JobItem
from providers.consultancies import (
    CHALLENGE_MARKERS,
    CONSULTANCY_SOURCE_IDS,
    build_consultancy_provider,
    canonical_job_url,
    get_consultancy_source,
    listing_fingerprint,
    normalize_listing_text,
    stable_job_id,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ProviderValidationStore:
    """Small local status store; reports remain immutable per audit run."""

    STATUS_FILE = "status.json"

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / self.STATUS_FILE

    def _read(self) -> dict[str, dict[str, object]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def get(self, source: str) -> dict[str, object]:
        return dict(self._read().get(source, {"status": "pending_validation"}))

    def all(self) -> dict[str, dict[str, object]]:
        return self._read()

    def update(self, source: str, **values: object) -> dict[str, object]:
        records = self._read()
        record = dict(records.get(source, {"status": "pending_validation"}))
        record.update(values)
        records[source] = record
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return record


def provider_is_validated(source: str, directory: str | Path) -> bool:
    return ProviderValidationStore(directory).get(source).get("status") == "validated"


def _source_matches_url(source: str, url: str) -> bool:
    definition = get_consultancy_source(source)
    parsed = urlsplit(url)
    expected_host = urlsplit(definition.index_url).netloc.lower()
    return (not parsed.netloc or parsed.netloc.lower() == expected_host) and any(
        re.search(pattern, parsed.path, flags=re.IGNORECASE)
        for pattern in definition.job_path_patterns
    )


def collect_visible_reference_jobs(
    source: str,
    config: BotConfig,
    logger: logging.Logger,
    *,
    max_pages: int,
    max_results: int,
) -> tuple[list[JobItem], list[str], str | None]:
    """Read DOM cards in an isolated browser context, without saving HTML."""
    definition = get_consultancy_source(source)
    if source == "adecco":
        return _collect_adecco_visible_reference(
            config, logger, max_pages=max_pages, max_results=max_results
        )
    pages: list[str] = []
    jobs: dict[str, JobItem] = {}
    current_url = definition.index_url
    visited: set[str] = set()
    failure: str | None = None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(locale="es-ES")
            page = context.new_page()
            # Keep the isolated audit bounded when virtualised cards are replaced.
            page.set_default_timeout(1_000)
            try:
                while (
                    current_url and len(visited) < max_pages and len(jobs) < max_results
                ):
                    current_url = canonical_job_url(current_url)
                    if current_url in visited:
                        break
                    visited.add(current_url)
                    response = page.goto(
                        current_url,
                        wait_until="domcontentloaded",
                        timeout=max(5_000, config.timeout_seconds * 1000),
                    )
                    pages.append(current_url)
                    status = response.status if response else 0
                    body_l = page.content()[:100_000].lower()
                    if status in {403, 429}:
                        failure = f"reference_http_{status}"
                        break
                    if any(marker in body_l for marker in CHALLENGE_MARKERS):
                        failure = "reference_challenge"
                        break
                    if status >= 400:
                        failure = f"reference_http_{status}"
                        break
                    try:
                        page.wait_for_timeout(750)
                    except PlaywrightError:
                        pass
                    for link in page.locator("a[href]").all():
                        try:
                            href = link.get_attribute("href") or ""
                            url = canonical_job_url(urljoin(page.url, href))
                            if not _source_matches_url(source, url):
                                continue
                            title = normalize_listing_text(
                                link.inner_text(timeout=1_000)
                            )
                            if not title or len(title) > 300:
                                continue
                            card_text = normalize_listing_text(
                                link.evaluate(
                                    "el => (el.closest('article, li, div') || el).innerText"
                                )
                            )
                            location = (
                                card_text[len(title) :].strip(" -|·")
                                if card_text.startswith(title)
                                else card_text
                            )
                            job = JobItem(
                                id=stable_job_id(
                                    source, url, title, definition.company, location
                                ),
                                title=title,
                                company=definition.company,
                                location=location[:300] or "Ubicación no especificada",
                                url=url,
                                source=source,
                            )
                            jobs.setdefault(job.id, job)
                            if len(jobs) >= max_results:
                                break
                        except PlaywrightError:
                            # A dynamic card can disappear while its list is rendering.
                            continue
                    if len(jobs) >= max_results:
                        break
                    next_url = ""
                    for selector in definition.next_selectors:
                        locator = page.locator(selector).first
                        if locator.count():
                            href = locator.get_attribute("href") or ""
                            if href:
                                candidate = canonical_job_url(urljoin(page.url, href))
                                if candidate != current_url:
                                    next_url = candidate
                                    break
                    current_url = next_url or None
            finally:
                context.close()
                browser.close()
    except PlaywrightError as exc:
        failure = f"reference_browser_error:{type(exc).__name__}"
        logger.warning("Reference browser failed for %s: %s", source, exc)

    return list(jobs.values()), pages, failure


def _collect_adecco_visible_reference(
    config: BotConfig,
    logger: logging.Logger,
    *,
    max_pages: int,
    max_results: int,
) -> tuple[list[JobItem], list[str], str | None]:
    """Independently observe Adecco's accessible cards in a fresh browser session."""
    definition = get_consultancy_source("adecco")
    pages: list[str] = []
    jobs: dict[str, JobItem] = {}
    failure: str | None = None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(locale="es-ES")
            page = context.new_page()
            page.set_default_timeout(1_000)
            try:
                response = page.goto(
                    definition.index_url,
                    wait_until="domcontentloaded",
                    timeout=max(5_000, config.timeout_seconds * 1000),
                )
                status = response.status if response else 0
                if status in {403, 429}:
                    return [], [page.url], f"reference_http_{status}"

                # Consent is part of the public UI and can otherwise cover pagination.
                for consent_selector in (
                    "#onetrust-accept-btn-handler",
                    "button:has-text('Aceptar todas')",
                    "button:has-text('Aceptar')",
                ):
                    try:
                        consent = page.locator(consent_selector).first
                        if consent.count() and consent.is_visible():
                            consent.click(no_wait_after=True, timeout=1_000)
                            break
                    except PlaywrightError:
                        continue

                for page_number in range(max_pages):
                    page.wait_for_timeout(750)
                    body_l = page.content()[:100_000].lower()
                    if any(marker in body_l for marker in CHALLENGE_MARKERS):
                        failure = "reference_challenge"
                        break
                    pages.append(page.url)
                    cards = page.locator(
                        "section.scrollbar-box article [role='button']"
                    )
                    card_count = cards.count()
                    if not card_count:
                        break
                    for index in range(card_count):
                        card = cards.nth(index)
                        details = card.evaluate(
                            """element => {
                                const title = element.querySelector('.card-header p')?.innerText || '';
                                const values = [...element.querySelectorAll('.card-body p')]
                                    .map(item => item.innerText.trim()).filter(Boolean);
                                return { title, location: values[2] || values.at(-1) || '' };
                            }"""
                        )
                        title = normalize_listing_text(str(details.get("title", "")))
                        location = (
                            normalize_listing_text(str(details.get("location", "")))
                            or "Ubicación no especificada"
                        )
                        if not title:
                            continue
                        try:
                            card.focus(timeout=1_000)
                            # The public card updates the detail pane without navigation.
                            card.press("Enter", no_wait_after=True, timeout=1_000)
                        except PlaywrightError:
                            continue
                        page.wait_for_timeout(120)
                        detail = page.locator("a.static_jobdetailpage_url").first
                        href = (
                            detail.get_attribute("href", timeout=1_000)
                            if detail.count()
                            else ""
                        )
                        url = canonical_job_url(urljoin(page.url, href))
                        if not href or not _source_matches_url("adecco", url):
                            continue
                        job = JobItem(
                            id=stable_job_id(
                                "adecco", url, title, definition.company, location
                            ),
                            title=title,
                            company=definition.company,
                            location=location,
                            url=url,
                            source="adecco",
                        )
                        jobs.setdefault(job.id, job)
                        if len(jobs) >= max_results:
                            break
                    if len(jobs) >= max_results or page_number + 1 >= max_pages:
                        break
                    first_title = normalize_listing_text(
                        cards.first.inner_text().split("\n", 1)[0]
                    )
                    next_button = page.locator(
                        "button[aria-label='Navigate next']"
                    ).first
                    if not next_button.count() or not next_button.is_enabled():
                        break
                    try:
                        next_button.click(no_wait_after=True, timeout=1_000)
                    except PlaywrightError:
                        failure = "reference_pagination_incomplete"
                        break
                    try:
                        page.wait_for_function(
                            "previous => { const current = document.querySelector(\"section.scrollbar-box article [role='button']\"); return current && current.innerText.split('\\n')[0].trim() !== previous; }",
                            first_title,
                            timeout=3_000,
                        )
                    except PlaywrightError:
                        break
            finally:
                context.close()
                browser.close()
    except PlaywrightError as exc:
        failure = f"reference_browser_error:{type(exc).__name__}"
        logger.warning("Reference browser failed for Adecco: %s", exc)
    return list(jobs.values()), pages, failure


def _match_jobs(
    reference: Iterable[JobItem], extracted: Iterable[JobItem]
) -> tuple[list[JobItem], list[JobItem], int]:
    extracted_list = list(extracted)
    by_url = {canonical_job_url(job.url): job for job in extracted_list if job.url}
    by_fingerprint = {listing_fingerprint(job): job for job in extracted_list}
    matched = 0
    missing: list[JobItem] = []
    for job in reference:
        if (
            canonical_job_url(job.url) in by_url
            or listing_fingerprint(job) in by_fingerprint
        ):
            matched += 1
        else:
            missing.append(job)
    reference_urls = {canonical_job_url(job.url) for job in reference if job.url}
    reference_fingerprints = {listing_fingerprint(job) for job in reference}
    extras = [
        job
        for job in extracted_list
        if canonical_job_url(job.url) not in reference_urls
        and listing_fingerprint(job) not in reference_fingerprints
    ]
    return missing, extras, matched


def _job_to_report(
    job: JobItem, filter_reason: str | None = None
) -> dict[str, str | None]:
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "url": canonical_job_url(job.url),
        "filter_reason": filter_reason,
    }


def audit_provider(
    source: str,
    config: BotConfig,
    logger: logging.Logger,
    *,
    eligible_reason: Callable[[JobItem], str | None],
    max_pages: int | None = None,
    max_results: int | None = None,
    reference_collector: Callable[
        [str, BotConfig, logging.Logger], tuple[list[JobItem], list[str], str | None]
    ]
    | None = None,
) -> dict[str, object]:
    """Compare the normal public extractor against a fresh browser DOM view."""
    definition = get_consultancy_source(source)
    page_limit = max_pages or config.provider_validation_max_pages
    result_limit = max_results or config.provider_validation_max_results
    extractor = build_consultancy_provider(source, config, logger)
    extracted = extractor.fetch_jobs(max_pages=page_limit, max_results=result_limit)
    if reference_collector is None:
        reference, reference_urls, reference_failure = collect_visible_reference_jobs(
            source, config, logger, max_pages=page_limit, max_results=result_limit
        )
    else:
        reference, reference_urls, reference_failure = reference_collector(
            source, config, logger
        )
    missing, extras, matched = _match_jobs(reference, extracted)
    important_missing = [job for job in missing if eligible_reason(job) is None]
    missing_records = [_job_to_report(job, eligible_reason(job)) for job in missing]

    if reference_failure and (
        "http_403" in reference_failure
        or "http_429" in reference_failure
        or "challenge" in reference_failure
    ):
        status, reason = "blocked", reference_failure
    elif extractor.last_blocked_reason:
        status, reason = (
            (
                "blocked"
                if "http_403" in extractor.last_blocked_reason
                or "http_429" in extractor.last_blocked_reason
                or "challenge" in extractor.last_blocked_reason
                else "degraded"
            ),
            extractor.last_blocked_reason,
        )
    elif reference_failure:
        status, reason = "degraded", reference_failure
    elif not reference:
        status, reason = "pending_validation", "reference_empty"
    elif important_missing:
        status, reason = "degraded", "eligible_offers_missing"
    else:
        status, reason = "validated", "coverage_ok"

    report: dict[str, object] = {
        "schema_version": 1,
        "source": source,
        "label": definition.label,
        "checked_at": _now(),
        "status": status,
        "reason": reason,
        "scope": {
            "max_pages": page_limit,
            "max_results": result_limit,
            "actual_reference_pages": len(reference_urls),
            "actual_extractor_pages": extractor.last_fetch_pages,
        },
        "reviewed_urls": reference_urls,
        "extractor": {
            "count": len(extracted),
            "http_status": extractor.last_http_status,
            "blocked_reason": extractor.last_blocked_reason,
            "ordering": getattr(extractor, "last_ordering", "not_reported"),
        },
        "reference": {"visible_count": len(reference), "failure": reference_failure},
        "comparison": {
            "matches": matched,
            "extras": [_job_to_report(job) for job in extras],
            "missing": missing_records,
            "eligible_missing": [_job_to_report(job) for job in important_missing],
        },
    }
    directory = Path(config.provider_validation_dir)
    runs = directory / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    report_path = runs / f"{datetime.now().strftime('%Y%m%dT%H%M%S')}_{source}.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    ProviderValidationStore(directory).update(
        source,
        status=status,
        reason=reason,
        checked_at=report["checked_at"],
        last_correct_at=report["checked_at"]
        if status == "validated"
        else ProviderValidationStore(directory).get(source).get("last_correct_at"),
        extracted_count=len(extracted),
        visible_count=len(reference),
        matches=matched,
        eligible_missing=len(important_missing),
        ordering=str(getattr(extractor, "last_ordering", "not_reported")),
        report=str(report_path),
    )
    logger.info(
        "Provider validation | source=%s status=%s visible=%d extracted=%d matches=%d eligible_missing=%d",
        source,
        status,
        len(reference),
        len(extracted),
        matched,
        len(important_missing),
    )
    return report


def detect_provider_anomaly(
    previous: dict[str, object], *, count: int, blocked_reason: str
) -> str | None:
    """Return a stable, explainable revalidation trigger, if one is needed."""
    if blocked_reason:
        return "blocked_or_http_error"
    previous_count = int(previous.get("last_runtime_count", 0) or 0)
    if previous_count > 0 and count == 0:
        return "zero_after_success"
    if previous_count >= 10 and 0 < count * 3 <= previous_count:
        return "strong_volume_drop"
    return None


_ASYNC_LOCK = threading.Lock()
_ASYNC_RUNNING: set[str] = set()


def record_runtime_observation(
    source: str, config: BotConfig, *, count: int, blocked_reason: str
) -> str | None:
    """Persist compact provider health metrics and return any audit trigger."""
    store = ProviderValidationStore(config.provider_validation_dir)
    previous = store.get(source)
    anomaly = detect_provider_anomaly(
        previous, count=count, blocked_reason=blocked_reason
    )
    store.update(
        source,
        last_runtime_at=_now(),
        last_runtime_count=count,
        last_runtime_blocked_reason=blocked_reason,
        last_anomaly=anomaly,
    )
    return anomaly


def schedule_anomaly_audit(
    source: str,
    config: BotConfig,
    logger: logging.Logger,
    eligible_reason: Callable[[JobItem], str | None],
    reason: str,
) -> bool:
    """Run audit off the scheduler thread; duplicate source audits are coalesced."""
    if not config.provider_validation_auto_on_anomaly:
        return False
    with _ASYNC_LOCK:
        if source in _ASYNC_RUNNING:
            return False
        _ASYNC_RUNNING.add(source)

    def worker() -> None:
        try:
            logger.warning(
                "Scheduling independent provider revalidation | source=%s reason=%s",
                source,
                reason,
            )
            audit_provider(source, config, logger, eligible_reason=eligible_reason)
        except Exception:
            logger.exception("Provider revalidation failed | source=%s", source)
        finally:
            with _ASYNC_LOCK:
                _ASYNC_RUNNING.discard(source)

    threading.Thread(
        target=worker, name=f"provider-audit-{source}", daemon=True
    ).start()
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate public consultancy provider coverage without alerts or seen writes."
    )
    parser.add_argument(
        "--provider", choices=(*CONSULTANCY_SOURCE_IDS, "all"), default="all"
    )
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--max-results", type=int, default=None)
    args = parser.parse_args()
    config = load_config()
    logger = logging.getLogger("provider-validation")
    logging.basicConfig(
        level=config.log_level, format="%(asctime)s | %(levelname)s | %(message)s"
    )
    from main import (
        job_filter_reason,  # Avoid circular import during normal scheduler startup.
    )

    sources = CONSULTANCY_SOURCE_IDS if args.provider == "all" else (args.provider,)
    failed = 0
    for source in sources:
        report = audit_provider(
            source,
            config,
            logger,
            eligible_reason=lambda job: job_filter_reason(job, config),
            max_pages=args.max_pages,
            max_results=args.max_results,
        )
        failed += int(report["status"] != "validated")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
