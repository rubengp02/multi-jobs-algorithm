"""Compact, privacy-preserving evidence for the final outcome of each job item."""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from models import JobItem
from operational_retention import jsonl_file_lock

JOB_AUDIT_DIRECTORY = "job_audit"
SCHEMA_VERSION = "job-audit-v1"
TERMINAL_OUTCOMES = frozenset(
    {
        "sent",
        "seen",
        "discarded_location",
        "discarded_include",
        "discarded_exclude",
        "discarded_time_window",
        "unverified_time_window",
        "alerts_disabled",
        "paused",
        "notification_limit",
        "delivery_failed",
    }
)


def _is_terminal_outcome(outcome: object) -> bool:
    value = str(outcome or "")
    return value in TERMINAL_OUTCOMES or value.startswith("discarded_relevance:")


def _canonical_url(url: str) -> str:
    """Drop volatile query strings before deriving a compact job key."""
    try:
        parts = urlsplit(url)
        return urlunsplit(
            (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", "")
        )
    except ValueError:
        return url.strip()


def _job_key(job: JobItem) -> str:
    source = (job.source or "unknown").strip().lower()
    value = "\x1f".join((source, str(job.id or ""), _canonical_url(job.url or "")))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


class JobAuditLedger:
    """Append-only daily batches; no titles, URLs or descriptions are retained."""

    def __init__(self, data_dir: Path, logger: logging.Logger) -> None:
        self.data_dir = data_dir
        self.logger = logger

    def record_jobs(
        self,
        jobs: Sequence[JobItem],
        outcomes: Mapping[int, str],
        *,
        origin: str,
        run_id: str | None = None,
    ) -> int:
        if not jobs:
            return 0

        now = datetime.now(timezone.utc)
        groups: dict[str, list[tuple[int, JobItem]]] = defaultdict(list)
        for index, job in enumerate(jobs):
            groups[(job.source or "unknown").strip().lower() or "unknown"].append(
                (index, job)
            )

        path = self.data_dir / JOB_AUDIT_DIRECTORY / f"{now.date().isoformat()}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        records: list[dict[str, object]] = []
        for provider, entries in groups.items():
            items = [
                {"key": _job_key(job), "outcome": outcomes.get(index)}
                for index, job in entries
            ]
            outcome_counts = Counter(
                str(item["outcome"]) for item in items if item["outcome"]
            )
            terminal = sum(1 for item in items if _is_terminal_outcome(item["outcome"]))
            records.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "timestamp": now.isoformat(),
                    "batch_id": uuid4().hex,
                    "provider": provider,
                    "origin": origin,
                    "run_id": run_id or "",
                    "detected": len(items),
                    "terminal": terminal,
                    "unaccounted": len(items) - terminal,
                    "complete": terminal == len(items),
                    "outcomes": dict(sorted(outcome_counts.items())),
                    "jobs": items,
                }
            )

        with jsonl_file_lock(path), path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(
                    json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n"
                )
        self.logger.debug(
            "Job audit ledger | origin=%s batches=%s jobs=%s",
            origin,
            len(records),
            len(jobs),
        )
        return len(records)
