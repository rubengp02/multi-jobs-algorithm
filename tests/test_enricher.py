import json
import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup

from enricher import MAX_DESCRIPTION_CHARS, _extract_page_text, enrich_job_description
from models import JobItem


class LinkedInDescriptionExtractionTests(unittest.TestCase):
    def test_uses_offer_description_not_linkedin_interface(self) -> None:
        soup = BeautifulSoup(
            """
            <main>
              <p>Usa la IA para evaluar como encajarias en esta oferta.</p>
              <div class="show-more-less-html__markup">
                Buscamos una persona con Python, FastAPI y Docker para crear APIs.
              </div>
            </main>
            """,
            "html.parser",
        )

        text = _extract_page_text(soup, is_linkedin=True)

        self.assertIn("Python", text)
        self.assertNotIn("Usa la IA", text)

    def test_does_not_treat_linkedin_page_chrome_as_a_description(self) -> None:
        soup = BeautifulSoup(
            "<main>Inicia sesion. Usa la IA para evaluar como encajarias.</main>",
            "html.parser",
        )

        self.assertEqual(_extract_page_text(soup, is_linkedin=True), "")

    def test_keeps_generic_provider_fallback(self) -> None:
        soup = BeautifulSoup("<main>Oferta con Python y SQL.</main>", "html.parser")

        self.assertEqual(
            _extract_page_text(soup, is_linkedin=False), "Oferta con Python y SQL."
        )

    def test_uses_common_public_ats_description_selector(self) -> None:
        soup = BeautifulSoup(
            """
            <main>Navegacion y otras vacantes.</main>
            <div data-qa="job-description">
              Experiencia minima de 2 anos con Python, Docker y PostgreSQL.
            </div>
            """,
            "html.parser",
        )

        text = _extract_page_text(
            soup, is_linkedin=False, hostname="jobs.example-consultancy.es"
        )

        self.assertIn("Experiencia minima de 2 anos", text)
        self.assertNotIn("Navegacion", text)

    @patch("enricher.requests.get")
    def test_uses_public_jobposting_jsonld_for_any_provider(self, get: Mock) -> None:
        description = "Experiencia minima de 3 anos con Python y Kubernetes. Ingles C1."
        get.return_value = Mock(
            status_code=200,
            text=(
                "<html><head><script type='application/ld+json'>"
                + json.dumps(
                    {
                        "@context": "https://schema.org",
                        "@type": "JobPosting",
                        "description": description,
                    }
                )
                + "</script></head><body><main>Contenido de pagina</main></body></html>"
            ),
        )
        job = JobItem(
            id="consultancy-jsonld",
            title="Engineer",
            company="Example consultancy",
            location="Valencia",
            url="https://jobs.example-consultancy.es/offers/1",
            source="consultancy",
        )

        self.assertEqual(enrich_job_description(job), description)

    @patch("enricher.requests.get")
    def test_preserves_requirements_beyond_the_previous_short_cap(
        self, get: Mock
    ) -> None:
        late_requirement = "Se requiere SQLAlchemy y Alembic."
        get.return_value = Mock(
            status_code=200,
            text=(
                '<div class="show-more-less-html__markup">'
                + ("Introduccion. " * 400)
                + late_requirement
                + "</div>"
            ),
        )
        job = JobItem(
            id="late-stack",
            title="Backend Engineer",
            company="Example",
            location="Valencia",
            url="https://www.linkedin.com/jobs/view/late-stack",
            source="linkedin",
        )

        description = enrich_job_description(job)

        self.assertGreater(len(description), 3_500)
        self.assertIn(late_requirement, description)
        self.assertLessEqual(len(description), MAX_DESCRIPTION_CHARS)


if __name__ == "__main__":
    unittest.main()
