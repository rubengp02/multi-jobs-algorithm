"""Daily audit of the bot's persisted operational evidence.

This command deliberately does not instantiate providers.  It reports what
the normal scheduler actually recorded, so running it cannot consume a portal
request, change ``seen_jobs.txt``, or send a job alert.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from bisect import bisect_left
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from audit_ledger import JOB_AUDIT_DIRECTORY, TERMINAL_OUTCOMES
from config import BotConfig, load_config
from notifier import TelegramNotifier

SCHEMA_VERSION = "daily-coverage-v1"
RATE_LIMIT_METRICS_FILE = "rate_limit_metrics.jsonl"
LINKEDIN_RUNS_FILE = "linkedin_runs.jsonl"
PROCESS_STAT_FIELDS = (
    "detected",
    "eligible",
    "discarded_location",
    "discarded_include",
    "discarded_exclude",
    "discarded_relevance",
    "relevance_warning",
    "description_unavailable",
    "discarded_description_unavailable",
    "duplicate_channels",
    "seen",
    "paused",
    "notification_limit",
    "alerts_disabled",
    "delivery_failed",
    "saved",
    "sent",
)

# Providers may retain an older source name in their stable job identifiers.
# Reconciliation accepts that name only when comparing the provider's own
# scheduler evidence; changing it at extraction time would invalidate `seen`.
LEDGER_PROVIDER_ALIASES: dict[str, frozenset[str]] = {
    "greenhouse_spain": frozenset({"greenhouse_spain", "greenhouse"}),
}


def _as_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # Older cycle files used the machine's local wall clock.  Interpret
        # them in that same local zone; new records are written in UTC below.
        return parsed.astimezone().astimezone(timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value is not None else None


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _read_jsonl_in_window(
    path: Path, start: datetime, end: datetime
) -> tuple[list[tuple[datetime, dict[str, Any]]], int, int]:
    """Stream one evidence file and retain only records needed by this audit."""
    if not path.exists():
        return [], 0, 0
    selected: list[tuple[datetime, dict[str, Any]]] = []
    malformed = 0
    invalid_timestamp = 0
    try:
        with path.open("r", encoding="utf-8") as file_handle:
            for raw_line in file_handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                if not isinstance(record, dict):
                    malformed += 1
                    continue
                recorded_at = _as_utc(record.get("timestamp"))
                if recorded_at is None:
                    invalid_timestamp += 1
                elif start <= recorded_at <= end:
                    selected.append((recorded_at, record))
    except OSError:
        return [], 1, 0
    selected.sort(key=lambda item: item[0])
    return selected, malformed, invalid_timestamp


def _expected_runs(seconds: int, interval_seconds: int) -> int:
    return max(1, math.floor(seconds / max(1, interval_seconds)))


def _age_minutes(now: datetime, then: datetime | None) -> int | None:
    if then is None:
        return None
    return max(0, round((now - then).total_seconds() / 60))


def _empty_totals() -> dict[str, int]:
    return {field: 0 for field in PROCESS_STAT_FIELDS + ("http_429",)}


def _add_totals(target: dict[str, int], values: dict[str, Any]) -> None:
    for field in target:
        target[field] += _nonnegative_int(values.get(field, 0))


def _provider_summary(
    provider: str,
    all_cycles: list[tuple[datetime, dict[str, Any]]],
    now: datetime,
    config: BotConfig,
) -> dict[str, Any]:
    provider_records: list[tuple[datetime, dict[str, Any]]] = []
    for recorded_at, cycle in all_cycles:
        providers = cycle.get("providers")
        if isinstance(providers, dict) and isinstance(providers.get(provider), dict):
            provider_records.append((recorded_at, providers[provider]))

    totals = _empty_totals()
    blocked_reasons: Counter[str] = Counter()
    validation_statuses: Counter[str] = Counter()
    instrumentation_present = False
    skipped_validation = False
    for _, values in provider_records:
        _add_totals(totals, values)
        instrumentation_present = instrumentation_present or any(
            field in values for field in PROCESS_STAT_FIELDS
        )
        reason = str(values.get("blocked_reason") or "").strip()
        if reason:
            blocked_reasons[reason] += 1
        validation_status = str(values.get("validation_status") or "").strip()
        if validation_status:
            validation_statuses[validation_status] += 1
        anomaly = str(values.get("validation_anomaly") or "")
        skipped_validation = skipped_validation or anomaly.startswith(
            "skipped_not_validated"
        )

    latest_at = provider_records[-1][0] if provider_records else None
    global_cycles = len(all_cycles)
    observed = len(provider_records)
    ratio = (observed / global_cycles) if global_cycles else 0.0
    age = _age_minutes(now, latest_at)
    reasons: list[str] = []
    status = "ok"

    if skipped_validation:
        status = "not_monitored"
        reasons.append("disabled_pending_human_validation")
    elif not global_cycles:
        status = "insufficient_data"
        reasons.append("no_scheduler_cycle_evidence")
    elif not observed:
        status = "critical"
        reasons.append("provider_missing_from_all_recorded_cycles")
    elif not instrumentation_present:
        status = "insufficient_data"
        reasons.append("legacy_cycle_metrics_without_outcome_counts")
    else:
        if age is not None and age > int(config.daily_coverage_max_stale_minutes):
            status = "critical"
            reasons.append("provider_evidence_stale")
        elif ratio < 0.5:
            status = "critical"
            reasons.append("provider_present_in_less_than_half_of_cycles")
        elif ratio < float(config.daily_coverage_min_cycle_ratio):
            status = "warning"
            reasons.append("provider_missing_from_some_cycles")
        if totals["http_429"]:
            status = "warning" if status == "ok" else status
            reasons.append("http_429_observed")
        if blocked_reasons:
            status = "warning" if status == "ok" else status
            reasons.append("provider_block_or_parse_issue_observed")
        if totals["delivery_failed"]:
            status = "warning" if status == "ok" else status
            reasons.append("telegram_delivery_failure_observed")

    return {
        "provider": provider,
        "status": status,
        "reasons": reasons,
        "cycles_observed": observed,
        "cycles_recorded": global_cycles,
        "cycle_ratio": round(ratio, 3),
        "last_evidence_at": _iso(latest_at),
        "last_evidence_age_minutes": age,
        "outcomes": totals,
        "blocked_reasons": dict(blocked_reasons),
        "validation_statuses": dict(validation_statuses),
        "instrumentation_present": instrumentation_present,
    }


def _linkedin_state(value: Any) -> str:
    return str(value or "").strip().lower()


def _linkedin_summary(
    runs: list[tuple[datetime, dict[str, Any]]], now: datetime, config: BotConfig
) -> dict[str, Any]:
    expected = _expected_runs(
        int(config.daily_coverage_lookback_hours) * 3600,
        int(config.linkedin_extension_refresh_seconds),
    )
    complete_extension = 0
    inventory_valid = 0
    coverage_correct = 0
    eligible_absences = 0
    partial = 0
    unique_jobs = 0
    channel_duplicates = 0
    rate_limited = 0
    blocked = 0
    url_count = 0
    pipeline_detected = 0

    for _, run in runs:
        complete_extension += int(bool(run.get("extension_complete")))
        partial += int(bool(run.get("partial")))
        audit = run.get("inventory_audit")
        if isinstance(audit, dict):
            audit_valid = bool(audit.get("valid", audit.get("comparison_valid", False)))
            inventory_valid += int(audit_valid)
            coverage_correct += int(bool(audit.get("coverage_correct")))
            eligible_absences += _nonnegative_int(audit.get("eligible_absences"))
        unique_jobs += _nonnegative_int(run.get("unique_jobs"))
        filters = run.get("filters")
        if isinstance(filters, dict):
            pipeline_detected += _nonnegative_int(filters.get("detected"))
        channel_duplicates += _nonnegative_int(run.get("channel_duplicates"))
        urls = run.get("urls")
        if not isinstance(urls, list):
            continue
        url_count += len(urls)
        for entry in urls:
            if not isinstance(entry, dict):
                continue
            for channel in ("extension", "api"):
                channel_data = entry.get(channel)
                state = _linkedin_state(
                    channel_data.get("state") if isinstance(channel_data, dict) else ""
                )
                if "rate_limit" in state or "429" in state:
                    rate_limited += 1
                if state in {"blocked", "challenge", "failed"}:
                    blocked += 1

    latest_at = runs[-1][0] if runs else None
    age = _age_minutes(now, latest_at)
    ratio = len(runs) / expected
    status = "ok"
    reasons: list[str] = []
    if not runs:
        status = "critical"
        reasons.append("no_linkedin_dual_run_evidence")
    elif age is not None and age > int(config.daily_coverage_max_stale_minutes):
        status = "critical"
        reasons.append("linkedin_evidence_stale")
    elif not complete_extension:
        status = "critical"
        reasons.append("no_complete_extension_batch")
    elif ratio < 0.5:
        status = "critical"
        reasons.append("too_few_linkedin_runs_for_window")
    else:
        if ratio < float(config.daily_coverage_min_cycle_ratio):
            status = "warning"
            reasons.append("linkedin_runs_below_expected_ratio")
        if partial:
            status = "warning" if status == "ok" else status
            reasons.append("partial_linkedin_batches_observed")
        if eligible_absences:
            status = "critical"
            reasons.append("eligible_reference_absence_observed")
        if not inventory_valid:
            status = "warning" if status == "ok" else status
            reasons.append("no_valid_dom_inventory_audit")
        elif not coverage_correct:
            status = "warning" if status == "ok" else status
            reasons.append("dom_inventory_not_coverage_correct")
        if rate_limited:
            status = "warning" if status == "ok" else status
            reasons.append("linkedin_rate_limit_observed")
        if blocked:
            status = "warning" if status == "ok" else status
            reasons.append("linkedin_block_or_challenge_observed")

    return {
        "provider": "linkedin",
        "status": status,
        "reasons": reasons,
        "runs_observed": len(runs),
        "runs_expected": expected,
        "run_ratio": round(ratio, 3),
        "last_evidence_at": _iso(latest_at),
        "last_evidence_age_minutes": age,
        "extension_complete_runs": complete_extension,
        "inventory_valid_runs": inventory_valid,
        "coverage_correct_runs": coverage_correct,
        "eligible_reference_absences": eligible_absences,
        "partial_runs": partial,
        "unique_jobs_reported": unique_jobs,
        "pipeline_detected": pipeline_detected,
        "channel_duplicates": channel_duplicates,
        "url_observations": url_count,
        "rate_limit_observations": rate_limited,
        "blocked_or_challenge_observations": blocked,
        "evidence_scope": "authenticated_extension_dom_inventory, not_external_market_coverage",
    }


def _job_audit_records(
    data_dir: Path, start: datetime, end: datetime
) -> tuple[list[tuple[datetime, dict[str, Any]]], int, int, list[str]]:
    """Read only daily ledgers that can overlap the requested audit window."""
    directory = data_dir / JOB_AUDIT_DIRECTORY
    records: list[tuple[datetime, dict[str, Any]]] = []
    malformed = 0
    invalid_timestamps = 0
    paths: list[str] = []
    if directory.exists():
        for path in sorted(directory.glob("*.jsonl")):
            try:
                file_date = date.fromisoformat(path.stem)
            except ValueError:
                file_date = None
            if file_date is not None and not (start.date() <= file_date <= end.date()):
                continue
            paths.append(str(path))
            loaded, malformed_lines, invalid_lines = _read_jsonl_in_window(
                path, start, end
            )
            records.extend(loaded)
            malformed += malformed_lines
            invalid_timestamps += invalid_lines
    records.sort(key=lambda item: item[0])
    return records, malformed, invalid_timestamps, paths


def _ledger_started_at(
    records: list[tuple[datetime, dict[str, Any]]],
) -> datetime | None:
    """Return the first normal-run ledger entry, excluding manual scans."""
    relevant = [
        recorded_at
        for recorded_at, record in records
        if str(record.get("origin") or "").strip() in {"scheduler", "linkedin_dual"}
    ]
    return min(relevant) if relevant else None


def _partition_scheduler_ledger(
    records: list[tuple[datetime, dict[str, Any]]],
    cycle_records: list[tuple[datetime, dict[str, Any]]],
    *,
    max_completion_delay_seconds: int,
) -> tuple[
    list[tuple[datetime, dict[str, Any]]], list[tuple[datetime, dict[str, Any]]]
]:
    """Associate a provider batch with the cycle metric that closes it.

    The scheduler writes its cycle metric only once every provider has
    finished.  The job ledger is intentionally written as each provider
    finishes.  A batch therefore belongs to the first later metric, rather
    than every metric in a broad time window.  Batches without that closing
    metric are still in progress and must not be reported as lost.
    """
    scheduler_records = [
        item
        for item in records
        if str(item[1].get("origin") or "").strip() == "scheduler"
    ]
    cycle_times = [recorded_at for recorded_at, _ in cycle_records]
    completed: list[tuple[datetime, dict[str, Any]]] = []
    pending: list[tuple[datetime, dict[str, Any]]] = []
    for recorded_at, record in scheduler_records:
        index = bisect_left(cycle_times, recorded_at)
        if index == len(cycle_times):
            pending.append((recorded_at, record))
            continue
        closing_cycle_at = cycle_times[index]
        if (
            closing_cycle_at - recorded_at
        ).total_seconds() > max_completion_delay_seconds:
            pending.append((recorded_at, record))
            continue
        # Keep the evidence immutable on disk while retaining its exact
        # closing metric in this in-memory audit view.
        completed.append(
            (recorded_at, {**record, "_audit_cycle_at": _iso(closing_cycle_at)})
        )
    return completed, pending


def _partition_linkedin_ledger(
    records: list[tuple[datetime, dict[str, Any]]],
    runs: list[tuple[datetime, dict[str, Any]]],
) -> tuple[
    list[tuple[datetime, dict[str, Any]]], list[tuple[datetime, dict[str, Any]]]
]:
    """Match LinkedIn items to a persisted dual-channel run when possible."""
    linkedin_records = [
        item
        for item in records
        if str(item[1].get("origin") or "").strip() == "linkedin_dual"
    ]
    completed_ids = {
        str(run.get("run_id") or "").strip() for _, run in runs if run.get("run_id")
    }
    latest_run_at = runs[-1][0] if runs else None
    completed: list[tuple[datetime, dict[str, Any]]] = []
    pending: list[tuple[datetime, dict[str, Any]]] = []
    for item in linkedin_records:
        recorded_at, record = item
        run_id = str(record.get("run_id") or "").strip()
        # Older ledgers did not persist run_id.  Their timestamp remains a
        # safe compatibility fallback, while new records require run closure.
        is_complete = (
            run_id in completed_ids
            if run_id
            else latest_run_at is not None and recorded_at <= latest_run_at
        )
        (completed if is_complete else pending).append(item)
    return completed, pending


def _provider_detected(
    provider: str, cycles: list[tuple[datetime, dict[str, Any]]]
) -> int:
    """Sum only the provider's detected count for the ledger evidence window."""
    total = 0
    for _, cycle in cycles:
        providers = cycle.get("providers")
        values = providers.get(provider) if isinstance(providers, dict) else None
        if isinstance(values, dict):
            total += _nonnegative_int(values.get("detected"))
    return total


def _matching_provider_batches(
    provider: str,
    records: list[tuple[datetime, dict[str, Any]]],
    origin: str,
) -> list[dict[str, Any]]:
    names = LEDGER_PROVIDER_ALIASES.get(provider, frozenset({provider}))
    return [
        record
        for _, record in records
        if str(record.get("provider") or "").strip().lower() in names
        and str(record.get("origin") or "").strip() == origin
    ]


def _provider_completed_cycles(
    provider: str,
    records: list[tuple[datetime, dict[str, Any]]],
    cycle_records: list[tuple[datetime, dict[str, Any]]],
) -> list[tuple[datetime, dict[str, Any]]]:
    """Return only cycle metrics that actually closed this provider's batches."""
    closing_times = {
        str(record.get("_audit_cycle_at"))
        for record in _matching_provider_batches(provider, records, "scheduler")
        if record.get("_audit_cycle_at")
    }
    return [item for item in cycle_records if _iso(item[0]) in closing_times]


def _linkedin_detected(runs: list[tuple[datetime, dict[str, Any]]]) -> int:
    """Sum LinkedIn deliveries represented by reports in the ledger window."""
    total = 0
    for _, run in runs:
        filters = run.get("filters")
        if isinstance(filters, dict):
            total += _nonnegative_int(filters.get("detected"))
    return total


def _linkedin_runs_for_ledger(
    records: list[tuple[datetime, dict[str, Any]]],
    runs: list[tuple[datetime, dict[str, Any]]],
) -> list[tuple[datetime, dict[str, Any]]]:
    """Select dual-channel reports by run ID, never by timing coincidence."""
    linked_batches = _matching_provider_batches("linkedin", records, "linkedin_dual")
    run_ids = {
        str(record.get("run_id") or "").strip()
        for record in linked_batches
        if str(record.get("run_id") or "").strip()
    }
    legacy_started_at = min(
        (
            recorded_at
            for recorded_at, record in records
            if not str(record.get("run_id") or "").strip()
        ),
        default=None,
    )
    return [
        item
        for item in runs
        if str(item[1].get("run_id") or "").strip() in run_ids
        or (legacy_started_at is not None and item[0] >= legacy_started_at)
    ]


def _job_reconciliation(
    provider: str,
    expected_detected: int,
    records: list[tuple[datetime, dict[str, Any]]],
    *,
    monitored: bool,
    pending_records: list[tuple[datetime, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Reconcile every extracted item to a terminal process outcome.

    The compact ledger stores one batch per provider with either terminal-outcome
    totals or opaque per-job hashes. It avoids storing job descriptions, URLs,
    titles, and Telegram content while preserving complete batch accounting.
    """
    if not monitored:
        return {
            "status": "not_applicable",
            "reason": "provider_not_monitored",
            "expected_detected": expected_detected,
            "audited_detected": 0,
            "terminal": 0,
            "unaccounted": 0,
            "outcomes": {},
            "pending_batches": 0,
            "pending_detected": 0,
        }

    origin = "linkedin_dual" if provider == "linkedin" else "scheduler"
    batches = _matching_provider_batches(provider, records, origin)
    pending_batches = _matching_provider_batches(
        provider, pending_records or [], origin
    )
    pending_detected = sum(
        _nonnegative_int(batch.get("detected")) for batch in pending_batches
    )
    pending_summary = {
        "pending_batches": len(pending_batches),
        "pending_detected": pending_detected,
    }

    # A batch written after the latest cycle/run record belongs to work that
    # has not reached its terminal evidence yet.  It is visible in the report
    # but cannot be a count mismatch with the preceding completed cycle.
    if not batches and pending_batches:
        return {
            "status": "in_progress",
            "reason": ["cycle_in_progress_not_yet_persisted"],
            "batches": 0,
            "expected_detected": expected_detected,
            "audited_detected": 0,
            "terminal": 0,
            "unaccounted": 0,
            "item_rows": 0,
            "invalid_items": 0,
            "incomplete_batches": 0,
            "outcomes": {},
            **pending_summary,
        }
    # A deployment that predates the ledger cannot prove individual outcomes.
    # Keep that transition visible as insufficient evidence, rather than
    # reporting secondary count mismatches as if they were data corruption.
    if not batches:
        return {
            "status": "insufficient_data",
            "reason": [
                "missing_per_job_ledger"
                if expected_detected > 0
                else "no_provider_items_in_ledger_window"
            ],
            "batches": 0,
            "expected_detected": expected_detected,
            "audited_detected": 0,
            "terminal": 0,
            "unaccounted": 0,
            "item_rows": 0,
            "invalid_items": 0,
            "incomplete_batches": 0,
            "outcomes": {},
            **pending_summary,
        }
    outcomes: Counter[str] = Counter()
    audited_detected = 0
    terminal = 0
    unaccounted = 0
    item_rows = 0
    invalid_items = 0
    incomplete_batches = 0
    for batch in batches:
        audited_detected += _nonnegative_int(batch.get("detected"))
        terminal += _nonnegative_int(batch.get("terminal"))
        unaccounted += _nonnegative_int(batch.get("unaccounted"))
        if not bool(batch.get("complete")):
            incomplete_batches += 1
        items = batch.get("jobs")
        if isinstance(items, list):
            item_rows += len(items)
            for item in items:
                outcome = item.get("outcome") if isinstance(item, dict) else None
                if not isinstance(outcome, str) or outcome not in TERMINAL_OUTCOMES:
                    invalid_items += 1
                    continue
                outcomes[outcome] += 1
            continue

        # Production uses aggregate outcome totals to bound disk growth.  A
        # legacy/detail ledger with individual rows remains supported above.
        aggregate_outcomes = batch.get("outcomes")
        if not isinstance(aggregate_outcomes, dict):
            invalid_items += _nonnegative_int(batch.get("detected"))
            continue
        aggregate_rows = 0
        for outcome, value in aggregate_outcomes.items():
            count = _nonnegative_int(value)
            if outcome not in TERMINAL_OUTCOMES:
                invalid_items += count
                continue
            outcomes[str(outcome)] += count
            aggregate_rows += count
        item_rows += aggregate_rows
        if aggregate_rows != _nonnegative_int(batch.get("terminal")):
            invalid_items += abs(
                aggregate_rows - _nonnegative_int(batch.get("terminal"))
            )

    reasons: list[str] = []
    if audited_detected != expected_detected:
        reasons.append("detected_count_mismatch")
    if item_rows != audited_detected:
        reasons.append("job_rows_count_mismatch")
    if (
        terminal != audited_detected
        or unaccounted
        or invalid_items
        or incomplete_batches
    ):
        reasons.append("unaccounted_or_nonterminal_job")
    status = (
        "ok"
        if not reasons
        else (
            "insufficient_data" if reasons == ["missing_per_job_ledger"] else "critical"
        )
    )
    return {
        "status": status,
        "reason": reasons,
        "batches": len(batches),
        "expected_detected": expected_detected,
        "audited_detected": audited_detected,
        "terminal": terminal,
        "unaccounted": unaccounted,
        "item_rows": item_rows,
        "invalid_items": invalid_items,
        "incomplete_batches": incomplete_batches,
        "outcomes": dict(sorted(outcomes.items())),
        **pending_summary,
    }


def _apply_job_reconciliation(
    summary: dict[str, Any], reconciliation: dict[str, Any]
) -> None:
    """Promote ledger gaps into the provider state without hiding prior faults."""
    summary["job_reconciliation"] = reconciliation
    state = str(reconciliation["status"])
    if state == "critical":
        summary["status"] = "critical"
        summary["reasons"].append("per_job_reconciliation_failed")
    elif state == "insufficient_data" and summary["status"] == "ok":
        summary["status"] = "insufficient_data"
        summary["reasons"].append("per_job_reconciliation_unavailable")


def _validation_snapshot(path: Path) -> dict[str, Any]:
    """Expose only status metadata; reports remain the review authority."""
    if not path.exists():
        return {"available": False, "status_counts": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"available": False, "status_counts": {}, "read_error": True}
    values = raw.values() if isinstance(raw, dict) else []
    statuses = Counter(
        str(item.get("status") or "unknown")
        for item in values
        if isinstance(item, dict)
    )
    return {"available": True, "status_counts": dict(statuses)}


def _status_evidence_value(status: str) -> int | None:
    return {
        "ok": 100,
        "warning": 55,
        "critical": 0,
        "insufficient_data": 25,
    }.get(status)


def build_daily_coverage_report(
    base_dir: Path, config: BotConfig, now: datetime | None = None
) -> dict[str, Any]:
    """Build a deterministic report from persisted files only."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    lookback = timedelta(hours=int(config.daily_coverage_lookback_hours))
    window_start = now - lookback
    data_dir = base_dir / "data"
    cycle_records, malformed_cycle_lines, invalid_cycle_timestamps = (
        _read_jsonl_in_window(data_dir / RATE_LIMIT_METRICS_FILE, window_start, now)
    )
    linkedin_runs, malformed_run_lines, invalid_run_timestamps = _read_jsonl_in_window(
        data_dir / LINKEDIN_RUNS_FILE, window_start, now
    )
    job_records, malformed_job_lines, invalid_job_timestamps, job_paths = (
        _job_audit_records(data_dir, window_start, now)
    )
    completed_scheduler_records, pending_scheduler_records = (
        _partition_scheduler_ledger(
            job_records,
            cycle_records,
            max_completion_delay_seconds=max(300, int(config.poll_seconds) * 2),
        )
    )
    completed_linkedin_records, pending_linkedin_records = _partition_linkedin_ledger(
        job_records, linkedin_runs
    )
    scheduler_ledger_started_at = _ledger_started_at(completed_scheduler_records)
    linkedin_ledger_started_at = _ledger_started_at(completed_linkedin_records)
    reconciliation_linkedin_runs = _linkedin_runs_for_ledger(
        completed_linkedin_records, linkedin_runs
    )

    expected_cycles = _expected_runs(
        int(config.daily_coverage_lookback_hours) * 3600, int(config.poll_seconds)
    )
    providers = [
        str(provider).strip()
        for provider in config.enabled_providers
        if str(provider).strip()
    ]
    summaries: list[dict[str, Any]] = []
    for provider in providers:
        if provider == "linkedin" and bool(config.linkedin_extension_enabled):
            summary = _linkedin_summary(linkedin_runs, now, config)
            _apply_job_reconciliation(
                summary,
                _job_reconciliation(
                    provider,
                    _linkedin_detected(reconciliation_linkedin_runs),
                    completed_linkedin_records,
                    monitored=True,
                    pending_records=pending_linkedin_records,
                ),
            )
        else:
            summary = _provider_summary(provider, cycle_records, now, config)
            provider_completed_batches = _matching_provider_batches(
                provider, completed_scheduler_records, "scheduler"
            )
            provider_cycles = _provider_completed_cycles(
                provider, completed_scheduler_records, cycle_records
            )
            # With no ledger evidence at all, retain the metrics count so the
            # audit reports insufficient evidence rather than a false zero.
            expected_detected = _provider_detected(
                provider,
                provider_cycles if provider_completed_batches else cycle_records,
            )
            _apply_job_reconciliation(
                summary,
                _job_reconciliation(
                    provider,
                    expected_detected,
                    completed_scheduler_records,
                    monitored=summary["status"] != "not_monitored",
                    pending_records=pending_scheduler_records,
                ),
            )
        summaries.append(summary)

    active_values = [
        value
        for item in summaries
        if (value := _status_evidence_value(str(item["status"]))) is not None
    ]
    scheduler_ratio = min(1.0, len(cycle_records) / expected_cycles)
    evidence_score = (
        round(
            min(100.0, scheduler_ratio * 100, sum(active_values) / len(active_values))
        )
        if active_values
        else 0
    )
    status_counts = Counter(str(item["status"]) for item in summaries)
    if status_counts["critical"]:
        overall_status = "critical"
    elif status_counts["warning"]:
        overall_status = "warning"
    elif status_counts["insufficient_data"]:
        overall_status = "insufficient_data"
    elif active_values:
        overall_status = "ok"
    else:
        overall_status = "insufficient_data"

    latest_cycle_at = cycle_records[-1][0] if cycle_records else None
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(now),
        "window": {
            "start": _iso(window_start),
            "end": _iso(now),
            "lookback_hours": int(config.daily_coverage_lookback_hours),
        },
        "scope": {
            "kind": "operational_evidence",
            "does_not_scrape": True,
            "does_not_modify_seen": True,
            "does_not_send_job_alerts": True,
            "limitation": (
                "It proves the terminal processing outcome of every recorded item, not complete external-market coverage."
            ),
            "per_job_reconciliation_starts_at": _iso(scheduler_ledger_started_at),
            "per_job_reconciliation_through": _iso(
                cycle_records[-1][0] if cycle_records else None
            ),
            "pending_scheduler_ledger_batches": len(pending_scheduler_records),
            "pending_linkedin_ledger_batches": len(pending_linkedin_records),
        },
        "scheduler": {
            "cycle_records": len(cycle_records),
            "expected_cycles": expected_cycles,
            "cycle_ratio": round(scheduler_ratio, 3),
            "last_cycle_at": _iso(latest_cycle_at),
            "last_cycle_age_minutes": _age_minutes(now, latest_cycle_at),
        },
        "overall": {
            "status": overall_status,
            "operational_evidence_score": evidence_score,
            "score_definition": "min(scheduler execution ratio, mean provider evidence status values)",
            "provider_status_counts": dict(status_counts),
        },
        "providers": summaries,
        "linkedin": next(
            (item for item in summaries if item["provider"] == "linkedin"), None
        ),
        "provider_validation_snapshot": _validation_snapshot(
            Path(config.provider_validation_dir) / "status.json"
        ),
        "input_quality": {
            "metrics_path": str(data_dir / RATE_LIMIT_METRICS_FILE),
            "linkedin_runs_path": str(data_dir / LINKEDIN_RUNS_FILE),
            "job_audit_paths": job_paths,
            "job_audit_started_at": _iso(_ledger_started_at(job_records)),
            "completed_scheduler_ledger_started_at": _iso(scheduler_ledger_started_at),
            "completed_linkedin_ledger_started_at": _iso(linkedin_ledger_started_at),
            "malformed_cycle_lines": malformed_cycle_lines,
            "invalid_cycle_timestamps": invalid_cycle_timestamps,
            "malformed_linkedin_lines": malformed_run_lines,
            "invalid_linkedin_timestamps": invalid_run_timestamps,
            "malformed_job_audit_lines": malformed_job_lines,
            "invalid_job_audit_timestamps": invalid_job_timestamps,
        },
    }
    return report


def write_daily_coverage_report(
    report: dict[str, Any], output_dir: Path
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = _as_utc(report.get("generated_at")) or datetime.now(timezone.utc)
    dated_path = output_dir / f"{generated_at.date().isoformat()}.json"
    latest_path = output_dir / "latest.json"
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    dated_path.write_text(payload, encoding="utf-8")
    latest_path.write_text(payload, encoding="utf-8")
    return dated_path, latest_path


def _escape_telegram_markdown(value: object) -> str:
    """Keep diagnostic values literal while the surrounding summary uses Markdown."""
    escaped = str(value)
    for character in ("\\", "_", "*", "`", "["):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def format_telegram_summary(report: dict[str, Any], report_path: Path) -> str:
    overall = report["overall"]
    scheduler = report["scheduler"]
    status_icon = {
        "ok": "OK",
        "warning": "AVISO",
        "critical": "CRITICO",
        "insufficient_data": "SIN DATOS",
    }
    lines = [
        "*Auditoria diaria del bot*",
        (
            f"Evidencia operativa: *{overall['operational_evidence_score']}/100* "
            f"({status_icon.get(overall['status'], overall['status'])})"
        ),
        (
            f"Ciclos registrados: {scheduler['cycle_records']}/{scheduler['expected_cycles']} "
            f"en {report['window']['lookback_hours']} h"
        ),
    ]
    for item in report["providers"]:
        provider = item["provider"]
        status = str(item["status"])
        reconciliation = item.get("job_reconciliation", {})
        accounted = (
            f"contabilidad {reconciliation.get('terminal', 0)}/"
            f"{reconciliation.get('expected_detected', 0)}"
        )
        if reconciliation.get("pending_batches", 0):
            accounted += f"; ciclo en curso {reconciliation.get('pending_detected', 0)}"
        if provider == "linkedin" and "runs_observed" in item:
            detail = (
                f"runs {item['runs_observed']}/{item['runs_expected']}; "
                f"extension completa {item['extension_complete_runs']}; parcial {item['partial_runs']}; {accounted}"
            )
        else:
            outcomes = item["outcomes"]
            detail = (
                f"ciclos {item['cycles_observed']}/{item['cycles_recorded']}; "
                f"detectadas {outcomes['detected']}; elegibles {outcomes['eligible']}; "
                f"enviadas {outcomes['sent']}; {accounted}"
            )
        lines.append(
            f"- {status_icon.get(status, _escape_telegram_markdown(status))} "
            f"{_escape_telegram_markdown(provider)}: {detail}"
        )
    lines.append("Contabilidad final del bot; no prueba cobertura total del mercado.")
    lines.append(f"Informe: {_escape_telegram_markdown(report_path)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit persisted daily bot execution evidence."
    )
    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="Write the report without a Telegram summary.",
    )
    parser.add_argument(
        "--output-dir", type=Path, help="Override DAILY_COVERAGE_DIR for this run."
    )
    args = parser.parse_args(argv)

    config = load_config()
    base_dir = Path(__file__).resolve().parent
    logging.basicConfig(
        level=getattr(logging, str(config.log_level).upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    logger = logging.getLogger("daily-coverage-audit")
    report = build_daily_coverage_report(base_dir, config)
    dated_path, _ = write_daily_coverage_report(
        report, args.output_dir or Path(config.daily_coverage_dir)
    )
    logger.info(
        "Daily coverage audit | status=%s evidence=%s cycles=%s/%s report=%s",
        report["overall"]["status"],
        report["overall"]["operational_evidence_score"],
        report["scheduler"]["cycle_records"],
        report["scheduler"]["expected_cycles"],
        dated_path,
    )
    if not args.no_telegram and bool(config.daily_coverage_telegram_summary):
        sent = TelegramNotifier(config, logger).send_message(
            format_telegram_summary(report, dated_path)
        )
        logger.info("Daily coverage Telegram summary | sent=%s", sent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
