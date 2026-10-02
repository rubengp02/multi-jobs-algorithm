import logging
import os

import requests

from models import JobItem

logger = logging.getLogger(__name__)


def evaluate_job_with_gemini(job: JobItem, description: str) -> bool:
    """
    Evaluates if the job is a true match using Gemini API.
    Returns True if approved, False if rejected (e.g. pure Frontend/QA).
    """
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not gemini_key:
        return True  # Default to pass if no key configured

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={gemini_key}"

    prompt = f"""
    Evalúa esta oferta de trabajo para un desarrollador de software cuyo foco es Python / Backend / Inteligencia Artificial / Data.

    TÍTULO: {job.title}
    EMPRESA: {job.company}
    DESCRIPCIÓN: {description[:2000]}

    REGLA ESTRICTA DE RECHAZO:
    Si el rol principal es PURAMENTE de Frontend (React, Angular, Vue), QA (Testing, Automatización de QA), Mobile (iOS, Android), Sistemas/DevOps puros o Soporte Técnico, DEBES RECHAZARLA.

    REGLA DE APROBACIÓN:
    Si el rol central es Backend, Data Engineer, Machine Learning o IA (especialmente si usan Python), DEBES APROBARLA.
    Si es un rol Fullstack que usa Python/Backend como núcleo pero pide React/Frontend como un extra o "nice to have", APRUÉBALA.
    Si tienes dudas, APRUÉBALA.

    Responde ÚNICAMENTE con la palabra "APROBADA" o "RECHAZADA". No des explicaciones ni uses otros caracteres.
    """

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 250},
    }

    try:
        r = requests.post(url, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        ans = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{"text": ""}])[0]
            .get("text", "")
            .strip()
            .upper()
        )
        if "RECHAZADA" in ans:
            logger.info(f"LLM FILTER REJECTED: {job.title} @ {job.company}")
            return False
        return True
    except Exception as e:
        logger.warning(f"Gemini API evaluation failed for {job.id}: {e}")
        return True
