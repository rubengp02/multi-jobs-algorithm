import logging
import unittest
from types import SimpleNamespace

from providers.accessiway import AccessiwayProvider


class AccessiwayProviderTests(unittest.TestCase):
    def test_extracts_every_unique_public_opening_with_card_metadata(self) -> None:
        html = """
        <ul class="company-links">
          <li><div>Backend Developer Technology · Turin-Italy · Fully Remote
            <a href="/jobs/101-backend-developer">Backend Developer</a>
          </div></li>
          <li><div>Fullstack Developer Technology · Multiple locations · Fully Remote
            <a href="https://accessiway.teamtailor.com/jobs/102-fullstack-developer">Fullstack Developer</a>
          </div></li>
          <li><div>Backend Developer Technology · Turin-Italy · Fully Remote
            <a href="/jobs/101-backend-developer">Backend Developer</a>
          </div></li>
        </ul>
        """
        config = SimpleNamespace(timeout_seconds=5, accessiway_max_results=10)
        provider = AccessiwayProvider(config, logging.getLogger("test-accessiway"))
        provider.session.get = lambda *_args, **_kwargs: SimpleNamespace(
            status_code=200,
            text=html,
            url=provider.ALL_JOBS_URL,
        )

        jobs = provider.fetch_jobs()

        self.assertEqual([job.id for job in jobs], ["accessiway_101", "accessiway_102"])
        self.assertEqual(jobs[0].location, "Turin-Italy · Fully Remote")
        self.assertEqual(jobs[1].location, "Multiple locations · Fully Remote")
        self.assertTrue(all(job.company == "Accessiway" for job in jobs))


if __name__ == "__main__":
    unittest.main()
