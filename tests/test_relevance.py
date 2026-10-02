from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from models import JobItem
from relevance import evaluate_relevance, relevance_fingerprint
from storage import RelevanceDecisionCache


def _job(title: str, description: str = "", location: str = "Valencia") -> JobItem:
    return JobItem(
        id="relevance-test",
        title=title,
        company="Example",
        location=location,
        url="https://example.test/jobs/relevance-test",
        source="linkedin",
        description=description,
    )


class RelevanceDecisionTests(unittest.TestCase):
    def test_target_profiles_are_accepted_with_explicit_digital_evidence(self) -> None:
        cases = (
            _job("AI Engineer"),
            _job("Data Engineer"),
            _job("Python API Developer"),
            _job(
                "Ingeniero de mantenimiento predictivo",
                "Desarrollar modelos Python con datos IoT para mantenimiento predictivo.",
            ),
            _job(
                "Programador PLC",
                "Proyecto de vision artificial con Python y datos industriales.",
            ),
        )

        for job in cases:
            with self.subTest(title=job.title):
                decision = evaluate_relevance(job)
                self.assertEqual(decision.status, "accepted")
                self.assertGreaterEqual(decision.score, 70)
                self.assertTrue(decision.positive_evidence)

    def test_borderline_analytics_and_automation_are_warnings(self) -> None:
        for title in ("Analista Power BI", "Automation Analyst RPA"):
            with self.subTest(title=title):
                decision = evaluate_relevance(_job(title))
                self.assertEqual(decision.status, "warning")
                self.assertGreaterEqual(decision.score, 50)
                self.assertLess(decision.score, 70)

    def test_unrelated_families_are_never_promoted_by_location_or_salary(self) -> None:
        cases = {
            "Tecnico de nominas": "rrhh_nominas",
            "Delineante AutoCAD BIM": "cad_bim",
            "Disenador grafico": "diseno_grafico",
            "Programador PLC Siemens": "plc_scada_puro",
            "Tecnico de mantenimiento mecanico": "mecanica_fabricacion",
        }
        for title, family in cases.items():
            with self.subTest(title=title):
                decision = evaluate_relevance(
                    _job(
                        title, "Trabajo remoto, salario competitivo.", "Remoto, Espana"
                    )
                )
                self.assertEqual(decision.status, "rejected")
                self.assertEqual(decision.family, family)
                self.assertLess(decision.score, 50)

    def test_linkedin_generic_software_is_retained_until_description_evidence(
        self,
    ) -> None:
        job = _job("Software Engineer")
        initial = evaluate_relevance(job)
        enriched = evaluate_relevance(job, "Crear APIs REST con Python y FastAPI.")

        self.assertEqual(initial.status, "warning")
        self.assertEqual(initial.family, "linkedin_search_candidate")
        self.assertTrue(initial.needs_description)
        self.assertEqual(enriched.status, "accepted")
        self.assertGreaterEqual(enriched.score, 70)

    def test_non_linkedin_generic_software_still_requires_profile_evidence(
        self,
    ) -> None:
        job = JobItem(**{**_job("Software Engineer").__dict__, "source": "infojobs"})

        decision = evaluate_relevance(job)

        self.assertEqual(decision.status, "rejected")
        self.assertEqual(decision.family, "software_sin_stack_objetivo")

    def test_decision_cache_serializes_concurrent_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache_path = Path(temporary) / "relevance_decisions.json"
            cache = RelevanceDecisionCache(cache_path, max_items=500)
            start = threading.Event()
            failures: list[Exception] = []

            def write_many(prefix: str) -> None:
                try:
                    start.wait()
                    for index in range(100):
                        cache.put(
                            "linkedin",
                            f"{prefix}-{index}",
                            f"fingerprint-{index}",
                            {"status": "rejected"},
                        )
                except Exception as error:  # noqa: BLE001 - surfaced by the test after joining.
                    failures.append(error)

            threads = [
                threading.Thread(target=write_many, args=(str(index),))
                for index in range(3)
            ]
            for thread in threads:
                thread.start()
            start.set()
            for thread in threads:
                thread.join()

            self.assertEqual(failures, [])
            self.assertEqual(
                len(json.loads(cache_path.read_text(encoding="utf-8"))), 300
            )


class RelevanceDecisionCacheTests(unittest.TestCase):
    def test_cache_is_bounded_and_evicts_stale_or_changed_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "relevance.json"
            cache = RelevanceDecisionCache(path, max_items=2, retention_days=1)
            decision = evaluate_relevance(_job("Data Engineer")).as_dict()
            for job_id in ("one", "two", "three"):
                cache.put("linkedin", job_id, f"fingerprint-{job_id}", decision)

            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(persisted), 2)
            self.assertIsNone(cache.get("linkedin", "one", "fingerprint-one"))
            self.assertIsNotNone(cache.get("linkedin", "three", "fingerprint-three"))
            self.assertIsNone(cache.get("linkedin", "three", "changed"))

            cache._entries["linkedin:three"]["timestamp"] = "2000-01-01T00:00:00+00:00"  # type: ignore[attr-defined]
            cache.purge()
            self.assertIsNone(cache.get("linkedin", "three", "fingerprint-three"))

    def test_content_fingerprint_changes_when_the_description_changes(self) -> None:
        base = _job("Software Engineer")
        changed = _job("Software Engineer", "Python FastAPI")
        self.assertNotEqual(relevance_fingerprint(base), relevance_fingerprint(changed))


if __name__ == "__main__":
    unittest.main()
