from __future__ import annotations

from typing import Any

from models import JobItem

TELEGRAM_COPY_TEXT_MAX_CHARS = 256


def build_project_prompt(job: JobItem) -> str:
    """Build the project-ideas request pasted into the user's ChatGPT chat."""
    return (
        "Mi CV y GitHub ya están en esta conversación. Lee esta oferta y propón "
        "3 proyectos personales realistas, no avanzados y alineados con sus requisitos "
        "para reforzar mucho mi candidatura. Para cada proyecto indica: objetivo, MVP "
        "concreto, stack justificado, plan breve de ejecución y cómo presentarlo en la "
        "candidatura. Prioriza los requisitos explícitos de la oferta, adapta las ideas "
        "a mi experiencia y proyectos existentes, y no inventes experiencia, tecnologías "
        "ni requisitos.\n\n"
        f"Oferta: {job.url}"
    )


def build_project_buttons(job: JobItem) -> list[list[dict[str, Any]]]:
    """Return Telegram-native actions for the job-specific project prompt.

    Telegram permits CopyTextButton payloads of at most 256 characters. A
    callback is used only when preserving the complete offer URL exceeds it.
    """
    prompt = build_project_prompt(job)
    if len(prompt) <= TELEGRAM_COPY_TEXT_MAX_CHARS:
        return [[{"text": "📋 Prompt", "copy_text": {"text": prompt}}]]

    return [[{"text": "📋 Prompt", "callback_data": f"/project {job.id}"}]]
