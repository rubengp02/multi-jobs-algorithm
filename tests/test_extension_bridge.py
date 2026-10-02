from __future__ import annotations

import json
import logging
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import main
from extension_bridge import (
    ExtensionBatch,
    ExtensionBridge,
    _job_from_payload,
    batch_from_payload,
)

SEARCH_URL = (
    "https://www.linkedin.com/jobs/search/?keywords=data&sortBy=DD&f_TPR=r86400"
)


def _complete_payload() -> dict[str, object]:
    return {
        "runId": "run-42",
        "searches": [
            {
                "url": SEARCH_URL,
                "state": "complete",
                "diagnostics": {
                    "reachedEnd": True,
                    "stableRounds": 3,
                    "scrollRounds": 7,
                },
                "jobs": [
                    {
                        "id": "42",
                        "title": "Data Engineer",
                        "company": "Acme",
                        "location": "Valencia",
                        "url": "https://www.linkedin.com/jobs/view/42/?ref=search",
                        "publishedAt": "2026-08-22T12:00:00Z",
                    }
                ],
            }
        ],
    }


class ExtensionBridgeTests(unittest.TestCase):
    def test_extension_mode_does_not_create_the_direct_linkedin_provider(self) -> None:
        config = SimpleNamespace(
            enabled_providers=["linkedin"], linkedin_extension_enabled=True
        )
        with patch("main.LinkedInProvider") as linkedin_provider:
            providers = main.build_providers(
                config, logging.getLogger("test-extension-bridge")
            )
        self.assertEqual(providers, {})
        linkedin_provider.assert_not_called()

    def test_payload_normalization_uses_canonical_linkedin_identity(self) -> None:
        job = _job_from_payload(
            {
                "id": "unexpected-long-id",
                "title": "Ingeniero de datos",
                "company": "Acme",
                "location": "Valencia",
                "url": "https://www.linkedin.com/jobs/view/123456/?tracking=anything",
                "posted": "Hace 30 min",
            }
        )
        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job.id, "123456")
        self.assertEqual(job.url, "https://www.linkedin.com/jobs/view/123456")
        self.assertIn("unexpected-long-id", job.aliases)
        self.assertTrue(job.posted_within_1h)
        self.assertIsNone(
            _job_from_payload(
                {"id": "missing", "title": "", "url": "https://example.test"}
            )
        )

    def test_payload_preserves_extension_card_metadata_for_diagnostics(self) -> None:
        job = _job_from_payload(
            {
                "id": "123456",
                "title": "Data Engineer",
                "company": "Acme",
                "location": "Espana (En remoto)",
                "url": "https://www.linkedin.com/jobs/view/123456/",
                "metadata": {"locationSource": "visible_line"},
            }
        )

        assert job is not None
        self.assertEqual(
            job.features["extension_card"]["locationSource"], "visible_line"
        )

    def test_batch_attaches_its_exact_search_url_to_cards(self) -> None:
        batch = batch_from_payload(_complete_payload())

        self.assertIsNotNone(batch)
        assert batch is not None
        card = batch.searches[0].jobs[0].features["extension_card"]
        self.assertEqual(card["searchUrl"], SEARCH_URL)

    def test_batch_requires_stable_completed_scroll(self) -> None:
        batch = batch_from_payload(_complete_payload())
        self.assertIsNotNone(batch)
        assert batch is not None
        self.assertEqual(batch.run_id, "run-42")
        self.assertTrue(batch.searches[0].complete)

        partial_payload = _complete_payload()
        searches = partial_payload["searches"]
        assert isinstance(searches, list)
        searches[0]["diagnostics"] = {"reachedEnd": True, "stableRounds": 2}
        partial = batch_from_payload(partial_payload)
        assert partial is not None
        self.assertFalse(partial.searches[0].complete)

    def test_batch_accepts_a_reached_first_page_target_without_end_scroll(self) -> None:
        payload = _complete_payload()
        searches = payload["searches"]
        assert isinstance(searches, list)
        searches[0]["diagnostics"] = {
            "firstPageTargetReached": True,
            "firstPageTargetComplete": True,
            "reachedEnd": False,
            "stableRounds": 0,
        }

        batch = batch_from_payload(payload)

        self.assertIsNotNone(batch)
        assert batch is not None
        self.assertTrue(batch.searches[0].complete)

    def test_health_settings_and_ingest_v2(self) -> None:
        received: list[ExtensionBatch] = []
        ingested = threading.Event()
        config = SimpleNamespace(
            linkedin_extension_enabled=True,
            linkedin_extension_host="127.0.0.1",
            linkedin_extension_port=0,
            linkedin_urls=[SEARCH_URL],
            linkedin_url="",
            linkedin_extension_refresh_seconds=900,
            linkedin_max_jobs=0,
            linkedin_time_windows_seconds=(1200, 3600),
            linkedin_inter_search_min_seconds=3.0,
            linkedin_inter_search_max_seconds=6.0,
        )

        def ingest(batch: ExtensionBatch) -> dict[str, int]:
            received.append(batch)
            ingested.set()
            return {"detected": 1, "saved": 1, "sent": 1}

        bridge = ExtensionBridge(
            config, logging.getLogger("test-extension-bridge"), ingest
        )
        bridge.start()
        base_url = f"http://127.0.0.1:{bridge.port}"
        try:
            with urlopen(f"{base_url}/health") as response:
                self.assertEqual(json.loads(response.read())["protocol"], 2)
            with urlopen(f"{base_url}/settings") as response:
                settings = json.loads(response.read())
                self.assertEqual(settings["maxJobs"], 25)
                self.assertEqual(
                    settings["searchUrls"],
                    [
                        SEARCH_URL.replace("f_TPR=r86400", "f_TPR=r1200"),
                        SEARCH_URL.replace("f_TPR=r86400", "f_TPR=r3600"),
                    ],
                )
                self.assertEqual(settings["refreshSeconds"], 900)
                self.assertEqual(settings["interSearchDelayMinSeconds"], 3.0)
                self.assertEqual(settings["interSearchDelayMaxSeconds"], 6.0)

            body = json.dumps(_complete_payload()).encode()
            request = Request(
                f"{base_url}/ingest",
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urlopen(request) as response:
                reply = json.loads(response.read())
            self.assertTrue(reply["ok"])
            self.assertTrue(reply["accepted"])
            self.assertEqual(reply["run_id"], "run-42")
            self.assertTrue(ingested.wait(timeout=2))
            self.assertEqual(len(received), 1)
            self.assertTrue(received[0].searches[0].complete)

            with urlopen(request) as response:
                duplicate = json.loads(response.read())
            self.assertTrue(duplicate["duplicate"])
            self.assertEqual(len(received), 1)

            with self.assertRaises(HTTPError) as error:
                urlopen(f"{base_url}/unknown")
            self.assertEqual(error.exception.code, 404)
        finally:
            bridge.stop()


if __name__ == "__main__":
    unittest.main()
