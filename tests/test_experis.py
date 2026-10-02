import logging
import unittest
from types import SimpleNamespace

from bs4 import BeautifulSoup

from enricher import _extract_page_text
from providers.experis import ExperisProvider


class ExperisProviderTests(unittest.TestCase):
    def test_extracts_unique_technical_jobs_and_infers_location(self) -> None:
        html = """
        <a class="seo-job-link" href="/es/oferta-de-empleo/101/python-developer-remoto">
          Python Developer 100% Remoto (H/M/X)
        </a>
        <a class="seo-job-link" href="https://www.experis.es/es/oferta-de-empleo/102/ingeniero-valencia">
          Ingeniero de Software - Valencia (H/M/X)
        </a>
        <a class="seo-job-link" href="/es/oferta-de-empleo/103/comercial-remoto">
          Comercial 100% Remoto (H/M/X)
        </a>
        <a class="seo-job-link" href="/es/oferta-de-empleo/101/python-developer-remoto">
          Python Developer 100% Remoto (H/M/X)
        </a>
        """
        config = SimpleNamespace(timeout_seconds=5, experis_max_results=10)
        provider = ExperisProvider(config, logging.getLogger("test-experis"))
        provider.session.get = lambda *_args, **_kwargs: SimpleNamespace(
            status_code=200,
            text=html,
            url=provider.ALL_JOBS_URL,
        )

        jobs = provider.fetch_jobs()

        self.assertEqual([job.id for job in jobs], ["experis_101", "experis_102"])
        self.assertEqual(jobs[0].location, "100% Remoto (España)")
        self.assertEqual(jobs[1].location, "Valencia")
        self.assertEqual(jobs[0].company, "Experis")

    def test_experis_description_avoids_page_chrome(self) -> None:
        soup = BeautifulSoup(
            """
            <body>
              <nav>Inicio | Ofertas | Contacto</nav>
              <section class="details-block job">
                Buscamos experiencia con Python, Azure y Docker para desarrollar plataformas.
              </section>
              <footer>Cookies y privacidad</footer>
            </body>
            """,
            "html.parser",
        )

        text = _extract_page_text(soup, is_linkedin=False, is_experis=True)

        self.assertIn("Python, Azure y Docker", text)
        self.assertNotIn("Cookies", text)


if __name__ == "__main__":
    unittest.main()
