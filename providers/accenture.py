from __future__ import annotations
import asyncio

import logging

from playwright.async_api import Playwright

from config import BotConfig
from models import JobItem, JobProvider
from utils_stealth import apply_playwright_stealth


class AccentureProvider(JobProvider):
    source = "accenture"

    def __init__(
        self,
        config: BotConfig,
        logger: logging.Logger,
        playwright: Playwright | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        self.playwright = playwright

    def check_session(self) -> tuple[bool, str]:
        if not self.playwright:
            return False, "Playwright required"
        return True, "ok"

    async def fetch_jobs(self, startup_deep_scan: bool = False) -> list[JobItem]:
        if not self.playwright:
            return []

        jobs = []
        try:
            browser = self.playwright.chromium.launch(headless=True)
            context, page = apply_playwright_stealth(browser)
            self.logger.info("Fetching Accenture listings via Playwright")
            await page.goto(
                "https://www.accenture.com/es-es/careers/jobsearch?jk=&sb=1",
                wait_until="networkidle",
                timeout=20000,
            )

            # Wait for job cards to render
            await page.wait_for_selector(
                ".cmp-job-listing__card, [data-cmp-data-layer]", timeout=10000
            )

            # Extract links
            html = await page.content()

            # We can use regex to find all job detail links cleanly
            import re

            links = set(
                re.findall(r'href=["\']([^"\']*jobdetails\?[^"\']+)["\']', html)
            )

            for link in links:
                full_url = (
                    f"https://www.accenture.com{link}" if link.startswith("/") else link
                )
                # We extract the title from the URL parameters as a fallback,
                # but we'll let the AI/Enricher extract the real title/description when it visits the URL.
                match = re.search(r"title=([^&]+)", link)
                title = (
                    match.group(1).replace("+", " ") if match else "Accenture Vacante"
                )

                job_id = ""
                id_match = re.search(r"id=([^&]+)", link)
                if id_match:
                    job_id = id_match.group(1)

                if not job_id:
                    continue

                jobs.append(
                    JobItem(
                        id=job_id,
                        title=title,
                        company="Accenture",
                        location="España",
                        url=full_url,
                        description="",
                        source=self.source,
                    )
                )

            await browser.close()
        except Exception as e:
            self.logger.error("Error fetching from Accenture: %s", e)

        return jobs
