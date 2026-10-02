import asyncio
import logging

from collections.abc import Iterable
from typing import AsyncIterable, Any

from bs4 import BeautifulSoup

from config import BotConfig
from models import JobItem
from utils_stealth import apply_playwright_stealth

from . import JobProvider


class SystraProvider(JobProvider):
    """
    Extracts jobs from SYSTRA's iCIMS portal using Playwright to bypass JS requirements.
    """

    def __init__(
        self, config: BotConfig, logger: logging.Logger, playwright: Any = None
    ) -> None:
        self.config = config
        self.logger = logger
        self.playwright = playwright
        # iCIMS portal for SYSTRA, specifically filtering for Spain (Location ID 13526 is typical for Spain in iCIMS, or we can just search 'Spain' / 'España')
        self.url = (
            "https://careers-systra.icims.com/jobs/search?ss=1&searchLocation=13526--"
        )

    async def fetch_jobs(self) -> list[JobItem]:
        return [j async for j in self._fetch_jobs()]

    async def _fetch_jobs(self) -> AsyncIterable[JobItem]:
        if not self.playwright:
            self.logger.error(
                "SystraProvider requires playwright but it is not available."
            )
            return

        browser = None
        try:
            browser = self.playwright.chromium.launch(headless=True)
            context, page = apply_playwright_stealth(browser)

            # iCIMS often loads the actual job list in an iframe with id "icims_content_iframe"
            # We will go directly to the iframe URL to avoid outer wrapper issues.
            iframe_url = "https://careers-systra.icims.com/jobs/search?in_iframe=1&searchLocation=13526--"
            await page.goto(iframe_url, wait_until="networkidle", timeout=30000)

            # Wait for job listings to load
            try:
                await page.wait_for_selector(
                    ".iCIMS_JobsTable, .iCIMS_JobHeaderGroup", timeout=10000
                )
            except Exception:
                self.logger.warning(
                    "Timeout waiting for SYSTRA iCIMS jobs to load. Maybe no jobs in Spain or layout changed."
                )

            html_text = await page.content()
            soup = BeautifulSoup(html_text, "html.parser")

            # iCIMS jobs are usually in rows with class "row" inside ".iCIMS_JobsTable"
            job_links = soup.find_all("a", class_="iCIMS_Anchor")

            for a in job_links:
                title = a.get("title") or a.get_text(strip=True)
                url = a.get("href")

                # Exclude non-job links
                if not url or "job" not in url.lower():
                    continue

                # Fix relative URLs
                if url.startswith("/"):
                    url = f"https://careers-systra.icims.com{url}"
                elif not url.startswith("http"):
                    continue

                # The ID is usually in the URL: /jobs/1234/job
                job_id = (
                    url.split("/jobs/")[-1].split("/")[0] if "/jobs/" in url else url
                )

                # We need to fetch the job description page
                desc_page = await browser.new_page()
                try:
                    await desc_page.goto(
                        url + "?in_iframe=1",
                        wait_until="domcontentloaded",
                        timeout=15000,
                    )
                    desc_html = await desc_page.content()
                    desc_soup = BeautifulSoup(desc_html, "html.parser")

                    # Extract location
                    # Usually in a dl/dd pair or header
                    location = "España"  # Default
                    for label in desc_soup.find_all(
                        "dt", class_="iCIMS_JobHeaderGroup"
                    ):
                        if (
                            "Location" in label.get_text()
                            or "Ubicación" in label.get_text()
                        ):
                            loc_val = label.find_next_sibling("dd")
                            if loc_val:
                                location = loc_val.get_text(strip=True)
                                break

                    # Extract description
                    desc_div = desc_soup.find("div", class_="iCIMS_JobContent")
                    description = (
                        desc_div.get_text(separator="\n", strip=True)
                        if desc_div
                        else ""
                    )

                    yield JobItem(
                        id=job_id,
                        title=title.replace("Job Title", "").strip(),
                        company="SYSTRA",
                        location=location,
                        url=url,
                        description=description,
                        source="systra",
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to extract SYSTRA job {url}: {e}")
                finally:
                    await desc_page.close()
                    await asyncio.sleep(1)  # Be nice to their server

        except Exception as e:
            self.logger.error("Failed to process SYSTRA jobs: %s", e)
        finally:
            if browser:
                await browser.close()

    def check_session(self) -> tuple[bool, str]:
        return True, "ok"
