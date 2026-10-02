import unittest

from models import JobItem
from project_prompt import (
    TELEGRAM_COPY_TEXT_MAX_CHARS,
    build_project_buttons,
    build_project_prompt,
)


def make_job(url: str = "https://example.com/jobs/123") -> JobItem:
    return JobItem(
        id="offer-123",
        title="Ingeniero de IA",
        company="Example",
        location="Valencia",
        url=url,
        source="example",
    )


class ProjectPromptTests(unittest.TestCase):
    def test_prompt_keeps_the_exact_offer_url_and_full_request_context(self) -> None:
        job = make_job()

        prompt = build_project_prompt(job)

        self.assertIn(job.url, prompt)
        self.assertIn("CV y GitHub", prompt)
        self.assertIn("3 proyectos personales realistas", prompt)
        self.assertIn("MVP", prompt)
        self.assertIn("stack justificado", prompt)
        self.assertIn("cómo presentarlo", prompt)
        self.assertIn("no inventes experiencia", prompt)

    def test_elaborate_prompt_uses_one_callback_button_when_it_exceeds_limit(
        self,
    ) -> None:
        job = make_job()

        buttons = build_project_buttons(job)

        self.assertGreater(len(build_project_prompt(job)), TELEGRAM_COPY_TEXT_MAX_CHARS)
        self.assertEqual(len(buttons[0]), 1)
        self.assertEqual(buttons[0][0]["text"], "📋 Prompt")
        self.assertEqual(buttons[0][0]["callback_data"], "/project offer-123")

    def test_long_url_preserves_it_via_prompt_callback(self) -> None:
        job = make_job("https://example.com/" + ("a" * 300))

        buttons = build_project_buttons(job)

        self.assertEqual(len(buttons[0]), 1)
        self.assertEqual(buttons[0][0]["text"], "📋 Prompt")
        self.assertEqual(buttons[0][0]["callback_data"], "/project offer-123")
        self.assertNotIn("copy_text", buttons[0][0])


if __name__ == "__main__":
    unittest.main()
