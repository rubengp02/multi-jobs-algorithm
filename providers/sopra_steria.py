import asyncio
import logging
from collections.abc import Iterable
from typing import AsyncIterable, Any

import requests

from config import BotConfig
from models import JobItem
from utils_stealth import get_stealth_headers

from . import JobProvider


class SopraSteriaProvider(JobProvider):
    """
    Extracts jobs from Sopra Steria using the public SmartRecruiters API.
    API endpoint: api.smartrecruiters.com/v1/companies/SopraSteria1/postings
    """

    def __init__(
        self, config: BotConfig, logger: logging.Logger, playwright: Any = None
    ) -> None:
        self.config = config
        self.logger = logger
        self.api_url = "https://api.smartrecruiters.com/v1/companies/SopraSteria1/postings?country=es"

    async def fetch_jobs(self) -> list[JobItem]:
        return [j async for j in self._fetch_jobs()]

    async def _fetch_jobs(self) -> AsyncIterable[JobItem]:
        try:
            response = requests.get(
                self.api_url, headers=get_stealth_headers(), timeout=15
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            self.logger.error(
                "Failed to fetch jobs from Sopra Steria SmartRecruiters API: %s", e
            )
            return

        postings = data.get("content", [])
        for p in postings:
            job_id = p.get("id")
            title = p.get("name", "").strip()

            # SmartRecruiters location object
            loc_obj = p.get("location", {})
            city = loc_obj.get("city", "").strip()
            region = loc_obj.get("region", "").strip()
            country = loc_obj.get("country", "").strip()

            loc_parts = [part for part in (city, region, country) if part]
            location = ", ".join(loc_parts) if loc_parts else "España"

            url = p.get(
                "ref", ""
            )  # the direct API ref or public URL. Actually, ref is the API URL!
            # The actual public URL is usually smartrecruiters.com/SopraSteria1/...
            # But wait, p has a "ref" which is API, and often there's no public URL in the list response.
            # Let's extract the public URL or fallback.

            # Wait, let's look at a SmartRecruiters JSON payload. We can build the URL.
            # Usually: https://careers.smartrecruiters.com/SopraSteria/{id} or the custom careers page.
            # Let's use the default SmartRecruiters URL which redirects properly.
            public_url = f"https://jobs.smartrecruiters.com/SopraSteria1/{job_id}"

            # We must fetch the description by querying the individual API endpoint!
            description = ""
            api_ref = p.get("ref")
            if api_ref:
                try:
                    detail_resp = requests.get(
                        api_ref, headers=get_stealth_headers(), timeout=10
                    )
                    if detail_resp.status_code == 200:
                        detail_data = detail_resp.json()
                        # Description is inside 'jobAd' -> 'sections'
                        sections = detail_data.get("jobAd", {}).get("sections", {})
                        desc_parts = []
                        for k, v in sections.items():
                            if v and v.get("text"):
                                desc_parts.append(v.get("text"))
                        description = "\n".join(desc_parts)
                except Exception as e:
                    self.logger.warning(
                        "Failed to fetch details for Sopra Steria job %s: %s", job_id, e
                    )

            yield JobItem(
                id=job_id,
                title=title,
                company="Sopra Steria",
                location=location,
                url=public_url,
                description=description,
                source="sopra_steria",
            )

    def check_session(self) -> tuple[bool, str]:
        return True, "ok"
