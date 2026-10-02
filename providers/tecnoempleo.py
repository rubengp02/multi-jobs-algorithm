from __future__ import annotations

import asyncio
import logging
import re

import httpx
from bs4 import BeautifulSoup
from playwright.sync_api import Playwright

from config import BotConfig
from matcher import is_job_geographically_viable
from models import JobItem
from utils_stealth import get_stealth_headers


class TecnoempleoProvider:
    source = "tecnoempleo"

    MADRID_STEMS = [
        "madrid",
        "valència",
        "paterna",
        "llíria",
        "lliria",
        "almussafes",
        "almusafes",
        "sagunto",
        "sagunt",
        "manises",
        "museros",
        "castellón",
        "castelló",
        "xirivella",
        "chirivella",
        "picanya",
        "albalat dels sorells",
        "riba-roja",
        "ribarroja",
        "torrent",
        "torrente",
        "alboraya",
        "alzira",
        "gandia",
        "ontinyent",
        "guadasequies",
        "comunidad madridna",
        "comunitat madridna",
    ]

    REMOTE_OVERRIDE_STEMS = [
        "100% remoto",
        "100% remote",
        "full remote",
        "teletrabajo 100%",
        "100% teletrabajo",
        "remoto 100%",
    ]

    REMOTE_STEMS = [
        "remoto",
        "remota",
        "remote",
        "teletrabajo",
        "teletrabajar",
        "wfh",
        "work from home",
        "a distancia",
        "distancia",
    ]

    HYBRID_STEMS = [
        "híbrido",
        "hibrido",
        "hybrid",
        "presencial",
        "onsite",
        "on-site",
        "modalidad presencial",
        "asistencia a oficina",
        "días presenciales",
        "dias presenciales",
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
        "cad",
        "cam",
        "cae",
        "embedded",
        "embebido",
        "firmware",
        "mlops",
        "devops",
    ]

    EXCLUDE_ROLE_STEMS = [
        "vendedor",
        "comercial",
        "sales",
        "facility",
        "medioambiente",
        "medio ambiente",
        "formador",
        "recruiter",
        "rrhh",
        "recursos humanos",
        "legal",
        "camarero",
        "fontanero",
        "electricista",
        "planta",
        "compras",
        "logística",
        "cadena de suministro",
        "hidráulic",
        "hidraulic",
        "civil",
        "caminos",
        "climatizac",
        "tubería",
        "geotécnic",
        "sap",
        "cobol",
        "abap",
        "beca",
        "becario",
        "prácticas",
        "practicas",
    ]

    SEARCH_URLS = [
        "https://www.tecnoempleo.com/ofertas-trabajo/?te=inteligencia+artificial",
        "https://www.tecnoempleo.com/ofertas-trabajo/?te=python",
        "https://www.tecnoempleo.com/ofertas-trabajo/?te=machine+learning",
        "https://www.tecnoempleo.com/ofertas-trabajo/?te=deep+learning",
        "https://www.tecnoempleo.com/ofertas-trabajo/?te=computer+vision",
        "https://www.tecnoempleo.com/ofertas-trabajo/?te=vision+artificial",
        "https://www.tecnoempleo.com/ofertas-trabajo/?te=data+engineer",
        "https://www.tecnoempleo.com/ofertas-trabajo/?te=fastapi",
        "https://www.tecnoempleo.com/ofertas-trabajo/?te=automatizacion",
        "https://www.tecnoempleo.com/ofertas-trabajo/?te=plc",
        "https://www.tecnoempleo.com/ofertas-trabajo/?te=scada",
        "https://www.tecnoempleo.com/ofertas-trabajo/?pr=madrid",
        "https://www.tecnoempleo.com/ofertas-trabajo/?pr=remoto",
        "https://www.tecnoempleo.com/ofertas-trabajo/?urg=1",
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
        self.headers = get_stealth_headers()

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

    def _is_job_viable(self, location: str, title: str, card_text: str = "") -> bool:
        return is_job_geographically_viable(location, title, card_text)

    def check_session(self) -> tuple[bool, str]:
        try:
            with httpx.Client(headers=self.headers) as client:
                r = client.get(
                    "https://www.tecnoempleo.com/ofertas-trabajo/?te=python",
                    timeout=self.config.timeout_seconds,
                )
                if r.status_code == 200:
                    return True, "tecnoempleo_http_200"
                return False, f"tecnoempleo_http_{r.status_code}"
        except Exception as exc:
            return False, f"tecnoempleo_error_{exc}"

    async def fetch_jobs(self) -> list[JobItem]:
        self.last_blocked_reason = ""
        found_jobs: dict[str, JobItem] = {}

        self.logger.info(
            "Fetching Tecnoempleo listings | URLs=%d", len(self.SEARCH_URLS)
        )

        client = httpx.AsyncClient(headers=self.headers)
        for target_url in self.SEARCH_URLS:
            try:
                await asyncio.sleep(0.4)
                r = await client.get(target_url, timeout=self.config.timeout_seconds)
                if r.status_code != 200:
                    self.logger.warning(
                        "Tecnoempleo HTTP %d on URL: %s", r.status_code, target_url
                    )
                    continue

                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if "/rf-" not in href:
                        continue

                    title = " ".join(a.get_text(" ", strip=True).split())
                    if (
                        not title
                        or len(title) < 5
                        or title in ["Ofertas de Trabajo", "Buscar Empleo"]
                    ):
                        continue

                    # Extract ID from /rf-([a-f0-9]+)
                    m_id = re.search(r"/rf-([a-f0-9]+)", href)
                    if not m_id:
                        continue
                    job_id = m_id.group(1)

                    if job_id in found_jobs:
                        continue

                    parent = a.find_parent(
                        "div",
                        class_=lambda c: (
                            c
                            and (
                                "p-3" in c
                                or "p-4" in c
                                or "border" in c
                                or "item" in c
                                or "card" in c
                            )
                        ),
                    )
                    card_text = parent.get_text(" ", strip=True) if parent else ""

                    # Extract company
                    company = "Tecnoempleo"
                    if parent:
                        comp_a = parent.select_one(
                            "a[href*='/empresa/']"
                        ) or parent.select_one("a[href*='/profesionales/']")
                        if comp_a:
                            comp_name = comp_a.get_text(strip=True)
                            if comp_name and len(comp_name) > 2:
                                company = comp_name
                        else:
                            lines = [
                                s.strip() for s in parent.stripped_strings if s.strip()
                            ]
                            if (
                                len(lines) >= 2
                                and lines[0] == title
                                and len(lines[1]) > 1
                                and not lines[1].startswith("100%")
                                and not lines[1].startswith("(")
                            ):
                                company = lines[1]
                            elif (
                                len(lines) >= 3
                                and lines[1] == title
                                and len(lines[2]) > 1
                                and not lines[2].startswith("100%")
                                and not lines[2].startswith("(")
                            ):
                                company = lines[2]

                    # Parse recency (prevent sending old jobs)
                    if re.search(
                        r"\b(?:[2-9]|\d{2,})\s+(?:d[íi]as?|semanas?|meses?)\b",
                        card_text,
                        re.IGNORECASE,
                    ) or re.search(
                        r"\bhace\s+1\s+(?:semana|mes)\b", card_text, re.IGNORECASE
                    ):
                        continue

                    is_fresh = bool(
                        re.search(
                            r"\b(?:minutos?|horas?|hoy|just now)\b",
                            card_text,
                            re.IGNORECASE,
                        )
                    )

                    # Extract location & modality
                    location = "España"
                    if any(v in card_text.lower() for v in self.MADRID_STEMS):
                        location = "madrid"
                    elif (
                        "100% remoto" in card_text.lower()
                        or "remoto" in card_text.lower()
                    ):
                        location = "100% Remoto"

                    if not self._is_job_relevant(title):
                        continue

                    if not self._is_job_viable(location, title, card_text):
                        continue

                    link = href
                    if not link.startswith("http"):
                        link = (
                            "https://www.tecnoempleo.com" + link
                            if link.startswith("/")
                            else f"https://www.tecnoempleo.com/{link}"
                        )

                    item = JobItem(
                        id=job_id,
                        title=title,
                        company=company,
                        location=location,
                        url=link,
                        source=self.source,
                        posted_within_1h=is_fresh,
                    )
                    found_jobs[job_id] = item

                    max_target = getattr(self.config, "tecnoempleo_max_results", 30)
                    if len(found_jobs) >= max_target:
                        break

            except Exception as exc:
                self.logger.warning(
                    "Error fetching Tecnoempleo from %s: %s", target_url, exc
                )

        self.logger.info(
            "Tecnoempleo search complete | viable_jobs_found=%d", len(found_jobs)
        )
        await client.aclose()
        return list(found_jobs.values())
