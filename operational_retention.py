"""Bounded retention for generated operational telemetry."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

_LOCK_GUARD = threading.Lock()
# Keep a lock only while at least one writer holds a reference to it.  A
# pop-after-use race could otherwise let a waiting writer use an orphaned lock
# while a third writer creates another one for the same JSONL file.
_LOCKS: dict[str, tuple[threading.Lock, int]] = {}


@contextlib.contextmanager
def jsonl_file_lock(path: Path) -> Iterator[None]:
    """Serialize local writers without retaining open files or background state."""
    key = str(path.resolve())
    with _LOCK_GUARD:
        existing = _LOCKS.get(key)
        if existing is None:
            lock, references = threading.Lock(), 0
        else:
            lock, references = existing
        _LOCKS[key] = (lock, references + 1)
    try:
        with lock:
            yield
    finally:
        with _LOCK_GUARD:
            current = _LOCKS.get(key)
            if current is not None and current[0] is lock:
                remaining = current[1] - 1
                if remaining:
                    _LOCKS[key] = (lock, remaining)
                else:
                    _LOCKS.pop(key, None)


def _timestamp(record: dict[str, object]) -> datetime | None:
    value = record.get("timestamp")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)


def _prune_jsonl(path: Path, cutoff: datetime) -> tuple[int, int]:
    """Stream a JSONL file and atomically retain current or unparseable evidence."""
    if not path.exists():
        return (0, 0)
    removed = 0
    retained = 0
    with jsonl_file_lock(path):
        with (
            path.open("r", encoding="utf-8") as source,
            tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                delete=False,
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
            ) as target,
        ):
            temp_path = Path(target.name)
            for line in source:
                try:
                    record = json.loads(line)
                    stamp = _timestamp(record) if isinstance(record, dict) else None
                except json.JSONDecodeError:
                    stamp = None
                if stamp is not None and stamp < cutoff:
                    removed += 1
                    continue
                target.write(line)
                retained += 1
        if removed:
            os.replace(temp_path, path)
        else:
            temp_path.unlink(missing_ok=True)
    return (removed, retained)


def _prune_dated_files(directory: Path, cutoff_date) -> int:
    if not directory.exists():
        return 0
    removed = 0
    for path in directory.glob("*.jsonl"):
        try:
            date_value = datetime.fromisoformat(path.stem).date()
        except ValueError:
            continue
        if date_value < cutoff_date:
            path.unlink()
            removed += 1
    return removed


def _prune_old_files(directory: Path, cutoff: datetime) -> int:
    if not directory.exists():
        return 0
    removed = 0
    for path in directory.rglob("*"):
        if not path.is_file() or path.name == "latest.json":
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if modified < cutoff:
            path.unlink()
            removed += 1
    return removed


def cleanup_operational_data(
    base_dir: Path, config: object, *, now: datetime | None = None
) -> dict[str, int]:
    """Prune only generated telemetry; ``seen_jobs.txt`` deliberately remains untouched."""
    now = now or datetime.now(timezone.utc)
    data_dir = base_dir / "data"
    metrics_days = max(
        1, int(getattr(config, "operational_metrics_retention_days", 90))
    )
    audit_days = max(1, int(getattr(config, "job_audit_retention_days", 35)))
    coverage_days = max(1, int(getattr(config, "daily_coverage_retention_days", 90)))
    validation_days = max(
        1, int(getattr(config, "provider_validation_retention_days", 180))
    )
    result = {
        "jsonl_records": 0,
        "job_audit_files": 0,
        "coverage_files": 0,
        "inventory_audit_files": 0,
        "validation_files": 0,
    }
    for filename in (
        "metrics_jobs.jsonl",
        "rate_limit_metrics.jsonl",
        "linkedin_runs.jsonl",
    ):
        removed, _ = _prune_jsonl(
            data_dir / filename, now - timedelta(days=metrics_days)
        )
        result["jsonl_records"] += removed
    result["job_audit_files"] = _prune_dated_files(
        data_dir / "job_audit", (now - timedelta(days=audit_days)).date()
    )
    result["coverage_files"] = _prune_old_files(
        data_dir / "daily_coverage", now - timedelta(days=coverage_days)
    )
    result["inventory_audit_files"] = _prune_old_files(
        data_dir / "linkedin_inventory_audit", now - timedelta(days=coverage_days)
    )
    result["validation_files"] = _prune_old_files(
        data_dir / "provider_validation" / "runs", now - timedelta(days=validation_days)
    )
    return result
