from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from main import load_all_recent_jobs_from_disk


class RecentMetricsTests(unittest.TestCase):
    def test_recent_loader_reads_tail_first_and_enforces_age_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            path = root / "data" / "metrics_jobs.jsonl"
            path.parent.mkdir(parents=True)
            now = time.time()
            rows = [
                {"timestamp": now - 3 * 86400, "id": "old", "source": "linkedin"},
                {
                    "timestamp": now,
                    "id": "first",
                    "source": "linkedin",
                    "title": "First",
                },
                {"timestamp": now, "id": "last", "source": "infojobs", "title": "Last"},
                {
                    "timestamp": now,
                    "id": "first",
                    "source": "linkedin",
                    "title": "Updated",
                },
            ]
            path.write_text(
                "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
            )

            jobs = load_all_recent_jobs_from_disk(root, max_days=2)

            self.assertEqual(["first", "last"], [job.id for job in jobs])
            self.assertEqual("Updated", jobs[0].title)
