import json
import logging
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main
from models import JobItem


class _Storage:
    def __init__(self, seen: set[tuple[str, str]] | None = None) -> None:
        self.seen = seen or set()
        self.added: list[tuple[str, str]] = []

    def is_seen(self, source: str, job_id: str) -> bool:
        return (source, job_id) in self.seen

    def add(self, source: str, job_id: str) -> None:
        self.seen.add((source, job_id))
        self.added.append((source, job_id))


class _Metrics:
    def __init__(self) -> None:
        self.recorded: list[str] = []

    def record_job(self, job: JobItem) -> None:
        self.recorded.append(job.id)


class _Notifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send_message(self, text: str, **_kwargs: object) -> bool:
        self.messages.append(text)
        return True


class _FailingNotifier(_Notifier):
    def send_message(self, text: str, **_kwargs: object) -> bool:
        self.messages.append(text)
        return False


class _CommandNotifier(_Notifier):
    def __init__(self, commands: list[tuple[int, str]]) -> None:
        super().__init__()
        self.commands = commands

    def fetch_command_messages(
        self, _chat_id: str, _offset: int | None
    ) -> tuple[list[tuple[int, str]], int]:
        return self.commands, 42


class _PlainProvider:
    def __init__(self) -> None:
        self.calls = 0

    def fetch_jobs(self) -> list[JobItem]:
        self.calls += 1
        return [_job("plain", "Python Developer")]


class _LinkedInProvider:
    def __init__(self) -> None:
        self.calls: list[bool] = []

    def fetch_jobs(self, startup_deep_scan: bool = False) -> list[JobItem]:
        self.calls.append(startup_deep_scan)
        return [_job("linkedin-scan", "Python Developer")]


class _RateLimitedProvider(_PlainProvider):
    last_blocked_reason = "rate_limit_429"


def _job(
    job_id: str, title: str, location: str = "Valencia", source: str = "linkedin"
) -> JobItem:
    return JobItem(
        id=job_id,
        title=title,
        company="Example",
        location=location,
        url=f"https://example.test/{job_id}",
        source=source,
        features={
            "linkedin_search_urls": [
                "https://www.linkedin.com/jobs/search/?f_TPR=r3600&sortBy=DD"
            ],
            "linkedin_recency_evidence": [
                {
                    "search_url": "https://www.linkedin.com/jobs/search/?f_TPR=r3600&sortBy=DD",
                    "posted_text": "Hace 10 minutos",
                    "published_at": "",
                }
            ],
        },
    )


class ProcessJobsStatsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_paused = main.BOT_PAUSED
        self.old_latest = main.LATEST_JOBS_CACHE
        self.old_today = main.TODAY_DISCOVERED_JOBS
        main.BOT_PAUSED = False
        main.LATEST_JOBS_CACHE = []
        main.TODAY_DISCOVERED_JOBS = []
        self.storage = _Storage({("linkedin", "seen")})
        self.metrics = _Metrics()
        self.notifier = _Notifier()
        self.ctx = SimpleNamespace(
            config=SimpleNamespace(include_words=["python"], exclude_words=["senior"]),
            storage=self.storage,
            metrics=self.metrics,
            notifier=self.notifier,
            logger=logging.getLogger("test-cycle-observability"),
        )

    def tearDown(self) -> None:
        main.BOT_PAUSED = self.old_paused
        main.LATEST_JOBS_CACHE = self.old_latest
        main.TODAY_DISCOVERED_JOBS = self.old_today

    @patch("main.enrich_job_description")
    def test_stats_explain_every_detected_job(self, enrich: object) -> None:
        enrich.side_effect = lambda job, _config: (
            "Java" if job.id == "include" else "Python"
        )  # type: ignore[attr-defined]
        jobs = [
            _job("location", "Python Developer", "Madrid"),
            _job("include", "Data Engineer", source="infojobs"),
            _job("exclude", "Senior Python Developer"),
            _job("seen", "Python Developer"),
            _job("sent", "Python Developer"),
            _job("limited", "Python Developer"),
        ]

        stats = main.process_jobs(jobs, self.ctx, send_alerts=True, max_notifs=1)

        self.assertEqual(stats.detected, 6)
        self.assertEqual(stats.discarded_location, 1)
        self.assertEqual(stats.discarded_include, 1)
        self.assertEqual(stats.discarded_exclude, 1)
        self.assertEqual(stats.seen, 1)
        self.assertEqual(stats.eligible, 2)
        self.assertEqual(stats.notification_limit, 1)
        self.assertEqual(stats.paused, 0)
        self.assertEqual(stats.sent, 1)
        self.assertEqual(stats.saved, 1)
        self.assertEqual(stats.delivery_failed, 0)
        self.assertEqual(self.metrics.recorded, ["sent", "limited"])

    @patch("main.enrich_job_description", return_value="Python")
    def test_zero_notification_limit_sends_every_eligible_job(
        self, _enrich: object
    ) -> None:
        jobs = [
            _job("first", "Python Developer"),
            _job("second", "Python Developer"),
        ]

        stats = main.process_jobs(jobs, self.ctx, send_alerts=True, max_notifs=0)

        self.assertEqual(stats.detected, 2)
        self.assertEqual(stats.eligible, 2)
        self.assertEqual(stats.notification_limit, 0)
        self.assertEqual(stats.sent, 2)
        self.assertEqual(stats.saved, 2)
        self.assertEqual(
            self.storage.added, [("linkedin", "first"), ("linkedin", "second")]
        )

    @patch("main.enrich_job_description", return_value="Python")
    def test_paused_jobs_are_counted_without_marking_them_seen(
        self, _enrich: object
    ) -> None:
        main.BOT_PAUSED = True

        stats = main.process_jobs(
            [_job("paused", "Python Developer")], self.ctx, True, 10
        )

        self.assertEqual(stats.detected, 1)
        self.assertEqual(stats.eligible, 1)
        self.assertEqual(stats.paused, 1)
        self.assertEqual(stats.sent, 0)
        self.assertEqual(stats.saved, 0)
        self.assertEqual(self.storage.added, [])

    @patch("main.enrich_job_description", return_value="Python")
    def test_failed_delivery_is_not_marked_as_seen(self, _enrich: object) -> None:
        self.ctx.notifier = _FailingNotifier()

        stats = main.process_jobs(
            [_job("retry", "Python Developer")], self.ctx, True, 10
        )

        self.assertEqual(stats.delivery_failed, 1)
        self.assertEqual(stats.sent, 0)
        self.assertEqual(stats.saved, 0)
        self.assertEqual(self.storage.added, [])

    def test_linkedin_job_outside_its_search_window_is_never_delivered(self) -> None:
        job = _job("too-old", "Python Developer")
        job.features["linkedin_search_urls"] = [
            "https://www.linkedin.com/jobs/search/?f_TPR=r1200&sortBy=DD"
        ]
        job.features["linkedin_recency_evidence"] = [
            {
                "search_url": "https://www.linkedin.com/jobs/search/?f_TPR=r1200&sortBy=DD",
                "posted_text": "Hace 41 minutos",
                "published_at": "",
            }
        ]

        stats = main.process_jobs([job], self.ctx, send_alerts=True, max_notifs=0)

        self.assertEqual(stats.detected, 1)
        self.assertEqual(stats.discarded_time_window, 1)
        self.assertEqual(stats.unverified_time_window, 0)
        self.assertEqual(stats.sent, 0)
        self.assertEqual(self.storage.added, [])


class ManualScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_latest = main.LATEST_JOBS_CACHE
        main.LATEST_JOBS_CACHE = [_job("cached", "Python Developer")]
        self.notifier = _CommandNotifier([(41, "/scan")])
        self.ctx = SimpleNamespace(
            config=SimpleNamespace(telegram_chat_id="123", max_notifs_per_cycle=10),
            notifier=self.notifier,
            logger=logging.getLogger("test-manual-scan"),
            scrape_lock=threading.Lock(),
        )

    def tearDown(self) -> None:
        main.LATEST_JOBS_CACHE = self.old_latest

    def test_scan_uses_the_scheduler_provider_api_and_process_pipeline(self) -> None:
        plain = _PlainProvider()
        linkedin = _LinkedInProvider()
        stats = SimpleNamespace(detected=1, eligible=1, seen=0, saved=1, sent=1)

        with patch("main.process_jobs", return_value=stats) as process:
            next_offset = main.process_telegram_commands(
                self.ctx,
                Path("."),
                None,
                providers_map={"linkedin": linkedin, "infojobs": plain},
            )

        self.assertEqual(next_offset, 42)
        self.assertEqual(plain.calls, 1)
        self.assertEqual(linkedin.calls, [False])
        self.assertEqual(process.call_count, 2)
        self.assertTrue(
            any("mismo flujo y filtros" in text for text in self.notifier.messages)
        )
        self.assertTrue(
            any(
                "evaluaron 2 ofertas y se enviaron 2 nuevas" in text
                for text in self.notifier.messages
            )
        )

    def test_scan_refuses_to_run_while_the_scheduler_holds_the_lock(self) -> None:
        provider = _PlainProvider()
        self.ctx.scrape_lock.acquire()
        try:
            main.process_telegram_commands(
                self.ctx,
                Path("."),
                None,
                providers_map={"infojobs": provider},
            )
        finally:
            self.ctx.scrape_lock.release()

        self.assertEqual(provider.calls, 0)
        self.assertTrue(
            any("no se ejecuta en paralelo" in text for text in self.notifier.messages)
        )

    def test_scan_reports_a_provider_429(self) -> None:
        provider = _RateLimitedProvider()
        stats = SimpleNamespace(detected=0, eligible=0, seen=0, saved=0, sent=0)

        with patch("main.process_jobs", return_value=stats):
            main.process_telegram_commands(
                self.ctx,
                Path("."),
                None,
                providers_map={"infojobs": provider},
            )

        self.assertTrue(
            any(
                "Se recibió 1 respuesta HTTP 429" in text
                for text in self.notifier.messages
            )
        )


class OnDemandCoverageAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_latest = main.LATEST_JOBS_CACHE
        main.LATEST_JOBS_CACHE = [_job("cached", "Python Developer")]
        self.notifier = _CommandNotifier([(41, "/auditoria")])
        self.ctx = SimpleNamespace(
            config=SimpleNamespace(
                telegram_chat_id="123", daily_coverage_dir="./data/daily_coverage"
            ),
            notifier=self.notifier,
            logger=logging.getLogger("test-on-demand-coverage-audit"),
        )

    def tearDown(self) -> None:
        main.LATEST_JOBS_CACHE = self.old_latest

    @patch("main.format_telegram_summary", return_value="audit now")
    @patch(
        "main.write_daily_coverage_report",
        return_value=(Path("data/daily_coverage/2026-08-24.json"), Path("latest.json")),
    )
    @patch(
        "main.build_daily_coverage_report",
        return_value={
            "overall": {"status": "warning", "operational_evidence_score": 84},
            "scheduler": {"cycle_records": 97, "expected_cycles": 104},
        },
    )
    def test_auditoria_generates_a_read_only_report_without_a_scan(
        self, build: object, write: object, summary: object
    ) -> None:
        next_offset = main.process_telegram_commands(self.ctx, Path("."), None)

        self.assertEqual(next_offset, 42)
        self.assertEqual(self.notifier.messages, ["audit now"])
        build.assert_called_once_with(Path("."), self.ctx.config)  # type: ignore[attr-defined]
        write.assert_called_once()  # type: ignore[attr-defined]
        summary.assert_called_once()  # type: ignore[attr-defined]


class RateLimitMetricsTests(unittest.TestCase):
    def test_cycle_rate_limit_metrics_are_append_only_and_provider_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temp_dir = Path(temporary_directory)
            cycle = {
                "cycle_num": 7,
                "http_429": 2,
                "by_provider": {
                    "linkedin": {
                        "http_429": 2,
                        "blocked_reason": "rate_limit_429",
                        "detected": 7,
                        "eligible": 2,
                        "seen": 1,
                        "sent": 1,
                    },
                    "infojobs": {"http_429": 0, "blocked_reason": "", "detected": 3},
                },
            }
            main.append_rate_limit_metrics(
                temp_dir, logging.getLogger("test-rate-limit-metrics"), cycle
            )

            path = temp_dir / "data" / main.RATE_LIMIT_METRICS_FILE
            record = json.loads(path.read_text(encoding="utf-8").strip())
            self.assertEqual(record["cycle_num"], 7)
            self.assertEqual(record["http_429"], 2)
            self.assertIsNotNone(datetime.fromisoformat(record["timestamp"]).tzinfo)
            self.assertEqual(record["providers"]["linkedin"]["http_429"], 2)
            self.assertEqual(record["providers"]["linkedin"]["detected"], 7)
            self.assertEqual(record["providers"]["linkedin"]["sent"], 1)


if __name__ == "__main__":
    unittest.main()
