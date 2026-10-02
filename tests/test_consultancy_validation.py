from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from main import build_providers
from models import JobItem
from provider_validation import (
    ProviderValidationStore,
    audit_provider,
    detect_provider_anomaly,
    provider_is_validated,
)
from providers.consultancies import (
    CONSULTANCY_SOURCE_IDS,
    CONSULTANCY_SOURCES,
    PublicConsultancyProvider,
    canonical_job_url,
)


class FakeResponse:
    def __init__(self, url: str, text: str, status_code: int = 200) -> None:
        self.url = url
        self.text = text
        self.status_code = status_code


class FakeSession:
    def __init__(self, pages: dict[str, FakeResponse]) -> None:
        self.pages = pages
        self.headers: dict[str, str] = {}

    def get(self, url: str, timeout: int) -> FakeResponse:
        return self.pages[url]


def config_for(directory: Path) -> SimpleNamespace:
    return SimpleNamespace(
        timeout_seconds=2,
        consultancy_max_pages=2,
        consultancy_max_results=50,
        provider_validation_dir=str(directory),
        provider_validation_max_pages=5,
        provider_validation_max_results=100,
        provider_validation_auto_on_anomaly=False,
        enabled_providers=[],
    )


class ConsultancyProviderTests(unittest.TestCase):
    def test_registry_has_the_28_named_source_adapters(self) -> None:
        self.assertEqual(len(CONSULTANCY_SOURCE_IDS), 28)
        self.assertEqual(
            set(CONSULTANCY_SOURCE_IDS),
            {source.source for source in CONSULTANCY_SOURCES},
        )
        for source in CONSULTANCY_SOURCES:
            with self.subTest(source=source.source):
                self.assertEqual(source.initial_status, "pending_validation")
                self.assertTrue(source.index_url.startswith("https://"))
                self.assertTrue(source.job_path_patterns)
                self.assertTrue(source.card_selectors)

    def test_each_adapter_parses_its_deterministic_listing_fixture(self) -> None:
        """Keep every registry entry covered when a portal selector changes."""
        paths = {
            "bo_growth": "/jobs/example",
            "avansel": "/jobs/example",
            "etalentum": "/ofertas-empleo/example",
            "ayanet": "/jobs/example",
            "grupo_brio": "/oferta/example",
            "w_hunt": "/vacantes/example",
            "habemus": "/oferta/example",
            "grupo_noas": "/oferta/example",
            "prosolbia": "/ofertas/example",
            "melt_group": "/oferta/example",
            "personal7": "/oferta/example",
            "montaner": "/oferta/example",
            "quality_temporal": "/oferta/example",
            "adecco": "/job/example",
            "randstad": "/ofertas-empleo/example",
            "gigroup": "/ofertas-de-trabajo/example",
            "faster": "/oferta/example",
            "iman": "/job/example",
            "grupo_crit": "/job/example",
            "synergie": "/oferta/example",
            "nortempo": "/offer/example",
            "ananda": "/oferta/example",
            "hays": "/job-detail/example",
            "michael_page": "/job-detail/example",
            "talent_search_people": "/oferta/example",
            "marlex": "/job/example",
            "manpower": "/job/example",
            "eurofirms": "/job/example",
        }
        config = config_for(Path(tempfile.mkdtemp()))
        for source in CONSULTANCY_SOURCES:
            with self.subTest(source=source.source):
                provider = PublicConsultancyProvider(
                    source, config, logging.getLogger("test")
                )
                html = f"<article><a href='{paths[source.source]}'>Oferta de prueba</a><span class='location'>Valencia</span></article>"
                jobs, next_url = provider._parse_page(
                    FakeResponse(source.index_url, html)
                )
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0].location, "Valencia")
                self.assertIsNone(next_url)

    def test_changed_structure_does_not_create_a_false_job(self) -> None:
        source = next(
            item for item in CONSULTANCY_SOURCES if item.source == "bo_growth"
        )
        provider = PublicConsultancyProvider(
            source, config_for(Path(tempfile.mkdtemp())), logging.getLogger("test")
        )
        jobs, next_url = provider._parse_page(
            FakeResponse(source.index_url, "<a href='/about'>Empresa</a>")
        )
        self.assertEqual(jobs, [])
        self.assertIsNone(next_url)

    def test_bounded_pagination_deduplicates_canonical_urls(self) -> None:
        source = next(
            item for item in CONSULTANCY_SOURCES if item.source == "bo_growth"
        )
        config = config_for(Path(tempfile.mkdtemp()))
        provider = PublicConsultancyProvider(source, config, logging.getLogger("test"))
        first = source.index_url
        second = "https://jobsite.bogrowth.es/jobs?page=2"
        provider.session = FakeSession(
            {
                first: FakeResponse(
                    first,
                    """
                    <a href='/jobs/data-engineer?utm_source=x'>Data Engineer</a>
                    <a rel='next' href='/jobs?page=2'>Siguiente</a>
                """,
                ),
                second: FakeResponse(
                    second,
                    """
                    <a href='/jobs/data-engineer'>Data Engineer</a>
                    <a href='/jobs/ml-engineer'>ML Engineer</a>
                """,
                ),
            }
        )
        jobs = provider.fetch_jobs()
        self.assertEqual(provider.last_fetch_pages, 2)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(
            canonical_job_url(jobs[0].url),
            "https://jobsite.bogrowth.es/jobs/data-engineer",
        )

    def test_public_dates_are_sorted_descending(self) -> None:
        source = next(
            item for item in CONSULTANCY_SOURCES if item.source == "bo_growth"
        )
        provider = PublicConsultancyProvider(
            source, config_for(Path(tempfile.mkdtemp())), logging.getLogger("test")
        )
        html = """
            <article><a href='/jobs/older'>Oferta antigua</a><time datetime='2026-08-01T10:00:00Z'></time></article>
            <article><a href='/jobs/newer'>Oferta reciente</a><time datetime='2026-08-02T10:00:00Z'></time></article>
        """
        provider.session = FakeSession(
            {source.index_url: FakeResponse(source.index_url, html)}
        )
        jobs = provider.fetch_jobs(max_pages=1)
        self.assertEqual(
            [job.title for job in jobs], ["Oferta reciente", "Oferta antigua"]
        )
        self.assertEqual(provider.last_ordering, "publication_date_desc")

    def test_partial_public_dates_preserve_portal_card_order(self) -> None:
        source = next(
            item for item in CONSULTANCY_SOURCES if item.source == "bo_growth"
        )
        provider = PublicConsultancyProvider(
            source, config_for(Path(tempfile.mkdtemp())), logging.getLogger("test")
        )
        html = """
            <article><a href='/jobs/undated'>Sin fecha</a></article>
            <article><a href='/jobs/dated'>Con fecha</a><time datetime='2026-08-02T10:00:00Z'></time></article>
        """
        provider.session = FakeSession(
            {source.index_url: FakeResponse(source.index_url, html)}
        )
        jobs = provider.fetch_jobs(max_pages=1)
        self.assertEqual([job.title for job in jobs], ["Sin fecha", "Con fecha"])
        self.assertEqual(provider.last_ordering, "portal_order_unverified")

    def test_http_429_is_explicit_and_returns_no_jobs(self) -> None:
        source = next(
            item for item in CONSULTANCY_SOURCES if item.source == "bo_growth"
        )
        provider = PublicConsultancyProvider(
            source, config_for(Path(tempfile.mkdtemp())), logging.getLogger("test")
        )
        provider.session = FakeSession(
            {source.index_url: FakeResponse(source.index_url, "rate limited", 429)}
        )
        self.assertEqual(provider.fetch_jobs(), [])
        self.assertEqual(provider.rate_limit_429_cycle, 1)
        self.assertIn("http_429", provider.last_blocked_reason)

    def test_public_dynamic_source_uses_bounded_browser_fallback_when_html_is_empty(
        self,
    ) -> None:
        source = next(item for item in CONSULTANCY_SOURCES if item.source == "adecco")
        provider = PublicConsultancyProvider(
            source, config_for(Path(tempfile.mkdtemp())), logging.getLogger("test")
        )
        provider.session = FakeSession(
            {source.index_url: FakeResponse(source.index_url, "<main></main>")}
        )
        rendered = JobItem(
            "adecco-1",
            "Ingeniero de datos",
            "Adecco",
            "Valencia",
            "https://www.adecco.com/es-es/job/data",
            "adecco",
        )
        with patch.object(
            provider, "_fetch_dynamic_listing", return_value={rendered.id: rendered}
        ) as fallback:
            jobs = provider.fetch_jobs()
        fallback.assert_called_once_with(2, 50)
        self.assertEqual(jobs, [rendered])


class ProviderAuditTests(unittest.TestCase):
    def _job(self, title: str, url: str, location: str = "Valencia") -> JobItem:
        return JobItem("id-" + title, title, "Bo Growth", location, url, "bo_growth")

    def test_eligible_visible_absence_degrades_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = config_for(Path(temp))
            reference_job = self._job(
                "Data Engineer", "https://jobsite.bogrowth.es/jobs/data-engineer"
            )
            fake = SimpleNamespace(
                last_blocked_reason="",
                last_http_status=200,
                last_fetch_pages=1,
                last_ordering="portal_order_unverified",
                fetch_jobs=lambda **_: [],
            )
            with patch(
                "provider_validation.build_consultancy_provider", return_value=fake
            ):
                report = audit_provider(
                    "bo_growth",
                    config,
                    logging.getLogger("test"),
                    eligible_reason=lambda _: None,
                    reference_collector=lambda *_: (
                        [reference_job],
                        ["https://jobsite.bogrowth.es/jobs"],
                        None,
                    ),
                )
            self.assertEqual(report["status"], "degraded")
            self.assertEqual(len(report["comparison"]["eligible_missing"]), 1)
            self.assertEqual(
                ProviderValidationStore(temp).get("bo_growth")["status"], "degraded"
            )

    def test_filtered_absence_is_reported_but_does_not_count_as_important(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = config_for(Path(temp))
            reference_job = self._job(
                "Office Manager",
                "https://jobsite.bogrowth.es/jobs/office-manager",
                "Madrid",
            )
            fake = SimpleNamespace(
                last_blocked_reason="",
                last_http_status=200,
                last_fetch_pages=1,
                last_ordering="portal_order_unverified",
                fetch_jobs=lambda **_: [],
            )
            with patch(
                "provider_validation.build_consultancy_provider", return_value=fake
            ):
                report = audit_provider(
                    "bo_growth",
                    config,
                    logging.getLogger("test"),
                    eligible_reason=lambda _: "location",
                    reference_collector=lambda *_: (
                        [reference_job],
                        ["https://jobsite.bogrowth.es/jobs"],
                        None,
                    ),
                )
            self.assertEqual(report["status"], "validated")
            self.assertEqual(report["extractor"]["ordering"], "portal_order_unverified")
            self.assertEqual(len(report["comparison"]["missing"]), 1)
            self.assertEqual(report["comparison"]["eligible_missing"], [])
            self.assertTrue(
                Path(ProviderValidationStore(temp).get("bo_growth")["report"]).exists()
            )

    def test_anomaly_is_only_triggered_after_a_real_baseline(self) -> None:
        self.assertIsNone(detect_provider_anomaly({}, count=0, blocked_reason=""))
        self.assertEqual(
            detect_provider_anomaly(
                {"last_runtime_count": 5}, count=0, blocked_reason=""
            ),
            "zero_after_success",
        )
        self.assertEqual(
            detect_provider_anomaly(
                {"last_runtime_count": 20}, count=6, blocked_reason=""
            ),
            "strong_volume_drop",
        )

    def test_pending_provider_is_not_built_until_validated_and_manually_enabled(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            config = config_for(Path(temp))
            config.enabled_providers = ["bo_growth"]
            logger = logging.getLogger("test")
            self.assertEqual(build_providers(config, logger), {})
            ProviderValidationStore(temp).update("bo_growth", status="validated")
            providers = build_providers(config, logger)
            self.assertIn("bo_growth", providers)
            self.assertTrue(provider_is_validated("bo_growth", temp))

    def test_audit_does_not_receive_seen_or_notifier_dependencies(self) -> None:
        # Its public signature only accepts source/config/logger/filter callback.
        # The JSON report is the sole persistent side effect.
        self.assertNotIn("seen", audit_provider.__code__.co_varnames)
        self.assertNotIn("notifier", audit_provider.__code__.co_varnames)
