from __future__ import annotations
import httpx
import asyncio

import logging
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from playwright.async_api import Playwright

from config import BotConfig
from models import JobItem


class ExperisProvider:
    """Read the public, server-rendered Experis job index once per cycle."""

    source = "experis"
    ALL_JOBS_URL = "https://www.experis.es/es/all-jobs"

    # The Experis index contains vacancies outside technology too. Keep only
    # roles that can reasonably be relevant before they enter the common flow.
    CORE_TECH_STEMS = (
        "ai",
        "ia",
        "artificial",
        "machine learning",
        "data",
        "datos",
        "software",
        "developer",
        "desarrollador",
        "engineer",
        "ingenier",
        "backend",
        "frontend",
        "fullstack",
        "full stack",
        "python",
        "java",
        "cloud",
        "devops",
        "sre",
        "security",
        "seguridad",
        "cyber",
        "infra",
        "sistemas",
        "systems",
        "network",
        "redes",
        "sap",
        "servicenow",
        "workday",
        "helix",
        "salesforce",
        "qa",
        "tester",
        "automatiz",
        "robot",
        "rpa",
        "digital",
        "it ",
        "it/",
        "it-",
        "técnic",
        "tecnic",
        "analista",
        "analyst",
        "arquitect",
        "architect",
    )
    EXCLUDE_ROLE_STEMS = (
        "comercial",
        "ventas",
        "sales",
        "recruit",
        "rrhh",
        "recursos humanos",
        "marketing",
        "accountant",
        "contable",
        "legal",
        "abogado",
        "administrativ",
    )

    def __init__(
        self,
        config: BotConfig,
        logger: logging.Logger,
        playwright: Playwright | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        self.last_blocked_reason = ""
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            }
        )

    @classmethod
    def _is_job_relevant(cls, title: str) -> bool:
        normalized = title.lower()
        if any(term in normalized for term in cls.EXCLUDE_ROLE_STEMS):
            return False

        for term in cls.CORE_TECH_STEMS:
            if term in {"ai", "ia", "qa"}:
                if re.search(r"\\b" + re.escape(term) + r"\\b", normalized):
                    return True
            elif term in normalized:
                return True
        return False

    @staticmethod
    def _location_from_title(title: str) -> str:
        normalized = title.lower()
        if re.search(
            r"(?:100\s*%\s*)?(?:remoto|remote)\b|\bfull\s*remote\b|"
            r"\bteletrabajo\s*100\s*%",
            normalized,
        ):
            return "100% Remoto (España)"
        if "madrid" in normalized or "madrid" in normalized:
            return "madrid"
        return "España (ubicación no especificada)"

    def check_session(self) -> tuple[bool, str]:
        return True, "ok (manual verification)"

    async def fetch_jobs(self) -> list[JobItem]:
        self.last_blocked_reason = ""
        self.logger.info("Fetching Experis public job index")
        found: dict[str, JobItem] = {}

        try:
            response = self.session.get(
                self.ALL_JOBS_URL,
                timeout=getattr(self.config, "timeout_seconds", 25),
            )
            if response.status_code != 200:
                self.last_blocked_reason = "experis_http_%s" % response.status_code
                self.logger.warning("Experis returned status %s", response.status_code)
                return []

            soup = BeautifulSoup(response.text, "html.parser")
            max_results = getattr(self.config, "experis_max_results", 60)
            base_url = getattr(response, "url", self.ALL_JOBS_URL)

            for link in soup.select("a.seo-job-link[href]"):
                title = " ".join(link.get_text(" ", strip=True).split())
                url = urljoin(base_url, str(link["href"]))
                match = re.search(r"/oferta-de-empleo/(\d+)(?:/|$)", url)
                if not title or not match or not self._is_job_relevant(title):
                    continue

                job_id = "%s_%s" % (self.source, match.group(1))
                if job_id in found:
                    continue

                found[job_id] = JobItem(
                    id=job_id,
                    title=title,
                    company="Experis",
                    location=self._location_from_title(title),
                    url=url,
                    source=self.source,
                )
                if len(found) >= max_results:
                    break
        except requests.RequestException as exc:
            self.last_blocked_reason = "experis_request_error"
            self.logger.warning("Error fetching Experis: %s", exc)
        except Exception as exc:
            self.last_blocked_reason = "experis_parse_error"
            self.logger.warning("Error parsing Experis listings: %s", exc)

        jobs = list(found.values())
        self.logger.info("Experis search complete | viable_jobs_found=%d", len(jobs))
        return jobs
