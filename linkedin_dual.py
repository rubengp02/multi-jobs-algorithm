"""Extension-primary LinkedIn acquisition with a deliberately quiet API fallback.

The authenticated browser is the delivery authority. The guest endpoint is
only used after two missed complete browser intervals; comparing it on every
healthy browser run caused a fragmentary guest response to falsely degrade a
complete extension batch.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from extension_bridge import ExtensionBatch, ExtensionSearchBatch
from linkedin_inventory_audit import LinkedInInventoryAuditor
from models import JobItem
from operational_retention import jsonl_file_lock
from providers.linkedin import LinkedInFetchResult, LinkedInProvider
from providers.linkedin_common import (
    canonical_identity,
    exact_search_url,
    linkedin_recency_evidence,
    linkedin_search_urls,
    merge_linkedin_jobs,
    normalise_job,
)

Delivery = Callable[[list[JobItem], bool, bool, int, str], dict[str, int]]


@dataclass(frozen=True)
class Reconciliation:
    jobs: list[JobItem]
    report: dict[str, Any]


class LinkedInDualCoordinator:
    """Deliver one browser inventory, then fall back only when it is unavailable."""

    def __init__(
        self,
        provider: LinkedInProvider,
        data_dir: Path,
        logger: logging.Logger,
        deliver: Delivery,
        audit_eligible: Callable[[JobItem], bool] | None = None,
    ) -> None:
        self.provider = provider
        self.logger = logger
        self.deliver = deliver
        self.report_file = data_dir / "linkedin_runs.jsonl"
        self.report_file.parent.mkdir(parents=True, exist_ok=True)
        self.expected_urls = tuple(
            exact_search_url(url) for url in provider.configured_urls()
        )
        self.inventory_auditor = LinkedInInventoryAuditor(
            data_dir, logger, self.expected_urls, audit_eligible
        )
        self.started_at = datetime.now(timezone.utc)
        self.last_extension_received_at: datetime | None = None
        self.last_extension_complete_at: datetime | None = None
        self.last_api_at: datetime | None = None
        self.last_fallback_at: datetime | None = None
        self.last_report: dict[str, Any] = {}
        self.fallback_active = False
        self._recovery_pending = True

    @staticmethod
    def _items(jobs: Iterable[JobItem]) -> dict[str, JobItem]:
        result: dict[str, JobItem] = {}
        for item in jobs:
            normalised = normalise_job(item)
            key = canonical_identity(normalised)
            existing = result.get(key)
            result[key] = (
                merge_linkedin_jobs(existing, normalised)
                if existing is not None
                else normalised
            )
        return result

    @staticmethod
    def _job_summary(item: JobItem) -> dict[str, object]:
        return {
            "id": item.id,
            "aliases": list(item.aliases),
            "title": item.title,
            "company": item.company,
            "location": item.location,
            "published_at": item.published_at,
            "url": item.url,
            "search_urls": list(linkedin_search_urls(item)),
            "recency_evidence": list(linkedin_recency_evidence(item)),
        }

    def _write_report(self, report: dict[str, Any]) -> None:
        with (
            jsonl_file_lock(self.report_file),
            self.report_file.open("a", encoding="utf-8") as handle,
        ):
            handle.write(json.dumps(report, ensure_ascii=True, sort_keys=True) + "\n")

    @staticmethod
    def _published_within_48h(item: JobItem, now: datetime) -> bool:
        if item.posted_within_1h:
            return True
        value = item.published_at.strip()
        if not value:
            return False
        relative = value.casefold()
        if relative in {"just now", "ahora", "today", "hoy", "yesterday", "ayer"}:
            return True
        match = re.search(
            r"(?:hace\s+)?(\d+)\s*(minutes?|minutos?|mins?|m|hours?|horas?|hrs?|h|days?|d[ií]as?|d)",
            relative,
        )
        if match:
            quantity = int(match.group(1))
            unit = match.group(2)
            if unit.startswith(("m", "min")):
                return quantity <= 48 * 60
            if unit.startswith(("h", "hor")):
                return quantity <= 48
            return quantity <= 2
        try:
            published = datetime.fromisoformat(value.replace("Z", "+00:00"))
            published = (
                published.replace(tzinfo=timezone.utc)
                if published.tzinfo is None
                else published.astimezone(timezone.utc)
            )
        except ValueError:
            return False
        return now - timedelta(hours=48) <= published <= now + timedelta(minutes=5)

    def _recovery_jobs(
        self, jobs: list[JobItem], report: dict[str, Any]
    ) -> list[JobItem]:
        if not self._recovery_pending:
            return jobs
        now = datetime.now(timezone.utc)
        recent = [job for job in jobs if self._published_within_48h(job, now)]
        report["recovery_scope"] = "first_page_visible_last_48h"
        report["recovery_candidates"] = len(recent)
        return recent

    def _extension_by_url(
        self, batch: ExtensionBatch
    ) -> dict[str, ExtensionSearchBatch]:
        return {
            exact_search_url(search.search_url): search
            for search in batch.searches
            if exact_search_url(search.search_url) in self.expected_urls
        }

    def _extension_reconciliation(self, batch: ExtensionBatch) -> Reconciliation:
        now = datetime.now(timezone.utc)
        extension_by_url = self._extension_by_url(batch)
        union: dict[str, JobItem] = {}
        urls: list[dict[str, Any]] = []
        raw_cards = 0
        for url in self.expected_urls:
            search = extension_by_url.get(url)
            items = self._items(search.jobs if search else ())
            raw_cards += len(items)
            for key, item in items.items():
                existing = union.get(key)
                union[key] = (
                    merge_linkedin_jobs(existing, item)
                    if existing is not None
                    else item
                )
            urls.append(
                {
                    "url": url,
                    "extension": {
                        "state": search.state if search else "missing",
                        "complete": search.complete if search else False,
                        "cards": len(items),
                        "diagnostics": search.diagnostics if search else {},
                        "error": search.error if search else "no_batch_for_url",
                        "jobs": [self._job_summary(item) for item in items.values()],
                    },
                    "api": {
                        "state": "not_queried",
                        "error": "extension_batch_received",
                        "job_items": [],
                    },
                }
            )
        extension_complete = bool(self.expected_urls) and all(
            url in extension_by_url and extension_by_url[url].complete
            for url in self.expected_urls
        )
        audit = self.inventory_auditor.audit(batch).report
        report: dict[str, Any] = {
            "timestamp": now.isoformat(timespec="seconds"),
            "run_id": batch.run_id,
            "trigger": "extension",
            "expected_urls": list(self.expected_urls),
            "extension_complete": extension_complete,
            "api_complete": None,
            "fallback_active": self.fallback_active,
            "recovery": self._recovery_pending,
            "urls": urls,
            "unique_jobs": len(union),
            "channel_duplicates": max(0, raw_cards - len(union)),
            "partial": not extension_complete,
            "inventory_audit": audit,
        }
        self.last_extension_received_at = now
        if extension_complete:
            self.last_extension_complete_at = now
        return Reconciliation(list(union.values()), report)

    def _api_reconciliation(
        self, api_results: list[LinkedInFetchResult]
    ) -> Reconciliation:
        now = datetime.now(timezone.utc)
        api_by_url = {
            exact_search_url(result.search_url): result for result in api_results
        }
        union: dict[str, JobItem] = {}
        urls: list[dict[str, Any]] = []
        for url in self.expected_urls:
            result = api_by_url.get(url)
            items = self._items(result.jobs if result else ())
            for key, item in items.items():
                existing = union.get(key)
                union[key] = (
                    merge_linkedin_jobs(existing, item)
                    if existing is not None
                    else item
                )
            urls.append(
                {
                    "url": url,
                    "extension": {
                        "state": "missing",
                        "complete": False,
                        "cards": 0,
                        "diagnostics": {},
                        "error": "fallback_without_extension",
                        "jobs": [],
                    },
                    "api": (
                        {
                            **result.as_dict(),
                            "job_items": [
                                self._job_summary(item) for item in items.values()
                            ],
                        }
                        if result
                        else {
                            "state": "missing",
                            "error": "no_api_result",
                            "job_items": [],
                        }
                    ),
                }
            )
        api_complete = bool(self.expected_urls) and all(
            url in api_by_url and api_by_url[url].complete for url in self.expected_urls
        )
        self.last_api_at = now
        report: dict[str, Any] = {
            "timestamp": now.isoformat(timespec="seconds"),
            "run_id": f"fallback-{now.strftime('%Y%m%d%H%M%S')}",
            "trigger": "api_fallback",
            "expected_urls": list(self.expected_urls),
            "extension_complete": False,
            "api_complete": api_complete,
            "fallback_active": True,
            "recovery": self._recovery_pending,
            "urls": urls,
            "unique_jobs": len(union),
            "channel_duplicates": 0,
            "partial": True,
            "inventory_audit": {
                "valid": False,
                "reason": "extension_unavailable_api_fallback",
            },
        }
        return Reconciliation(list(union.values()), report)

    @staticmethod
    def _comparison_counts(report: dict[str, Any]) -> dict[str, int]:
        audit = report.get("inventory_audit") or {}
        return {
            "matches": int(audit.get("matches", 0)),
            "only_production": int(audit.get("only_bot", 0)),
            "only_reference": int(audit.get("only_reference", 0)),
            "api_rate_limited": sum(
                1
                for entry in report.get("urls", [])
                if (entry.get("api") or {}).get("state") == "rate_limited"
            ),
            "eligible_absences": int(audit.get("eligible_absences", 0)),
        }

    def _deliver(
        self, reconciliation: Reconciliation, send_alerts: bool, first_cycle: bool
    ) -> dict[str, Any]:
        report = reconciliation.report
        jobs = self._recovery_jobs(reconciliation.jobs, report)
        delivery = self.deliver(
            jobs,
            send_alerts,
            first_cycle,
            report["channel_duplicates"],
            str(report["run_id"]),
        )
        report["filters"] = delivery
        return delivery

    def ingest_extension(
        self, batch: ExtensionBatch, send_alerts: bool, first_cycle: bool
    ) -> dict[str, Any]:
        reconciliation = self._extension_reconciliation(batch)
        delivery = self._deliver(reconciliation, send_alerts, first_cycle)
        report = reconciliation.report
        if report["extension_complete"]:
            self._recovery_pending = False
            self.fallback_active = False
        report["recovery"] = self._recovery_pending
        report["fallback_active"] = self.fallback_active
        self.last_report = report
        self._write_report(report)
        audit = report["inventory_audit"]
        self.logger.info(
            "LinkedIn extension run | run_id=%s complete=%s unique=%d reference_valid=%s eligible_absences=%d sent=%d",
            report["run_id"],
            report["extension_complete"],
            report["unique_jobs"],
            audit.get("valid", False),
            audit.get("eligible_absences", 0),
            delivery.get("sent", 0),
        )
        return {
            **delivery,
            **self._comparison_counts(report),
            "partial": report["partial"],
            "run_id": report["run_id"],
            "unique_jobs": report["unique_jobs"],
            "fallback_active": self.fallback_active,
        }

    def fallback_if_due(
        self, send_alerts: bool, first_cycle: bool
    ) -> dict[str, Any] | None:
        """Use API only after two intervals without a complete extension batch."""
        now = datetime.now(timezone.utc)
        interval = max(
            60,
            int(
                getattr(self.provider.config, "linkedin_extension_refresh_seconds", 900)
            ),
        )
        deadline = now - timedelta(seconds=2 * interval)
        if now < self.started_at + timedelta(seconds=2 * interval):
            return None
        if (
            self.last_extension_complete_at is not None
            and self.last_extension_complete_at >= deadline
        ):
            return None
        if (
            self.last_fallback_at is not None
            and now < self.last_fallback_at + timedelta(seconds=interval)
        ):
            return None
        self.fallback_active = True
        self.last_fallback_at = now
        reconciliation = self._api_reconciliation(self.provider.fetch_snapshots())
        delivery = self._deliver(reconciliation, send_alerts, first_cycle)
        report = reconciliation.report
        if report["api_complete"]:
            self._recovery_pending = False
        report["recovery"] = self._recovery_pending
        self.last_report = report
        self._write_report(report)
        self.logger.warning(
            "LinkedIn extension missing for two intervals; API fallback | unique=%d complete=%s sent=%d",
            report["unique_jobs"],
            report["api_complete"],
            delivery.get("sent", 0),
        )
        return {
            **delivery,
            **self._comparison_counts(report),
            "partial": True,
            "fallback_active": True,
            "unique_jobs": report["unique_jobs"],
            "delivery": delivery,
        }

    def status(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)

        def age(value: datetime | None) -> int | None:
            return None if value is None else round((now - value).total_seconds())

        audit = self.last_report.get("inventory_audit") or {}
        return {
            "last_extension_received_age_sec": age(self.last_extension_received_at),
            "last_extension_complete_age_sec": age(self.last_extension_complete_at),
            "last_api_age_sec": age(self.last_api_at),
            "last_fallback_age_sec": age(self.last_fallback_at),
            "fallback_active": self.fallback_active,
            "last_extension_ok": self.last_extension_complete_at is not None,
            "last_api_ok": bool(self.last_report.get("api_complete", False)),
            "last_discrepancies": self._comparison_counts(self.last_report)
            if self.last_report
            else {},
            "last_partial": bool(self.last_report.get("partial", False)),
            "last_inventory_audit": {
                key: audit.get(key)
                for key in (
                    "valid",
                    "reason",
                    "matches",
                    "only_bot",
                    "only_reference",
                    "eligible_absences",
                )
            },
            "last_channel_states": [
                {
                    "url": entry.get("url", ""),
                    "extension": (entry.get("extension") or {}).get("state", "missing"),
                    "api": (entry.get("api") or {}).get("state", "missing"),
                }
                for entry in self.last_report.get("urls", [])
            ],
            "last_run": self.last_report,
        }
