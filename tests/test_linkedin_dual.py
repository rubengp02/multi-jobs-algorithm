from __future__ import annotations

import logging
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import main
from extension_bridge import ExtensionBatch, ExtensionSearchBatch
from linkedin_dual import LinkedInDualCoordinator
from models import JobItem
from providers.linkedin import LinkedInFetchResult

SEARCH_URL = "https://www.linkedin.com/jobs/search/?keywords=data&sortBy=DD"
REMOTE_SEARCH_URL = f"{SEARCH_URL}&f_WT=2"


def _job(job_id: str, title: str = "Data Engineer") -> JobItem:
    return JobItem(
        id=job_id,
        title=title,
        company="Acme",
        location="Valencia",
        url=f"https://www.linkedin.com/jobs/view/{job_id}/?tracking=search",
        source="linkedin",
        posted_within_1h=True,
    )


def _snapshot(*jobs: JobItem, state: str = "ok") -> LinkedInFetchResult:
    return LinkedInFetchResult(
        search_url=SEARCH_URL,
        endpoint_url="https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=data&sortBy=DD",
        state=state,  # type: ignore[arg-type]
        http_status=200,
        jobs=jobs,
        raw_cards=len(jobs),
        parsed_cards=len(jobs),
        incomplete_cards=0,
    )


class FakeProvider:
    def __init__(self, results: list[LinkedInFetchResult]) -> None:
        self.config = SimpleNamespace(linkedin_extension_refresh_seconds=900)
        self.results = results
        self.calls = 0

    def configured_urls(self) -> list[str]:
        return [SEARCH_URL]

    def fetch_snapshots(self) -> list[LinkedInFetchResult]:
        self.calls += 1
        return self.results


class LinkedInDualCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.deliveries: list[tuple[list[JobItem], bool, bool, int, str]] = []

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _deliver(
        self,
        jobs: list[JobItem],
        send_alerts: bool,
        first_cycle: bool,
        duplicates: int,
        run_id: str,
    ) -> dict[str, int]:
        self.deliveries.append((jobs, send_alerts, first_cycle, duplicates, run_id))
        return {
            "detected": len(jobs),
            "eligible": len(jobs),
            "saved": len(jobs),
            "sent": len(jobs),
        }

    def _coordinator(
        self, results: list[LinkedInFetchResult]
    ) -> LinkedInDualCoordinator:
        return LinkedInDualCoordinator(
            FakeProvider(results),  # type: ignore[arg-type]
            Path(self.temp_dir.name),
            logging.getLogger("test-linkedin-dual"),
            self._deliver,
        )

    def test_complete_extension_is_delivered_once_without_guest_api_probe(self) -> None:
        coordinator = self._coordinator([_snapshot(_job("100001"), _job("100003"))])
        batch = ExtensionBatch(
            run_id="dual-1",
            searches=(
                ExtensionSearchBatch(
                    search_url=SEARCH_URL,
                    state="complete",
                    diagnostics={"reachedEnd": True, "stableRounds": 3},
                    jobs=(_job("100001"), _job("100002")),
                    reference_jobs=(_job("100001"), _job("100002")),
                ),
            ),
        )

        result = coordinator.ingest_extension(
            batch, send_alerts=True, first_cycle=False
        )

        self.assertEqual(result["unique_jobs"], 2)
        self.assertEqual(result["matches"], 2)
        self.assertEqual(result["only_production"], 0)
        self.assertEqual(result["only_reference"], 0)
        self.assertEqual(len(self.deliveries), 1)
        self.assertEqual(
            sorted(job.id for job in self.deliveries[0][0]),
            ["100001", "100002"],
        )
        self.assertEqual(self.deliveries[0][3], 0)
        self.assertEqual(self.deliveries[0][4], "dual-1")
        self.assertEqual(coordinator.provider.calls, 0)

        report_lines = (
            (Path(self.temp_dir.name) / "linkedin_runs.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        self.assertEqual(len(report_lines), 1)
        self.assertIn('"run_id": "dual-1"', report_lines[0])
        self.assertFalse(coordinator.status()["fallback_active"])

    def test_partial_extension_keeps_fallback_degraded_until_full_recovery(
        self,
    ) -> None:
        coordinator = self._coordinator([_snapshot(_job("100001"))])
        partial = ExtensionBatch(
            run_id="partial",
            searches=(
                ExtensionSearchBatch(
                    search_url=SEARCH_URL,
                    state="partial",
                    diagnostics={"reachedEnd": False, "stableRounds": 0},
                    jobs=(_job("100001"),),
                ),
            ),
        )
        coordinator.fallback_active = True

        result = coordinator.ingest_extension(
            partial, send_alerts=True, first_cycle=False
        )

        self.assertTrue(result["partial"])
        self.assertTrue(result["fallback_active"])
        self.assertIsNone(coordinator.last_extension_complete_at)

    def test_first_page_complete_batch_does_not_require_all_announced_results(
        self,
    ) -> None:
        coordinator = self._coordinator([_snapshot(_job("100001"))])
        batch = ExtensionBatch(
            run_id="reported-total-gap",
            searches=(
                ExtensionSearchBatch(
                    search_url=SEARCH_URL,
                    state="complete",
                    diagnostics={
                        "reachedEnd": True,
                        "stableRounds": 3,
                        "reportedTotalComplete": False,
                        "firstPageTargetComplete": True,
                    },
                    jobs=(_job("100001"),),
                    reference_jobs=(_job("100001"),),
                ),
            ),
        )

        result = coordinator.ingest_extension(
            batch, send_alerts=True, first_cycle=False
        )

        self.assertFalse(result["partial"])
        self.assertIsNotNone(coordinator.last_extension_complete_at)

    def test_full_extension_is_not_degraded_by_a_guest_api_that_was_not_queried(
        self,
    ) -> None:
        coordinator = self._coordinator([_snapshot(_job("100004"), state="partial")])
        batch = ExtensionBatch(
            run_id="api-partial",
            searches=(
                ExtensionSearchBatch(
                    search_url=SEARCH_URL,
                    state="complete",
                    diagnostics={"reachedEnd": True, "stableRounds": 3},
                    jobs=(_job("100004"),),
                    reference_jobs=(_job("100004"),),
                ),
            ),
        )

        result = coordinator.ingest_extension(
            batch, send_alerts=True, first_cycle=False
        )

        self.assertFalse(result["partial"])
        self.assertFalse(result["fallback_active"])
        self.assertFalse(coordinator.status()["last_api_ok"])
        self.assertEqual(coordinator.provider.calls, 0)
        self.assertEqual(
            coordinator.status()["last_channel_states"][0]["api"], "not_queried"
        )

    def test_api_fallback_starts_only_after_two_missing_intervals(self) -> None:
        coordinator = self._coordinator([_snapshot(_job("100008"))])
        coordinator.started_at = datetime.now(timezone.utc) - timedelta(seconds=1801)

        result = coordinator.fallback_if_due(send_alerts=True, first_cycle=False)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["fallback_active"])
        self.assertEqual(result["sent"], 1)
        self.assertEqual(len(self.deliveries), 1)
        self.assertIsNone(
            coordinator.fallback_if_due(send_alerts=True, first_cycle=False)
        )

    def test_linkedin_search_candidates_skip_generic_include_filters(self) -> None:
        config = SimpleNamespace(
            include_words=["python"], exclude_words=["tecnico de nominas"]
        )
        job = _job("100088", title="Platform Engineer")

        self.assertIsNone(main.job_filter_reason(job, config))
        self.assertIsNone(
            main.job_filter_reason(job, config, "Python tecnico de nominas")
        )
        payroll_title = JobItem(**{**job.__dict__, "title": "Tecnico de nominas"})
        self.assertEqual(main.job_filter_reason(payroll_title, config), "exclude")
        external = JobItem(**{**job.__dict__, "source": "infojobs"})
        self.assertEqual(main.job_filter_reason(external, config), "include")

    def test_missing_linkedin_location_uses_only_the_explicit_remote_search_scope(
        self,
    ) -> None:
        config = SimpleNamespace(include_words=[], exclude_words=[])
        remote_card = JobItem(
            id="100089",
            title="Data Engineer",
            company="Acme",
            location="Ubicaci\u00f3n no indicada",
            url="https://www.linkedin.com/jobs/view/100089",
            source="linkedin",
            features={"extension_card": {"searchUrl": REMOTE_SEARCH_URL}},
        )
        non_remote_card = JobItem(
            **{
                **remote_card.__dict__,
                "id": "100090",
                "features": {"extension_card": {"searchUrl": SEARCH_URL}},
            }
        )

        self.assertIsNone(main.job_filter_reason(remote_card, config))
        self.assertEqual(main.job_filter_reason(non_remote_card, config), "location")

        remote_hq_card = JobItem(
            **{
                **remote_card.__dict__,
                "id": "100091",
                "location": "New York, Estados Unidos",
            }
        )
        self.assertIsNone(main.job_filter_reason(remote_hq_card, config))

    def test_recovery_accepts_relative_linkedin_dates_up_to_48_hours(self) -> None:
        now = datetime.now(timezone.utc)
        within_window = _job("100099")
        within_window = JobItem(
            **{
                **within_window.__dict__,
                "posted_within_1h": False,
                "published_at": "hace 47 horas",
            }
        )
        outside_window = _job("100100")
        outside_window = JobItem(
            **{
                **outside_window.__dict__,
                "posted_within_1h": False,
                "published_at": "3 days ago",
            }
        )

        self.assertTrue(
            LinkedInDualCoordinator._published_within_48h(within_window, now)
        )
        self.assertFalse(
            LinkedInDualCoordinator._published_within_48h(outside_window, now)
        )


if __name__ == "__main__":
    unittest.main()
