import asyncio
import json
import logging

from bs4 import BeautifulSoup
from curl_cffi import requests

from models import JobItem


class SynergieProvider:
    def __init__(self, config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.last_blocked_reason = ""

    def check_session(self) -> tuple[bool, str]:
        try:
            import requests

            r = requests.get(
                "https://www.synergie.es/busco-trabajo/",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if r.status_code == 200:
                return True, "ok"
            return False, f"http_{r.status_code}"
        except Exception as e:
            return False, f"error_{str(e)[:20]}"

    async def fetch_jobs(self, startup_deep_scan: bool = False) -> list[JobItem]:
        self.last_blocked_reason = ""
        try:
            resp = requests.get(
                "https://www.synergie.es/busco-trabajo/",
                impersonate="chrome",
                timeout=15,
            )
            if resp.status_code != 200:
                self.last_blocked_reason = f"HTTP {resp.status_code}"
                return []
        except Exception as e:
            self.last_blocked_reason = str(e)
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        island = soup.find(
            "astro-island", attrs={"opts": lambda x: x and "OfferList" in x}
        )
        if not island or not island.get("props"):
            self.last_blocked_reason = "No Astro props found"
            return []

        try:
            data = json.loads(island.get("props"))
        except Exception:
            self.last_blocked_reason = "JSON parse error"
            return []

        jobs_raw = []

        def traverse(obj):
            if isinstance(obj, dict):
                if "job_request" in obj and "title" in obj and "url" in obj:
                    jobs_raw.append(obj)
                for v in obj.values():
                    traverse(v)
            elif isinstance(obj, list):
                for i in obj:
                    traverse(i)

        traverse(data)

        found = []
        for obj in jobs_raw:
            try:
                title = obj["title"][1]
                url = obj["url"][1]
                if not title or not url or "DEJA TU CV" in title.upper():
                    continue

                city = obj.get("city", [0, ""])[1]
                desc = obj.get("description", [0, ""])[1] or ""

                try:
                    prov = obj["posting_province_id"][1]["NOMBRE_PROV"][1]
                    if prov and prov.lower() != city.lower():
                        city = f"{city}, {prov}"
                except Exception:
                    pass

                job = JobItem(
                    id=url,
                    url=url,
                    title=title,
                    company="Synergie",
                    location=city.strip(", "),
                    description=desc,
                    source="synergie",
                )
                found.append(job)
            except Exception:
                continue

        return found
