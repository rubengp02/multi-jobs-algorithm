import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from daily_coverage_audit import (
    _read_jsonl_in_window,
    build_daily_coverage_report,
    format_telegram_summary,
    write_daily_coverage_report,
)

NOW = datetime(2026, 8, 24, 22, 0, tzinfo=timezone.utc)


def _append_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )


def _config(root: Path, enabled_providers: list[str], extension_enabled: bool = True):
    return SimpleNamespace(
        poll_seconds=900,
        enabled_providers=enabled_providers,
        daily_coverage_lookback_hours=1,
        daily_coverage_min_cycle_ratio=0.80,
        daily_coverage_max_stale_minutes=50,
        linkedin_extension_enabled=extension_enabled,
        linkedin_extension_refresh_seconds=900,
        provider_validation_dir=str(root / "data" / "provider_validation"),
    )


def _provider_stats(**overrides: int | str) -> dict:
    stats: dict[str, int | str] = {
        "detected": 3,
        "eligible": 1,
        "discarded_location": 0,
        "discarded_include": 0,
        "discarded_exclude": 0,
        "discarded_relevance": 0,
        "relevance_warning": 0,
        "description_unavailable": 0,
        "discarded_description_unavailable": 0,
        "duplicate_channels": 0,
        "seen": 0,
        "paused": 0,
        "notification_limit": 0,
        "alerts_disabled": 0,
        "delivery_failed": 0,
        "saved": 1,
        "sent": 1,
        "http_429": 0,
        "blocked_reason": "",
    }
    stats.update(overrides)
    return stats


def _cycle(when: datetime, provider_stats: dict, provider: str = "infojobs") -> dict:
    return {
        "timestamp": when.isoformat(),
        "http_429": int(provider_stats.get("http_429", 0)),
        "providers": {provider: provider_stats},
    }


def _linkedin_run(when: datetime) -> dict:
    return {
        "timestamp": when.isoformat(),
        "run_id": f"run-{when.minute}",
        "extension_complete": True,
        "api_complete": True,
        "fallback_active": False,
        "partial": False,
        "filters": {"detected": 3},
        "inventory_audit": {
            "valid": True,
            "coverage_correct": True,
            "eligible_absences": 0,
        },
        "urls": [{"extension": {"state": "ok"}, "api": {"state": "ok"}}],
    }


def _job_audit(
    when: datetime, provider: str, *, detected: int = 3, terminal: int | None = None
) -> dict:
    final = detected if terminal is None else terminal
    outcomes = {"sent": final} if final else {}
    return {
        "timestamp": when.isoformat(),
        "provider": provider,
        "origin": "linkedin_dual" if provider == "linkedin" else "scheduler",
        "detected": detected,
        "terminal": final,
        "unaccounted": detected - final,
        "complete": final == detected,
        "outcomes": outcomes,
        "jobs": [
            {
                "key": f"{provider}-{when.minute}-{index}",
                "outcome": "sent" if index < final else None,
            }
            for index in range(detected)
        ],
    }


class DailyCoverageAuditTests(unittest.TestCase):
    def test_jsonl_reader_retains_only_the_requested_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "evidence.jsonl"
            _append_jsonl(
                path,
                [
                    {"timestamp": (NOW - timedelta(days=2)).isoformat()},
                    {"timestamp": NOW.isoformat(), "provider": "infojobs"},
                    {"timestamp": "not-a-date"},
                ],
            )
            with path.open("a", encoding="utf-8") as handle:
                handle.write("not-json\n")

            records, malformed, invalid_timestamps = _read_jsonl_in_window(
                path, NOW - timedelta(hours=1), NOW + timedelta(minutes=1)
            )

            self.assertEqual(1, len(records))
            self.assertEqual("infojobs", records[0][1]["provider"])
            self.assertEqual(1, malformed)
            self.assertEqual(1, invalid_timestamps)

    def test_healthy_evidence_is_written_without_touching_seen(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            data_dir = base_dir / "data"
            seen_path = data_dir / "seen_jobs.txt"
            seen_path.parent.mkdir(parents=True)
            seen_path.write_text("already-seen\n", encoding="utf-8")
            instants = [NOW - timedelta(minutes=value) for value in (45, 30, 15, 1)]
            _append_jsonl(
                data_dir / "rate_limit_metrics.jsonl",
                [_cycle(value, _provider_stats()) for value in instants],
            )
            _append_jsonl(
                data_dir / "linkedin_runs.jsonl",
                [_linkedin_run(value) for value in instants],
            )
            _append_jsonl(
                data_dir / "job_audit" / "2026-08-24.jsonl",
                [
                    _job_audit(value, provider)
                    for value in instants
                    for provider in ("linkedin", "infojobs")
                ],
            )

            report = build_daily_coverage_report(
                base_dir, _config(base_dir, ["linkedin", "infojobs"]), now=NOW
            )
            dated_path, latest_path = write_daily_coverage_report(
                report, data_dir / "daily_coverage"
            )

            self.assertEqual(report["overall"]["status"], "ok")
            self.assertEqual(report["scheduler"]["cycle_records"], 4)
            self.assertEqual(report["providers"][1]["outcomes"]["detected"], 12)
            self.assertEqual(
                report["providers"][1]["job_reconciliation"]["terminal"], 12
            )
            self.assertEqual(seen_path.read_text(encoding="utf-8"), "already-seen\n")
            self.assertTrue(dated_path.is_file())
            self.assertEqual(
                json.loads(latest_path.read_text(encoding="utf-8"))["overall"][
                    "status"
                ],
                "ok",
            )

    def test_rate_limit_and_missing_cycles_are_visible_as_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            data_dir = base_dir / "data"
            _append_jsonl(
                data_dir / "rate_limit_metrics.jsonl",
                [
                    _cycle(NOW - timedelta(minutes=30), _provider_stats(http_429=1)),
                    _cycle(NOW - timedelta(minutes=5), _provider_stats(http_429=1)),
                ],
            )
            _append_jsonl(
                data_dir / "linkedin_runs.jsonl",
                [
                    _linkedin_run(NOW - timedelta(minutes=value))
                    for value in (45, 30, 15, 1)
                ],
            )
            _append_jsonl(
                data_dir / "job_audit" / "2026-08-24.jsonl",
                [
                    _job_audit(value, "linkedin")
                    for value in (
                        NOW - timedelta(minutes=45),
                        NOW - timedelta(minutes=30),
                        NOW - timedelta(minutes=15),
                        NOW - timedelta(minutes=1),
                    )
                ]
                + [
                    _job_audit(value, "infojobs")
                    for value in (
                        NOW - timedelta(minutes=30),
                        NOW - timedelta(minutes=5),
                    )
                ],
            )

            report = build_daily_coverage_report(
                base_dir, _config(base_dir, ["linkedin", "infojobs"]), now=NOW
            )

            self.assertEqual(report["overall"]["status"], "warning")
            self.assertEqual(report["scheduler"]["cycle_records"], 2)
            self.assertIn("http_429_observed", report["providers"][1]["reasons"])

    def test_unaccounted_job_item_is_critical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            data_dir = base_dir / "data"
            when = NOW - timedelta(minutes=5)
            _append_jsonl(
                data_dir / "rate_limit_metrics.jsonl",
                [_cycle(when, _provider_stats())],
            )
            _append_jsonl(
                data_dir / "job_audit" / "2026-08-24.jsonl",
                [_job_audit(when, "infojobs", terminal=2)],
            )

            report = build_daily_coverage_report(
                base_dir,
                _config(base_dir, ["infojobs"], extension_enabled=False),
                now=NOW,
            )

            reconciliation = report["providers"][0]["job_reconciliation"]
            self.assertEqual(report["overall"]["status"], "critical")
            self.assertEqual(reconciliation["unaccounted"], 1)
            self.assertIn(
                "per_job_reconciliation_failed", report["providers"][0]["reasons"]
            )

    def test_missing_per_job_ledger_is_not_reported_as_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            data_dir = base_dir / "data"
            _append_jsonl(
                data_dir / "rate_limit_metrics.jsonl",
                [_cycle(NOW - timedelta(minutes=5), _provider_stats())],
            )

            report = build_daily_coverage_report(
                base_dir,
                _config(base_dir, ["infojobs"], extension_enabled=False),
                now=NOW,
            )

            reconciliation = report["providers"][0]["job_reconciliation"]
            self.assertEqual(report["providers"][0]["status"], "insufficient_data")
            self.assertEqual(reconciliation["status"], "insufficient_data")
            self.assertIn("missing_per_job_ledger", reconciliation["reason"])

    def test_ledger_baseline_does_not_reconcile_predeployment_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            data_dir = base_dir / "data"
            old_cycle = NOW - timedelta(minutes=45)
            current_cycle = NOW - timedelta(minutes=5)
            _append_jsonl(
                data_dir / "rate_limit_metrics.jsonl",
                [
                    _cycle(old_cycle, _provider_stats()),
                    _cycle(current_cycle, _provider_stats(detected=2)),
                ],
            )
            _append_jsonl(
                data_dir / "job_audit" / "2026-08-24.jsonl",
                [_job_audit(current_cycle, "infojobs", detected=2)],
            )

            report = build_daily_coverage_report(
                base_dir,
                _config(base_dir, ["infojobs"], extension_enabled=False),
                now=NOW,
            )

            reconciliation = report["providers"][0]["job_reconciliation"]
            self.assertEqual(report["providers"][0]["outcomes"]["detected"], 5)
            self.assertEqual(reconciliation["expected_detected"], 2)
            self.assertEqual(reconciliation["terminal"], 2)
            self.assertEqual(reconciliation["status"], "ok")
            self.assertEqual(
                report["scope"]["per_job_reconciliation_starts_at"],
                current_cycle.isoformat(timespec="seconds"),
            )

    def test_open_scheduler_cycle_is_deferred_not_reported_as_lost(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            data_dir = base_dir / "data"
            completed_cycle = NOW - timedelta(minutes=20)
            open_batch = NOW - timedelta(minutes=1)
            _append_jsonl(
                data_dir / "rate_limit_metrics.jsonl",
                [_cycle(completed_cycle, _provider_stats(detected=2))],
            )
            _append_jsonl(
                data_dir / "job_audit" / "2026-08-24.jsonl",
                [
                    _job_audit(completed_cycle, "infojobs", detected=2),
                    _job_audit(open_batch, "infojobs", detected=3),
                ],
            )

            report = build_daily_coverage_report(
                base_dir,
                _config(base_dir, ["infojobs"], extension_enabled=False),
                now=NOW,
            )

            reconciliation = report["providers"][0]["job_reconciliation"]
            self.assertEqual(report["overall"]["status"], "ok")
            self.assertEqual(reconciliation["status"], "ok")
            self.assertEqual(reconciliation["expected_detected"], 2)
            self.assertEqual(reconciliation["terminal"], 2)
            self.assertEqual(reconciliation["pending_batches"], 1)
            self.assertEqual(reconciliation["pending_detected"], 3)

    def test_compact_outcome_totals_are_reconciled_without_job_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            data_dir = base_dir / "data"
            when = NOW - timedelta(minutes=5)
            _append_jsonl(
                data_dir / "rate_limit_metrics.jsonl",
                [
                    _cycle(
                        when, _provider_stats(detected=2, eligible=1, saved=1, sent=1)
                    )
                ],
            )
            record = _job_audit(when, "infojobs", detected=2)
            record.pop("jobs")
            record["outcomes"] = {"sent": 1, "seen": 1}
            _append_jsonl(data_dir / "job_audit" / "2026-08-24.jsonl", [record])

            report = build_daily_coverage_report(
                base_dir,
                _config(base_dir, ["infojobs"], extension_enabled=False),
                now=NOW,
            )

            reconciliation = report["providers"][0]["job_reconciliation"]
            self.assertEqual(reconciliation["status"], "ok")
            self.assertEqual(reconciliation["terminal"], 2)
            self.assertEqual(reconciliation["outcomes"], {"seen": 1, "sent": 1})

    def test_linkedin_run_is_matched_by_run_id_even_if_report_precedes_ledger(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            data_dir = base_dir / "data"
            run_at = NOW - timedelta(minutes=10)
            ledger_at = NOW - timedelta(minutes=9)
            _append_jsonl(
                data_dir / "linkedin_runs.jsonl",
                [
                    {
                        **_linkedin_run(run_at),
                        "run_id": "run-linked-before-ledger",
                    }
                ],
            )
            record = _job_audit(ledger_at, "linkedin")
            record["run_id"] = "run-linked-before-ledger"
            _append_jsonl(data_dir / "job_audit" / "2026-08-24.jsonl", [record])

            report = build_daily_coverage_report(
                base_dir, _config(base_dir, ["linkedin"]), now=NOW
            )

            reconciliation = report["providers"][0]["job_reconciliation"]
            self.assertEqual(reconciliation["status"], "ok")
            self.assertEqual(reconciliation["expected_detected"], 3)
            self.assertEqual(reconciliation["terminal"], 3)

    def test_stable_greenhouse_source_is_reconciled_as_greenhouse_spain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            data_dir = base_dir / "data"
            when = NOW - timedelta(minutes=5)
            _append_jsonl(
                data_dir / "rate_limit_metrics.jsonl",
                [
                    _cycle(
                        when,
                        _provider_stats(detected=2, eligible=0, saved=0, sent=0),
                        provider="greenhouse_spain",
                    )
                ],
            )
            _append_jsonl(
                data_dir / "job_audit" / "2026-08-24.jsonl",
                [_job_audit(when, "greenhouse", detected=2)],
            )

            report = build_daily_coverage_report(
                base_dir,
                _config(base_dir, ["greenhouse_spain"], extension_enabled=False),
                now=NOW,
            )

            reconciliation = report["providers"][0]["job_reconciliation"]
            self.assertEqual(reconciliation["status"], "ok")
            self.assertEqual(reconciliation["expected_detected"], 2)
            self.assertEqual(reconciliation["terminal"], 2)

    def test_absent_runtime_evidence_is_not_reported_as_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            report = build_daily_coverage_report(
                base_dir,
                _config(base_dir, ["infojobs"], extension_enabled=False),
                now=NOW,
            )

            self.assertEqual(report["overall"]["status"], "insufficient_data")
            self.assertEqual(report["providers"][0]["status"], "insufficient_data")

    def test_telegram_summary_escapes_diagnostic_paths_and_provider_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            report = build_daily_coverage_report(
                base_dir,
                _config(base_dir, ["quality_temporal"], extension_enabled=False),
                now=NOW,
            )

            summary = format_telegram_summary(
                report, Path("data/daily_coverage/latest_report.json")
            )

            self.assertIn("quality\\_temporal", summary)
            self.assertIn("daily\\_coverage", summary)
            self.assertIn("latest\\_report.json", summary)
