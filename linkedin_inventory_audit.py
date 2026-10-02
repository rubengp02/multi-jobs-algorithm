"""Independent browser-DOM inventory audit for LinkedIn.

The extension sends two inventories after one completed scroll: the cards used
by production and a reference inventory selected through a separate DOM path.
This module only compares them.  It never calls Telegram or reads/writes seen.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from extension_bridge import ExtensionBatch, ExtensionSearchBatch
from models import JobItem
from operational_retention import jsonl_file_lock
from providers.linkedin_common import (
    canonical_identity,
    exact_search_url,
    linkedin_recency_evidence,
    linkedin_search_urls,
    merge_linkedin_jobs,
    normalise_job,
)
from relevance import RelevanceDecision, evaluate_relevance


@dataclass(frozen=True)
class InventoryAuditResult:
    """Small result returned to the coordinator without exposing raw cards."""

    valid: bool
    coverage_correct: bool
    matches: int
    only_bot: int
    only_reference: int
    eligible_absences: int
    report: dict[str, Any]


class LinkedInInventoryAuditor:
    """Persist a truthful, compact comparison for every extension execution."""

    max_capture_gap_seconds = 120

    def __init__(
        self,
        data_dir: Path,
        logger: logging.Logger,
        expected_urls: Iterable[str],
        is_eligible: Callable[[JobItem], bool] | None = None,
    ) -> None:
        self.logger = logger
        self.expected_urls = tuple(exact_search_url(url) for url in expected_urls)
        self.is_eligible = is_eligible or (
            lambda item: evaluate_relevance(item).status != "rejected"
        )
        self.output_dir = data_dir / "linkedin_inventory_audit"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _summary(
        item: JobItem, decision: RelevanceDecision | None = None
    ) -> dict[str, object]:
        result: dict[str, object] = {
            "id": item.id,
            "title": item.title,
            "company": item.company,
            "location": item.location,
            "published_at": item.published_at,
            "url": item.url,
            "search_urls": list(linkedin_search_urls(item)),
            "recency_evidence": list(linkedin_recency_evidence(item)),
        }
        if decision is not None:
            result["relevance"] = {
                "status": decision.status,
                "score": decision.score,
                "family": decision.family,
                "positive_evidence": list(decision.positive_evidence),
                "negative_evidence": list(decision.negative_evidence),
            }
        return result

    @staticmethod
    def _fallback_key(item: JobItem) -> str:
        # The canonical LinkedIn ID is preferred.  Cards without it remain
        # comparable without treating a mutable URL parameter as identity.
        identity = canonical_identity(item)
        if identity.startswith(("id:", "url:")):
            return identity
        return "fields:" + "|".join(
            value.casefold().strip()
            for value in (item.title, item.company, item.location)
        )

    def _items(self, jobs: Iterable[JobItem]) -> dict[str, JobItem]:
        result: dict[str, JobItem] = {}
        for item in jobs:
            normalised = normalise_job(item)
            key = self._fallback_key(normalised)
            existing = result.get(key)
            result[key] = (
                merge_linkedin_jobs(existing, normalised)
                if existing is not None
                else normalised
            )
        return result

    @staticmethod
    def _captured_at(
        search: ExtensionSearchBatch, key: str, fallback: datetime
    ) -> datetime:
        value = str(
            search.diagnostics.get(key, search.diagnostics.get("capturedAt", ""))
        )
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return fallback

    def _audit_search(
        self, url: str, search: ExtensionSearchBatch | None, now: datetime
    ) -> dict[str, Any]:
        if search is None:
            return {
                "url": url,
                "valid": False,
                "reason": "missing_extension_search",
                "bot_cards": [],
                "reference_cards": [],
                "matches": [],
                "only_bot": [],
                "only_reference": [],
                "eligible_absences": [],
            }
        bot = self._items(search.jobs)
        reference = self._items(search.reference_jobs)
        bot_at = self._captured_at(search, "productionCapturedAt", now)
        reference_at = self._captured_at(search, "referenceCapturedAt", bot_at)
        gap_seconds = abs((bot_at - reference_at).total_seconds())
        challenge = bool(search.diagnostics.get("challengeDetected", False))
        first_page_target_complete = (
            search.diagnostics.get("firstPageTargetComplete", True) is not False
        )
        valid = bool(
            search.complete
            and first_page_target_complete
            and gap_seconds <= self.max_capture_gap_seconds
            and not challenge
        )
        reasons: list[str] = []
        if not search.complete:
            reasons.append("extension_partial_or_non_complete")
        if not first_page_target_complete:
            reasons.append("first_page_target_not_loaded")
        if challenge:
            reasons.append("challenge_detected")
        if gap_seconds > self.max_capture_gap_seconds:
            reasons.append("captures_more_than_120_seconds_apart")
        if bot and not reference:
            reasons.append("reference_inventory_missing")
            valid = False

        shared = sorted(set(bot) & set(reference))
        only_bot = sorted(set(bot) - set(reference))
        only_reference = sorted(set(reference) - set(bot))
        absences: list[dict[str, object]] = []
        for key in only_reference:
            item = reference[key]
            decision = evaluate_relevance(item)
            if decision.status != "rejected" and self.is_eligible(item):
                absences.append(self._summary(item, decision))
        return {
            "url": url,
            "valid": valid,
            "reason": ",".join(reasons) if reasons else "ok",
            "state": search.state,
            "captured_at": bot_at.isoformat(timespec="seconds"),
            "reference_captured_at": reference_at.isoformat(timespec="seconds"),
            "capture_gap_seconds": round(gap_seconds, 2),
            "diagnostics": search.diagnostics,
            "bot_cards": [self._summary(item) for item in bot.values()],
            "reference_cards": [self._summary(item) for item in reference.values()],
            "matches": [self._summary(bot[key]) for key in shared],
            "only_bot": [self._summary(bot[key]) for key in only_bot],
            "only_reference": [
                self._summary(reference[key], evaluate_relevance(reference[key]))
                for key in only_reference
            ],
            "eligible_absences": absences,
        }

    def audit(self, batch: ExtensionBatch) -> InventoryAuditResult:
        now = datetime.now(timezone.utc)
        searches = {
            exact_search_url(search.search_url): search
            for search in batch.searches
            if exact_search_url(search.search_url) in self.expected_urls
        }
        url_reports = [
            self._audit_search(url, searches.get(url), now)
            for url in self.expected_urls
        ]
        valid = bool(url_reports) and all(bool(entry["valid"]) for entry in url_reports)
        matches = sum(len(entry["matches"]) for entry in url_reports)
        only_bot = sum(len(entry["only_bot"]) for entry in url_reports)
        only_reference = sum(len(entry["only_reference"]) for entry in url_reports)
        eligible_absences = sum(
            len(entry["eligible_absences"]) for entry in url_reports
        )
        invalid_reasons = sorted(
            {str(entry["reason"]) for entry in url_reports if not bool(entry["valid"])}
        )
        report: dict[str, Any] = {
            "timestamp": now.isoformat(timespec="seconds"),
            "run_id": batch.run_id,
            "expected_urls": list(self.expected_urls),
            "valid": valid,
            "comparison_valid": valid,
            "coverage_correct": valid and eligible_absences == 0,
            "reason": "ok" if valid else ",".join(invalid_reasons),
            "matches": matches,
            "only_bot": only_bot,
            "only_reference": only_reference,
            "eligible_absences": eligible_absences,
            "urls": url_reports,
        }
        report_file = self.output_dir / f"{now.date().isoformat()}.jsonl"
        with (
            jsonl_file_lock(report_file),
            report_file.open("a", encoding="utf-8") as handle,
        ):
            handle.write(json.dumps(report, ensure_ascii=True, sort_keys=True) + "\n")
        (self.output_dir / "latest.json").write_text(
            json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        if not valid:
            self.logger.warning(
                "LinkedIn inventory audit invalid | run_id=%s", batch.run_id
            )
        elif eligible_absences:
            self.logger.error(
                "LinkedIn inventory audit found %d eligible absences | run_id=%s",
                eligible_absences,
                batch.run_id,
            )
        else:
            self.logger.info(
                "LinkedIn inventory audit coverage correct | run_id=%s", batch.run_id
            )
        return InventoryAuditResult(
            valid=valid,
            coverage_correct=bool(report["coverage_correct"]),
            matches=matches,
            only_bot=only_bot,
            only_reference=only_reference,
            eligible_absences=eligible_absences,
            report=report,
        )
