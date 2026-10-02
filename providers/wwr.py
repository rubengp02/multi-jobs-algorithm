from __future__ import annotations

import hashlib
import logging
import re
import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx
from bs4 import BeautifulSoup
from playwright.sync_api import Playwright

from config import BotConfig
from models import JobItem


class WWRProvider:
    source = "wwr"

    ALLOWED_REGIONS = [
        "anywhere in the world",
        "europe",
        "europe only",
        "worldwide",
        "spain",
        "emea",
        "latam/europe",
        "eu",
        "all",
        "",
    ]

    DISALLOWED_REGIONS = [
        "usa only",
        "us only",
        "north america only",
        "americas only",
        "latam only",
        "asia only",
        "canada only",
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

    RSS_FEEDS = [
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
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
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
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

    def _is_region_viable(self, region_str: str) -> bool:
        r_lower = region_str.lower().strip()
        if not r_lower:
            return True

        if any(dis in r_lower for dis in self.DISALLOWED_REGIONS):
            return False

        return any(al in r_lower for al in self.ALLOWED_REGIONS)

    def check_session(self) -> tuple[bool, str]:
        try:
            import httpx

            with httpx.Client() as client:
                r = client.get(
                    self.RSS_FEEDS[0], headers={"User-Agent": "Mozilla/5.0"}, timeout=10
                )
                if r.status_code == 200:
                    return True, "ok"
                return False, f"http_{r.status_code}"
        except Exception as e:
            return False, f"error_{str(e)[:20]}"

    async def fetch_jobs(self, startup_deep_scan: bool = False) -> list[JobItem]:
        found_jobs: dict[str, JobItem] = {}
        self.logger.info(
            "Fetching WeWorkRemotely RSS feeds | Feeds=%d", len(self.RSS_FEEDS)
        )

        now_utc = datetime.now(timezone.utc)

        async with httpx.AsyncClient(headers=self.headers) as client:
            for feed_url in self.RSS_FEEDS:
                try:
                    r = await client.get(feed_url, timeout=12)
                    if r.status_code != 200:
                        self.logger.warning(
                            "WWR returned status %s for %s", r.status_code, feed_url
                        )
                        continue

                    soup = BeautifulSoup(r.text, "html.parser")
                    items = soup.find_all("item")

                    for it in items:
                        raw_title = it.find("title").text if it.find("title") else ""
                        raw_link = it.find("link")
                        url = (
                            raw_link.next_sibling.strip()
                            if (raw_link and raw_link.next_sibling)
                            else (raw_link.text if raw_link else "")
                        )

                        if not raw_title or not url:
                            continue

                        # Title format is usually "Company Name: Job Title"
                        if ":" in raw_title:
                            company, _, title = raw_title.partition(":")
                            company = company.strip()
                            title = title.strip()
                        else:
                            company = "Empresa Tech"
                            title = raw_title.strip()

                        if not self._is_job_relevant(title):
                            continue

                        # Extract region if available
                        region = ""
                        region_tag = it.find("region")
                        if region_tag and region_tag.text:
                            region = region_tag.text.strip()

                        if not self._is_region_viable(region):
                            continue

                        # Generate deterministic ID
                        job_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:12]
                        job_id = f"wwr_{job_hash}"
                        if job_id in found_jobs:
                            continue

                        # Freshness detection
                        posted_within_1h = False
                        pub_tag = it.find("pubdate") or it.find("pubDate")
                        if pub_tag and pub_tag.text:
                            try:
                                pub_dt = parsedate_to_datetime(pub_tag.text.strip())
                                if (now_utc - pub_dt) <= timedelta(hours=24):
                                    posted_within_1h = True
                            except Exception:
                                posted_within_1h = False
                                pub_dt = datetime.min.replace(tzinfo=timezone.utc)
                        else:
                            pub_dt = datetime.min.replace(tzinfo=timezone.utc)

                        loc_display = (
                            f"100% Remoto ({region})"
                            if region
                            else "100% Remoto (España / Global)"
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

                        max_results = getattr(self.config, "wwr_max_results", 35)
                        if len(found_jobs) >= max_results:
                            break

                except Exception as exc:
                    self.logger.warning(
                        "Error fetching WWR feed from %s: %s", feed_url, exc
                    )

        # Sort jobs by publication date descending (newest first)
        sorted_jobs = [
            j for j, _ in sorted(found_jobs.values(), key=lambda x: x[1], reverse=True)
        ]
        self.logger.info(
            "WWR remote search complete | viable_jobs_found=%d", len(sorted_jobs)
        )
        return sorted_jobs
