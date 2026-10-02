from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
import asyncio

import httpx
from playwright.sync_api import Playwright

from config import BotConfig
from models import JobItem


class RemoteOKProvider:
    source = "remoteok"

    API_URL = "https://remoteok.com/api"

    ALLOWED_LOCATIONS = [
        "spain",
        "españa",
        "europe",
        "worldwide",
        "anywhere",
        "eu",
        "emea",
        "uk, europe",
        "europe only",
        "all",
        "remote",
        "",
    ]

    DISALLOWED_LOCATIONS = [
        "usa only",
        "us only",
        "north america",
        "latam only",
        "canada only",
        "asia only",
        "australia only",
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
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        }

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

    def _is_location_viable(self, loc_str: str) -> bool:
        l_lower = loc_str.lower().strip()
        if not l_lower:
            return True

        if any(dis in l_lower for dis in self.DISALLOWED_LOCATIONS):
            return False

        return any(al in l_lower for al in self.ALLOWED_LOCATIONS)

    def check_session(self) -> tuple[bool, str]:
        try:
            with httpx.Client() as client:
                r = client.get(
                    "https://remoteok.com/api",
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=10,
                )
                if r.status_code == 200:
                    return True, "ok"
                return False, f"http_{r.status_code}"
        except Exception as e:
            return False, f"error_{str(e)[:20]}"

    async def fetch_jobs(self, startup_deep_scan: bool = False) -> list[JobItem]:
        found_jobs: dict[str, tuple[JobItem, datetime]] = {}
        self.logger.info("Fetching RemoteOK global remote listings")

        now_utc = datetime.now(timezone.utc)

        try:
            async with httpx.AsyncClient(headers=self.headers) as client:
                r = await client.get(self.API_URL, timeout=12)
                
                if r.status_code != 200:
                    self.logger.warning("RemoteOK returned status %s", r.status_code)
                    return []

                data = r.json()
                if not isinstance(data, list):
                    return []

                # First element is metadata / legal disclaimer
                items = [j for j in data[1:] if isinstance(j, dict)]

                for item in items:
                    raw_id = item.get("id") or item.get("slug")
                    if not raw_id:
                        continue

                    job_id = f"remoteok_{raw_id}"
                    if job_id in found_jobs:
                        continue

                    title = item.get("position", "").strip()
                    if not title or not self._is_job_relevant(title):
                        continue

                    loc = item.get("location", "").strip()
                    if not self._is_location_viable(loc):
                        continue

                    company = item.get("company", "Empresa Tech").strip()
                    url = item.get("url", "").strip()
                    if not url:
                        url = f"https://remoteok.com/remote-jobs/{raw_id}"

                    # Parse date
                    date_str = item.get("date", "")
                    posted_within_1h = False
                    pub_dt = datetime.min.replace(tzinfo=timezone.utc)

                    if date_str:
                        try:
                            clean_dt = date_str.replace("Z", "+00:00")
                            pub_dt = datetime.fromisoformat(clean_dt)
                            if (now_utc - pub_dt) <= timedelta(hours=24):
                                posted_within_1h = True
                        except Exception:
                            posted_within_1h = False

                    loc_display = (
                        f"100% Remoto ({loc})" if loc else "100% Remoto (España / Global)"
                    )

                    job_obj = JobItem(
                        id=job_id,
                        title=title,
                        company=company,
                        location=loc_display,
                        url=url,
                        source=self.source,
                        posted_within_1h=posted_within_1h,
                    )
                    found_jobs[job_id] = (job_obj, pub_dt)

                    max_results = getattr(self.config, "remoteok_max_results", 30)
                    if len(found_jobs) >= max_results:
                        break

        except Exception as exc:
            self.logger.warning("Error fetching RemoteOK: %s", exc)

        # Sort jobs by publication date descending (newest first)
        sorted_jobs = [
            j for j, _ in sorted(found_jobs.values(), key=lambda x: x[1], reverse=True)
        ]
        self.logger.info(
            "RemoteOK search complete | viable_jobs_found=%d", len(sorted_jobs)
        )
        return sorted_jobs
