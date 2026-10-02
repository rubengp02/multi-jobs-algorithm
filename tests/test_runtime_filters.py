from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import main
from models import JobItem


class RuntimeFilterMigrationTests(unittest.TestCase):
    def test_legacy_broad_exclusions_are_preserved_but_deactivated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            path = base_dir / "data" / main.RUNTIME_FILTERS_FILE
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps({"exclude_words": ["data", "senior", "data"]}),
                encoding="utf-8",
            )

            active = main.load_runtime_exclude_words(
                base_dir, ["fallback"], logging.getLogger("test-runtime-filters")
            )

            self.assertEqual(active, [])
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["filter_policy_version"], 2)
            self.assertEqual(payload["exclude_words"], [])
            self.assertEqual(
                payload["softened_legacy_exclude_words"], ["data", "senior"]
            )

    def test_new_precise_exclusions_remain_active(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)

            main.save_runtime_exclude_words(
                base_dir,
                ["nominas", "nominas"],
                logging.getLogger("test-runtime-filters"),
            )

            active = main.load_runtime_exclude_words(
                base_dir, [], logging.getLogger("test-runtime-filters")
            )
            self.assertEqual(active, ["nominas"])

    def test_current_broad_exclusion_is_deactivated_on_load(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            path = base_dir / "data" / main.RUNTIME_FILTERS_FILE
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "filter_policy_version": main.RUNTIME_FILTER_POLICY_VERSION,
                        "exclude_words": ["data", "tecnico de nominas"],
                    }
                ),
                encoding="utf-8",
            )

            active = main.load_runtime_exclude_words(
                base_dir, [], logging.getLogger("test-runtime-filters")
            )

            self.assertEqual(active, ["tecnico de nominas"])
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["softened_legacy_exclude_words"], ["data"])

    def test_save_keeps_broad_additions_in_history_not_the_blacklist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)

            main.save_runtime_exclude_words(
                base_dir,
                ["data", "tecnico de nominas"],
                logging.getLogger("test-runtime-filters"),
            )

            payload = json.loads(
                (base_dir / "data" / main.RUNTIME_FILTERS_FILE).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(payload["exclude_words"], ["tecnico de nominas"])
            self.assertEqual(payload["softened_legacy_exclude_words"], ["data"])

    def test_legacy_data_exclusion_does_not_hide_linkedin_data_engineer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory)
            path = base_dir / "data" / main.RUNTIME_FILTERS_FILE
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"exclude_words": ["data"]}), encoding="utf-8")
            config = SimpleNamespace(
                include_words=["python"],
                exclude_words=main.load_runtime_exclude_words(
                    base_dir, [], logging.getLogger("test-runtime-filters")
                ),
                locations=[],
            )
            job = JobItem(
                id="4460306051",
                title="Data Engineer Fabric",
                company="Logicalis Spain",
                location="Espana (En remoto)",
                url="https://www.linkedin.com/jobs/view/4460306051/",
                source="linkedin",
            )

            self.assertIsNone(main.job_filter_reason(job, config))


if __name__ == "__main__":
    unittest.main()
