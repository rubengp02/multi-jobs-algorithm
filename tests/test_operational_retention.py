import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from operational_retention import cleanup_operational_data

NOW = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )


class OperationalRetentionTests(unittest.TestCase):
    def test_prunes_generated_history_and_preserves_seen(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            data_dir = base_dir / "data"
            old = NOW - timedelta(days=100)
            recent = NOW - timedelta(days=1)
            _write_jsonl(
                data_dir / "metrics_jobs.jsonl",
                [{"timestamp": old.isoformat()}, {"timestamp": recent.isoformat()}],
            )
            _write_jsonl(
                data_dir / "rate_limit_metrics.jsonl", [{"timestamp": old.isoformat()}]
            )
            _write_jsonl(
                data_dir / "linkedin_runs.jsonl", [{"timestamp": recent.isoformat()}]
            )
            old_audit = data_dir / "job_audit" / "2026-07-01.jsonl"
            current_audit = data_dir / "job_audit" / "2026-08-24.jsonl"
            _write_jsonl(old_audit, [{"timestamp": old.isoformat()}])
            _write_jsonl(current_audit, [{"timestamp": recent.isoformat()}])
            old_coverage = data_dir / "daily_coverage" / "2026-07-01.json"
            old_coverage.parent.mkdir(parents=True, exist_ok=True)
            old_coverage.write_text("{}", encoding="utf-8")
            os.utime(old_coverage, (old.timestamp(), old.timestamp()))
            latest = data_dir / "daily_coverage" / "latest.json"
            latest.write_text("{}", encoding="utf-8")
            old_validation = data_dir / "provider_validation" / "runs" / "old.json"
            old_validation.parent.mkdir(parents=True, exist_ok=True)
            old_validation.write_text("{}", encoding="utf-8")
            os.utime(old_validation, (old.timestamp(), old.timestamp()))
            seen = data_dir / "seen_jobs.txt"
            seen.write_text("must-stay\n", encoding="utf-8")
            config = SimpleNamespace(
                operational_metrics_retention_days=90,
                job_audit_retention_days=35,
                daily_coverage_retention_days=90,
                provider_validation_retention_days=90,
            )

            result = cleanup_operational_data(base_dir, config, now=NOW)

            metrics = [
                json.loads(line)
                for line in (data_dir / "metrics_jobs.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(len(metrics), 1)
            self.assertEqual(metrics[0]["timestamp"], recent.isoformat())
            self.assertFalse(old_audit.exists())
            self.assertTrue(current_audit.exists())
            self.assertFalse(old_coverage.exists())
            self.assertTrue(latest.exists())
            self.assertFalse(old_validation.exists())
            self.assertEqual(seen.read_text(encoding="utf-8"), "must-stay\n")
            self.assertGreaterEqual(result["jsonl_records"], 2)
