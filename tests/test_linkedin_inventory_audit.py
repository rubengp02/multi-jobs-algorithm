from __future__ import annotations

import logging
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from extension_bridge import ExtensionBatch, ExtensionSearchBatch
from linkedin_inventory_audit import LinkedInInventoryAuditor
from models import JobItem

SEARCH_URL = "https://www.linkedin.com/jobs/search/?keywords=data&sortBy=DD"


def _job(job_id: str, title: str = "Data Engineer") -> JobItem:
    return JobItem(
        id=job_id,
        title=title,
        company="Acme",
        location="Valencia",
        url=f"https://www.linkedin.com/jobs/view/{job_id}/?tracking=search",
        source="linkedin",
    )


def _batch(
    *,
    bot: tuple[JobItem, ...],
    reference: tuple[JobItem, ...],
    reference_at: datetime | None = None,
    reported_total_complete: bool = True,
    first_page_target_complete: bool = True,
) -> ExtensionBatch:
    now = datetime.now(timezone.utc)
    return ExtensionBatch(
        run_id="inventory-test",
        searches=(
            ExtensionSearchBatch(
                search_url=SEARCH_URL,
                state="complete",
                jobs=bot,
                reference_jobs=reference,
                diagnostics={
                    "reachedEnd": True,
                    "stableRounds": 3,
                    "reportedTotalComplete": reported_total_complete,
                    "firstPageTargetComplete": first_page_target_complete,
                    "productionCapturedAt": now.isoformat(),
                    "referenceCapturedAt": (reference_at or now).isoformat(),
                },
            ),
        ),
    )


class LinkedInInventoryAuditTests(unittest.TestCase):
    def test_matching_complete_captures_are_coverage_correct_without_seen_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            seen = root / "seen_jobs.txt"
            seen.write_text("linkedin:already-seen\n", encoding="utf-8")
            original_seen = seen.read_bytes()
            auditor = LinkedInInventoryAuditor(
                root, logging.getLogger("test"), [SEARCH_URL]
            )

            result = auditor.audit(
                _batch(bot=(_job("10000001"),), reference=(_job("10000001"),))
            )

            self.assertTrue(result.valid)
            self.assertTrue(result.coverage_correct)
            self.assertEqual(result.matches, 1)
            self.assertEqual(result.eligible_absences, 0)
            self.assertEqual(seen.read_bytes(), original_seen)
            self.assertTrue(
                (root / "linkedin_inventory_audit" / "latest.json").exists()
            )

    def test_eligible_reference_absence_invalidates_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            auditor = LinkedInInventoryAuditor(
                Path(temporary_directory), logging.getLogger("test"), [SEARCH_URL]
            )
            result = auditor.audit(
                _batch(
                    bot=(_job("10000001"),),
                    reference=(
                        _job("10000001"),
                        _job("10000002", "AI Engineer"),
                    ),
                )
            )

            self.assertTrue(result.valid)
            self.assertFalse(result.coverage_correct)
            self.assertEqual(result.only_reference, 1)
            self.assertEqual(result.eligible_absences, 1)

    def test_distant_or_partial_capture_cannot_claim_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            auditor = LinkedInInventoryAuditor(
                Path(temporary_directory), logging.getLogger("test"), [SEARCH_URL]
            )
            old = datetime.now(timezone.utc) - timedelta(seconds=121)
            result = auditor.audit(
                _batch(
                    bot=(_job("10000001"),),
                    reference=(_job("10000001"),),
                    reference_at=old,
                )
            )

            self.assertFalse(result.valid)
            self.assertFalse(result.coverage_correct)
            self.assertIn(
                "captures_more_than_120_seconds_apart", result.report["reason"]
            )

    def test_first_page_complete_does_not_require_every_announced_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            auditor = LinkedInInventoryAuditor(
                Path(temporary_directory), logging.getLogger("test"), [SEARCH_URL]
            )
            result = auditor.audit(
                _batch(
                    bot=(_job("10000001"),),
                    reference=(_job("10000001"),),
                    reported_total_complete=False,
                )
            )

            self.assertTrue(result.valid)
            self.assertTrue(result.coverage_correct)

    def test_incomplete_first_page_cannot_claim_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            auditor = LinkedInInventoryAuditor(
                Path(temporary_directory), logging.getLogger("test"), [SEARCH_URL]
            )
            result = auditor.audit(
                _batch(
                    bot=(_job("10000001"),),
                    reference=(_job("10000001"),),
                    first_page_target_complete=False,
                )
            )

            self.assertFalse(result.valid)
            self.assertFalse(result.coverage_correct)
            self.assertIn("first_page_target_not_loaded", result.report["reason"])

    def test_irrelevant_reference_absence_is_not_an_eligible_coverage_loss(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            auditor = LinkedInInventoryAuditor(
                Path(temporary_directory),
                logging.getLogger("test"),
                [SEARCH_URL],
                is_eligible=lambda _job: False,
            )
            result = auditor.audit(
                _batch(bot=(), reference=(_job("10000001", "Payroll Specialist"),))
            )

            self.assertTrue(result.valid)
            self.assertTrue(result.coverage_correct)
            self.assertEqual(result.only_reference, 1)
            self.assertEqual(result.eligible_absences, 0)


if __name__ == "__main__":
    unittest.main()
