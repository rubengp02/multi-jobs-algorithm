from __future__ import annotations
import httpx
import asyncio

import logging
import os
import re

import requests
from bs4 import BeautifulSoup
from playwright.async_api import Playwright

from config import BotConfig
from models import JobItem


class UPVSIEProvider:
    source = "upv_sie"
    OFFICIAL_APP_URL = "https://aplicat.upv.es/dire-app/gesOfertas.xhtml"

    CORE_TECH_STEMS = [
        "ai",
        "ia",
        "inteligencia artificial",
        "machine learning",
        "deep learning",
        "vision",
        "visión",
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
        "desarrolladora",
        "programador",
        "programadora",
        "predictiv",
        "robótica",
        "robotica",
        "robotics",
        "rpa",
        "uipath",
        "n8n",
        "mlops",
        "devops",
    ]

    EXCLUDE_ROLE_STEMS = [
        "edificación",
        "edificacion",
        "obra",
        "climatización",
        "climatizacion",
        "frío",
        "frio",
        "hidráulica",
        "hidraulica",
        "civil",
        "caminos",
        "tubería",
        "tuberia",
        "geotécnica",
        "geotecnia",
        "eléctric",
        "electric",
        "mecánic",
        "mecanic",
        "instalaciones",
        "planta",
        "compras",
        "logística",
        "vendedor",
        "comercial",
        "sales",
        "recruiter",
        "rrhh",
        "camarero",
        "fontanero",
        "biometano",
        "agraria",
        "agrónomo",
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
        self.dni = os.getenv("UPV_DNI", "").strip()
        self.pin = os.getenv("UPV_PIN", "").strip()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "es-ES,es;q=0.9,ca;q=0.8",
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

    def check_session(self) -> tuple[bool, str]:
        try:
            import requests

            r = requests.get(
                self.OFFICIAL_APP_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=10
            )
            if r.status_code == 200:
                return True, "ok"
            return False, f"http_{r.status_code}"
        except Exception as e:
            return False, f"error_{str(e)[:20]}"

    async def fetch_jobs(self, startup_deep_scan: bool = False) -> list[JobItem]:
        found_jobs: dict[str, JobItem] = {}
        self.logger.info(
            "Fetching official UPV SIE (Servicio Integrado de Empleo) portal: %s",
            self.OFFICIAL_APP_URL,
        )

        try:
            async with httpx.AsyncClient(headers=getattr(self, "headers", {})) as client:
                r = await client.get(self.OFFICIAL_APP_URL, timeout=12)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                tables = soup.find_all("table")
                if len(tables) >= 3:
                    table = tables[2]  # Table containing official job offers
                    for row in table.find_all("tr"):
                        cols = [
                            c.get_text(strip=True)
                            for c in row.find_all(["td", "th"])
                            if c.get_text(strip=True)
                        ]
                        if len(cols) >= 4 and cols[0].startswith("DL-"):
                            ref = cols[0]
                            title = cols[1]
                            fec_alta = cols[2]
                            fec_fin = cols[3]

                            if not self._is_job_relevant(title):
                                continue

                            job_id = f"upv_{ref.lower()}"
                            job_url = self.OFFICIAL_APP_URL
                            job_obj = JobItem(
                                id=job_id,
                                title=f"[{ref}] {title}",
                                company="Empresa Colaboradora UPV / SIE",
                                location="Tu Ciudad / Entorno Universidad",
                                url=job_url,
                                source=self.source,
                                posted_within_1h=True,
                                description=f"Oferta oficial del Servicio Integrado de Empleo (SIE UPV). Ref: {ref}. Fecha de alta: {fec_alta}. Plazo de inscripción: hasta {fec_fin}.",
                            )
                            found_jobs[job_id] = job_obj
        except Exception as exc:
            self.logger.error(
                "Error fetching UPV SIE jobs from %s: %s", self.OFFICIAL_APP_URL, exc
            )

        self.logger.info(
            "UPV SIE search complete | viable_jobs_found=%d", len(found_jobs)
        )
        return list(found_jobs.values())
