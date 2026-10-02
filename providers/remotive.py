from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import httpx
from playwright.async_api import Playwright

from config import BotConfig
from models import JobItem


class RemotiveProvider:
    source = "remotive"

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

    ENDPOINTS = [
        "https://remotive.com/api/remote-jobs?category=software-dev",
        "https://remotive.com/api/remote-jobs?category=data",
        "https://remotive.com/api/remote-jobs?category=devops",
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
        # Temporarily synchronous for startup check, or make it async if needed.
        # Startup checks usually remain sync.
        try:
            import httpx
            with httpx.Client() as client:
                r = client.get(
                    "https://remotive.com/api/remote-jobs?category=software-dev&limit=1",
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=10.0,
                )
                if r.status_code == 200:
                    return True, "ok"
                return False, f"http_{r.status_code}"
        except Exception as e:
            return False, f"error_{str(e)[:20]}"

    async def fetch_jobs(self, startup_deep_scan: bool = False) -> list[JobItem]:
        found_jobs: dict[str, tuple[JobItem, datetime]] = {}
        self.logger.info(
            "Fetching Remotive remote listings | Categories=%d", len(self.ENDPOINTS)
        )

        now_utc = datetime.now(timezone.utc)

        async with httpx.AsyncClient(headers=self.headers, timeout=12.0) as client:
            for endpoint in self.ENDPOINTS:
                try:
                    r = await client.get(endpoint)
                    if r.status_code != 200:
                        self.logger.warning(
                            "Remotive returned status %s for %s", r.status_code, endpoint
                        )
                        continue

                    data = r.json()
                    raw_jobs = data.get("jobs", [])

                    for item in raw_jobs:
                        job_id = f"remotive_{item.get('id')}"
                        if job_id in found_jobs:
                            continue

                        title = item.get("title", "").strip()
                        if not title or not self._is_job_relevant(title):
                            continue

                        req_loc = item.get("candidate_required_location", "").strip()
                        if not self._is_location_viable(req_loc):
                            continue

                        company = item.get("company_name", "Empresa Tech").strip()
                        url = item.get("url", "").strip()

                        loc_display = (
                            f"100% Remoto ({req_loc})"
                            if req_loc
                            else "100% Remoto (España / Global)"
                        )

                        # Parse publication date for freshness
                        posted_within_1h = False
                        pub_str = item.get("publication_date", "")
                        if pub_str:
                            try:
                                clean_pub = pub_str.replace("Z", "+00:00")
                                pub_dt = datetime.fromisoformat(clean_pub)
                                if (now_utc - pub_dt) <= timedelta(hours=24):
                                    posted_within_1h = True
                            except Exception:
                                posted_within_1h = False
                                pub_dt = datetime.min.replace(tzinfo=timezone.utc)
                        else:
                            pub_dt = datetime.min.replace(tzinfo=timezone.utc)

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

                        max_results = getattr(self.config, "remotive_max_results", 35)
                        if len(found_jobs) >= max_results:
                            break

                except Exception as exc:
                    self.logger.warning(
                        "Error fetching Remotive from %s: %s", endpoint, exc
                    )

        # Sort jobs by publication date descending (newest first)
        sorted_jobs = [
            j for j, _ in sorted(found_jobs.values(), key=lambda x: x[1], reverse=True)
        ]
        self.logger.info(
            "Remotive remote search complete | viable_jobs_found=%d", len(sorted_jobs)
        )
        return sorted_jobs
