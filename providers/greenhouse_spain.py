from __future__ import annotations
import httpx
import asyncio

import logging
import re
from datetime import datetime, timedelta, timezone

import requests
from playwright.async_api import Playwright

from config import BotConfig
from matcher import is_job_geographically_viable
from models import JobItem


class GreenhouseSpainProvider:
    source = "greenhouse"

    # Catalog of product tech companies in Spain using public Greenhouse boards
    COMPANIES = [
        {
            "name": "Clarity AI",
            "board": "clarityai",
            "url": "https://boards-api.greenhouse.io/v1/boards/clarityai/jobs",
        },
        {
            "name": "Cabify",
            "board": "cabify",
            "url": "https://boards-api.greenhouse.io/v1/boards/cabify/jobs",
        },
        {
            "name": "Fever",
            "board": "feverup",
            "url": "https://boards-api.greenhouse.io/v1/boards/feverup/jobs",
        },
        {
            "name": "Wallapop",
            "board": "wallapop",
            "url": "https://boards-api.greenhouse.io/v1/boards/wallapop/jobs",
        },
        {
            "name": "Typeform",
            "board": "typeform",
            "url": "https://boards-api.greenhouse.io/v1/boards/typeform/jobs",
        },
        {
            "name": "Datadog Spain",
            "board": "datadog",
            "url": "https://boards-api.greenhouse.io/v1/boards/datadog/jobs",
        },
        {
            "name": "N26 Spain",
            "board": "n26",
            "url": "https://boards-api.greenhouse.io/v1/boards/n26/jobs",
        },
        {
            "name": "Algolia",
            "board": "algolia",
            "url": "https://boards-api.greenhouse.io/v1/boards/algolia/jobs",
        },
        {
            "name": "Jobandtalent",
            "board": "jobandtalent",
            "url": "https://boards-api.greenhouse.io/v1/boards/jobandtalent/jobs",
        },
    ]

    ALLOWED_LOCATIONS = [
        "spain",
        "españa",
        "madrid",
        "madrid",
        "barcelona",
        "remote",
        "remoto",
        "anywhere",
        "worldwide",
        "europe",
    ]

    CORE_TECH_STEMS = [
        "ai",
        "ia",
        "artificial",
        "machine learning",
        "learning",
        "vision",
        "visión",
        "deep learning",
        "llm",
        "rag",
        "generativ",
        "gpt",
        "nlp",
        "nlu",
        "data",
        "datos",
        "analytics",
        "bi",
        "etl",
        "python",
        "fastapi",
        "django",
        "flask",
        "backend",
        "fullstack",
        "full stack",
        "software",
        "developer",
        "desarrollador",
        "engineer",
        "ingeniero",
        "ingeniera",
        "predictiv",
        "automatiz",
        "automation",
        "plc",
        "scada",
        "industrial",
        "robotics",
        "mlops",
        "devops",
        "cloud",
        "aws",
        "docker",
    ]

    EXCLUDE_ROLE_STEMS = [
        "sales",
        "vendedor",
        "comercial",
        "account executive",
        "marketing",
        "content",
        "recruiter",
        "rrhh",
        "human resources",
        "legal",
        "customer support",
        "support specialist",
        "finance",
        "accountant",
        "copywriter",
        "designer",
        "product manager",
    ]

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
                "Accept": "application/json",
            }
        )

    def _is_job_relevant(self, title: str) -> bool:
        t_lower = title.lower()
        if any(ex in t_lower for ex in self.EXCLUDE_ROLE_STEMS):
            return False

        for ts in self.CORE_TECH_STEMS:
            if ts in ["ai", "ia"]:
                if re.search(r"\b" + ts + r"\b", t_lower):
                    return True
            else:
                if ts in t_lower:
                    return True
        return False

    def _is_location_viable(self, loc_str: str, title: str = "") -> bool:
        return is_job_geographically_viable(loc_str, title)

    def check_session(self) -> tuple[bool, str]:
        try:
            import requests

            r = requests.get(
                "https://boards.eu.greenhouse.io/",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if r.status_code == 200:
                return True, "ok"
            return False, f"http_{r.status_code}"
        except Exception as e:
            return False, f"error_{str(e)[:20]}"

    async def fetch_jobs(self, startup_deep_scan: bool = False) -> list[JobItem]:
        found_jobs: dict[str, JobItem] = {}
        self.logger.info(
            "Fetching Greenhouse Spain corporate boards | Companies=%d",
            len(self.COMPANIES),
        )

        now_utc = datetime.now(timezone.utc)

        for comp_meta in self.COMPANIES:
            comp_name = comp_meta["name"]
            api_url = comp_meta["url"]

            try:
                async with httpx.AsyncClient(headers=getattr(self, "headers", {})) as client:
                    r = await client.get(api_url, timeout=10)
                if r.status_code != 200:
                    self.logger.debug(
                        "Greenhouse board %s returned status %s",
                        comp_name,
                        r.status_code,
                    )
                    continue

                data = r.json()
                raw_jobs = data.get("jobs", [])

                for item in raw_jobs:
                    job_id = f"greenhouse_{item.get('id')}"
                    if job_id in found_jobs:
                        continue

                    title = item.get("title", "").strip()
                    if not title or not self._is_job_relevant(title):
                        continue

                    loc_data = item.get("location", {})
                    loc_name = (
                        loc_data.get("name", "")
                        if isinstance(loc_data, dict)
                        else str(loc_data)
                    )
                    if not self._is_location_viable(loc_name, title):
                        continue

                    url = item.get("absolute_url", "").strip()
                    if not url:
                        continue

                    # Freshness detection
                    posted_within_1h = False
                    updated_at = item.get("updated_at", "")
                    if updated_at:
                        try:
                            clean_upd = updated_at.replace("Z", "+00:00")
                            upd_dt = datetime.fromisoformat(clean_upd)
                            if (now_utc - upd_dt) <= timedelta(hours=24):
                                posted_within_1h = True
                        except Exception:
                            posted_within_1h = False
                            upd_dt = datetime.min.replace(tzinfo=timezone.utc)
                    else:
                        pub_dt = datetime.min.replace(tzinfo=timezone.utc)
                        upd_dt = pub_dt

                    loc_display = loc_name if loc_name else "España / Remoto"

                    job_obj = JobItem(
                        id=job_id,
                        title=title,
                        company=comp_name,
                        location=loc_display,
                        url=url,
                        source=self.source,
                        posted_within_1h=posted_within_1h,
                    )
                    found_jobs[job_id] = (job_obj, upd_dt)

                    max_results = getattr(self.config, "greenhouse_max_results", 35)
                    if len(found_jobs) >= max_results:
                        break

            except Exception as exc:
                self.logger.warning(
                    "Error fetching Greenhouse board %s: %s", comp_name, exc
                )

        # Sort jobs by update date descending (newest first)
        sorted_jobs = [
            j for j, _ in sorted(found_jobs.values(), key=lambda x: x[1], reverse=True)
        ]
        self.logger.info(
            "Greenhouse Spain search complete | viable_jobs_found=%d", len(sorted_jobs)
        )
        return sorted_jobs
