import json
import logging
import unittest
from types import SimpleNamespace

from providers.infojobs import InfoJobsProvider


class InfoJobsEmbeddedPayloadTests(unittest.TestCase):
    def test_fetch_jobs_uses_embedded_payload_and_preserves_description(self) -> None:
        payload = {
            "offers": [
                {
                    "code": "offer-123",
                    "title": "Python Developer",
                    "companyName": "Example Corp",
                    "city": "Valencia",
                    "description": "Desarrollo de APIs con FastAPI y PostgreSQL.",
                    "link": "/of-ioffer-123",
                    "teleworking": "Teletrabajo",
                    "publishedAt": "2026-08-20T08:00:00+00:00",
                }
            ]
        }
        html = (
            "<script>window.__INITIAL_PROPS__ = JSON.parse("
            + json.dumps(json.dumps(payload))
            + ");</script>"
        )
        config = SimpleNamespace(
            infojobs_url="https://example.test/search",
            infojobs_max_results=10,
            timeout_seconds=5,
        )
        provider = InfoJobsProvider(config, logging.getLogger("test-infojobs"))
        provider.session.get = lambda *_args, **_kwargs: SimpleNamespace(
            status_code=200,
            text=html,
        )

        jobs = provider.fetch_jobs(startup_deep_scan=True)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].id, "offer-123")
        self.assertIn("FastAPI", jobs[0].description)
        self.assertIn("100% Remoto", jobs[0].description)
        self.assertTrue(jobs[0].url.startswith("https://www.infojobs.net/"))


if __name__ == "__main__":
    unittest.main()
