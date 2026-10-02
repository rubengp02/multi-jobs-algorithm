import logging
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from providers.linkedin import LinkedInProvider
from providers.linkedin_common import expanded_search_urls

SEARCH_URL = (
    "https://www.linkedin.com/jobs/search/?currentJobId=4423666089&distance=25"
    "&f_TPR=r1200&keywords=ingeniero%20de%20inteligencia%20artificial&sortBy=DD"
)


def _config(max_jobs: int = 25) -> SimpleNamespace:
    return SimpleNamespace(
        linkedin_urls=[SEARCH_URL],
        linkedin_url="",
        linkedin_max_jobs=max_jobs,
        timeout_seconds=5,
        poll_seconds=900,
        linkedin_time_windows_seconds=(1200,),
        linkedin_inter_search_min_seconds=3.0,
        linkedin_inter_search_max_seconds=6.0,
    )


def _card(job_id: int, title: str = "Python Developer") -> str:
    return f"""<div class="base-card" data-entity-urn="urn:li:jobPosting:{job_id}">
      <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/{job_id}/?tracking=abc"></a>
      <h3 class="base-search-card__title">{title}</h3>
      <h4 class="base-search-card__subtitle">Example</h4>
      <span class="job-search-card__location">Valencia</span>
      <time datetime="2026-08-22T12:00:00Z">hace 1 hora</time>
    </div>"""


class LinkedInCycleLimitsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = LinkedInProvider(
            _config(), logging.getLogger("test-linkedin-cycle-limits")
        )

    def test_configured_url_and_guest_endpoint_preserve_original_query(self) -> None:
        self.assertEqual(self.provider.configured_urls(), [SEARCH_URL])
        endpoint = self.provider._guest_endpoint(SEARCH_URL)
        self.assertIn("f_TPR=r1200", endpoint)
        self.assertIn("sortBy=DD", endpoint)
        self.assertNotIn("start=", endpoint)

    def test_expands_each_base_url_from_twenty_minutes_to_one_hour(self) -> None:
        self.provider.config.linkedin_time_windows_seconds = (1200, 3600)

        self.assertEqual(
            self.provider.configured_urls(),
            [
                SEARCH_URL,
                SEARCH_URL.replace("f_TPR=r1200", "f_TPR=r3600"),
            ],
        )

    def test_time_windows_only_replace_the_temporal_filter(self) -> None:
        base_url = (
            "https://www.linkedin.com/jobs/search/?keywords=ingeniero%20de%20datos"
            "&geoId=105512687&sortBy=DD#ignored"
        )

        urls = expanded_search_urls([base_url], (1200, 3600))

        self.assertEqual(
            urls,
            [
                base_url.removesuffix("#ignored") + "&f_TPR=r1200",
                base_url.removesuffix("#ignored") + "&f_TPR=r3600",
            ],
        )
        self.assertTrue(all("sortBy=DD" in url for url in urls))

    def test_waits_between_temporal_searches(self) -> None:
        self.provider.config.linkedin_time_windows_seconds = (1200, 3600)
        self.provider.session.get = lambda *_args, **_kwargs: SimpleNamespace(  # type: ignore[method-assign]
            status_code=200, text=_card(100101) + _card(100102)
        )

        with (
            patch("providers.linkedin.random.uniform", return_value=4.25),
            patch("providers.linkedin.time.sleep") as sleep,
        ):
            snapshots = self.provider.fetch_snapshots()

        self.assertEqual(len(snapshots), 2)
        sleep.assert_called_once_with(4.25)

    def test_returns_raw_first_page_cards_without_relevance_filters(self) -> None:
        html = _card(100101, "Chef") + _card(100102, "Data Engineer")
        self.provider.session.get = lambda *_args, **_kwargs: SimpleNamespace(
            status_code=200, text=html
        )  # type: ignore[method-assign]

        result = self.provider.fetch_url(SEARCH_URL)

        self.assertEqual(result.state, "ok")
        self.assertEqual(result.raw_cards, 2)
        self.assertEqual(result.parsed_cards, 2)
        self.assertEqual([job.title for job in result.jobs], ["Chef", "Data Engineer"])
        self.assertEqual(result.jobs[0].id, "100101")
        self.assertEqual(
            result.jobs[0].url, "https://www.linkedin.com/jobs/view/100101"
        )

    def test_maximum_is_technical_card_cap_not_a_second_page(self) -> None:
        html = "".join(_card(1000 + index) for index in range(30))
        self.provider.session.get = lambda *_args, **_kwargs: SimpleNamespace(
            status_code=200, text=html
        )  # type: ignore[method-assign]

        result = self.provider.fetch_url(SEARCH_URL)

        self.assertEqual(result.raw_cards, 30)
        self.assertEqual(len(result.jobs), 25)
        self.assertEqual(result.state, "ok")

    def test_zero_maximum_uses_the_first_page_limit(self) -> None:
        provider = LinkedInProvider(
            _config(max_jobs=0), logging.getLogger("test-linkedin-unbounded")
        )
        html = "".join(_card(3000 + index) for index in range(30))
        provider.session.get = lambda *_args, **_kwargs: SimpleNamespace(
            status_code=200, text=html
        )  # type: ignore[method-assign]

        result = provider.fetch_url(SEARCH_URL)

        self.assertEqual(result.raw_cards, 30)
        self.assertEqual(len(result.jobs), 25)
        self.assertEqual(result.state, "ok")

    def test_guest_ten_card_fragment_is_partial_without_browser_confirmation(
        self,
    ) -> None:
        html = "".join(_card(2000 + index) for index in range(10))
        self.provider.session.get = lambda *_args, **_kwargs: SimpleNamespace(
            status_code=200, text=html
        )  # type: ignore[method-assign]

        result = self.provider.fetch_url(SEARCH_URL)

        self.assertEqual(result.raw_cards, 10)
        self.assertEqual(result.state, "partial")
        self.assertFalse(result.complete)

    def test_http_and_parse_health_states_are_never_reported_as_success(self) -> None:
        self.provider.session.get = lambda *_args, **_kwargs: SimpleNamespace(
            status_code=429, text=""
        )  # type: ignore[method-assign]
        limited = self.provider.fetch_url(SEARCH_URL)
        self.assertEqual(limited.state, "rate_limited")
        self.assertFalse(limited.complete)

        self.provider._rate_limited_until = 0
        self.provider.session.get = lambda *_args, **_kwargs: SimpleNamespace(
            status_code=200, text="<div>captcha</div>"
        )  # type: ignore[method-assign]
        blocked = self.provider.fetch_url(SEARCH_URL)
        self.assertEqual(blocked.state, "blocked")
        self.assertFalse(blocked.complete)

        self.provider.session.get = lambda *_args, **_kwargs: SimpleNamespace(
            status_code=200, text=_card(303) + "<div class='base-card'></div>"
        )  # type: ignore[method-assign]
        partial = self.provider.fetch_url(SEARCH_URL)
        self.assertEqual(partial.state, "partial")
        self.assertFalse(partial.complete)

    def test_check_session_explains_empty_instead_of_false_ok(self) -> None:
        self.provider.session.get = lambda *_args, **_kwargs: SimpleNamespace(
            status_code=200, text="<html></html>"
        )  # type: ignore[method-assign]

        healthy, detail = self.provider.check_session()

        self.assertFalse(healthy)
        self.assertEqual(self.provider.last_session_state, "empty")
        self.assertIn("empty:http=200:cards=0", detail)


if __name__ == "__main__":
    unittest.main()
