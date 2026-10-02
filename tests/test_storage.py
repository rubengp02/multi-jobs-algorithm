from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from storage import SeenStorage


class SeenStorageTests(unittest.TestCase):
    def test_load_keeps_legacy_entries_and_deduplicates_while_streaming(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "seen_jobs.txt"
            path.write_text(
                "linkedin:one|100\nlegacy-entry\nlinkedin:one|200\ninfojobs:two|bad\n",
                encoding="utf-8",
            )

            storage = SeenStorage(path)

            self.assertEqual(3, storage.count())
            self.assertTrue(storage.is_seen("linkedin", "one"))
            self.assertTrue(storage.is_seen("infojobs", "two"))
            self.assertIn("legacy-entry", storage._seen)
