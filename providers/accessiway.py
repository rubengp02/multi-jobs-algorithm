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


class AccessiwayProvider:
    """Read Accessiway's public Teamtailor job board once per cycle."""

    source = "accessiway"
    ALL_JOBS_URL = "https://accessiway.teamtailor.com/jobs"

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

    @staticmethod
    def _location_from_card(card_text: str, title: str) -> str:
        """Keep Teamtailor's location and modality, excluding its department."""
        metadata = card_text
        if metadata.startswith(title):
            metadata = metadata[len(title) :].strip()
        # Some Teamtailor themes render the link title twice in the card text.
        if metadata.endswith(title):
            metadata = metadata[: -len(title)].strip()
        parts = [part.strip() for part in metadata.split("·") if part.strip()]
        if len(parts) >= 2:
            return " · ".join(parts[1:])
        return metadata or "Ubicación no especificada"

    def check_session(self) -> tuple[bool, str]:
        return True, "ok (manual verification)"

    async def fetch_jobs(self) -> list[JobItem]:
        self.last_blocked_reason = ""
        self.logger.info("Fetching Accessiway public job board")
        found: dict[str, JobItem] = {}

        try:
            response = self.session.get(
                self.ALL_JOBS_URL,
                timeout=getattr(self.config, "timeout_seconds", 25),
            )
            if response.status_code != 200:
                self.last_blocked_reason = "accessiway_http_%s" % response.status_code
                self.logger.warning(
                    "Accessiway returned status %s", response.status_code
                )
                return []

            soup = BeautifulSoup(response.text, "html.parser")
            max_results = getattr(self.config, "accessiway_max_results", 100)
            base_url = getattr(response, "url", self.ALL_JOBS_URL)

            for link in soup.select("a[href*='/jobs/']"):
                title = " ".join(link.get_text(" ", strip=True).split())
                url = urljoin(base_url, str(link["href"]))
                match = re.search(r"/jobs/(\d+)(?:[-/]|$)", url)
                if not title or not match:
                    continue

                job_id = "%s_%s" % (self.source, match.group(1))
                if job_id in found:
                    continue

                card = link.find_parent("li") or link.parent
                card_text = " ".join(card.get_text(" ", strip=True).split())
                found[job_id] = JobItem(
                    id=job_id,
                    title=title,
                    company="Accessiway",
                    location=self._location_from_card(card_text, title),
                    url=url,
                    source=self.source,
                )
                if len(found) >= max_results:
                    break
        except requests.RequestException as exc:
            self.last_blocked_reason = "accessiway_request_error"
            self.logger.warning("Error fetching Accessiway: %s", exc)
        except Exception as exc:
            self.last_blocked_reason = "accessiway_parse_error"
            self.logger.warning("Error parsing Accessiway listings: %s", exc)

        jobs = list(found.values())
        self.logger.info("Accessiway search complete | jobs_found=%d", len(jobs))
        return jobs
