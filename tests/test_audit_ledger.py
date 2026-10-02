import json
import logging
import tempfile
import unittest
from pathlib import Path

from audit_ledger import JobAuditLedger
from models import JobItem


class JobAuditLedgerTests(unittest.TestCase):
    def test_records_only_hashed_identity_and_terminal_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_dir = Path(temporary_directory) / "data"
            job = JobItem(
                id="42",
                title="Private title",
                company="Private company",
                location="Valencia",
                url="https://example.test/jobs/42?volatile=value",
                source="infojobs",
                description="Private description that must not enter the ledger.",
            )

            JobAuditLedger(data_dir, logging.getLogger("test")).record_jobs(
                [job], {0: "sent"}, origin="scheduler", run_id="cycle-1"
            )

            path = next((data_dir / "job_audit").glob("*.jsonl"))
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(record["detected"], 1)
            self.assertEqual(record["terminal"], 1)
            self.assertTrue(record["complete"])
            self.assertEqual(record["jobs"][0]["outcome"], "sent")
            self.assertEqual(len(record["jobs"][0]["key"]), 24)
            rendered = json.dumps(record)
            self.assertNotIn(job.title, rendered)
            self.assertNotIn(job.description, rendered)
            self.assertNotIn(job.url, rendered)

    def test_missing_outcome_is_explicitly_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            ledger = JobAuditLedger(
                Path(temporary_directory) / "data", logging.getLogger("test")
            )
            job = JobItem(
                "42", "Title", "Company", "Spain", "https://example.test/42", "infojobs"
            )

            ledger.record_jobs([job], {}, origin="scheduler")

            path = next(
                (Path(temporary_directory) / "data" / "job_audit").glob("*.jsonl")
            )
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(record["complete"])
            self.assertEqual(record["unaccounted"], 1)

    def test_dynamic_relevance_rejection_is_a_terminal_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_dir = Path(temporary_directory) / "data"
            jobs = [
                JobItem(
                    "one",
                    "One",
                    "Company",
                    "Spain",
                    "https://example.test/one",
                    "linkedin",
                ),
                JobItem(
                    "two",
                    "Two",
                    "Company",
                    "Spain",
                    "https://example.test/two",
                    "linkedin",
                ),
            ]

            JobAuditLedger(data_dir, logging.getLogger("test")).record_jobs(
                jobs,
                {
                    0: "discarded_relevance:sin_evidencia_digital",
                    1: "discarded_time_window",
                },
                origin="scheduler",
            )

            path = next((data_dir / "job_audit").glob("*.jsonl"))
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(record["complete"])
            self.assertEqual(record["terminal"], 2)
