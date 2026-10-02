from __future__ import annotations

import json
import logging
import random
import re
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests

from utils_stealth import get_stealth_headers

if TYPE_CHECKING:
    from playwright.sync_api import Playwright

from config import BotConfig
from matcher import is_job_geographically_viable
from models import JobItem


class InfoJobsProvider:
    source = "infojobs"

    VALENCIA_STEMS = [
        "valencia",
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
        "comunidad valenciana",
        "comunitat valenciana",
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

    DEFAULT_SEARCH_URLS = [
        # 1. Valencia & Área Metropolitana (Prioridad Local)
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/ia",
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/python",
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/automatizacion",
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/plc",
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/vision-artificial",
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/deep-learning",
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/data-science",
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/scada",
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/robotica",
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/backend",
        # 2. España / 100% Remoto (Prioridad Nacional)
        "https://www.infojobs.net/ofertas-trabajo/inteligencia-artificial",
        "https://www.infojobs.net/ofertas-trabajo/machine-learning",
        "https://www.infojobs.net/ofertas-trabajo/python",
        "https://www.infojobs.net/ofertas-trabajo/data-engineer",
        # Empresas Específicas de la Fase 1
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/nunsys",
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/edicom",
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/babel",
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/s2-grupo",
        # Empresas Específicas de la Fase 2 (Gigantes en España)
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/ntt-data",
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/minsait",
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/indra",
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/capgemini",
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/gft",
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/seidor",
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/ayesa",
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/inetum",
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/hiberus",
        "https://www.infojobs.net/ofertas-trabajo/[CIUDAD_PRINCIPAL]/grupo-oesia",
    ]

    INITIAL_PROPS_RE = re.compile(
        r'window\.__INITIAL_PROPS__\s*=\s*JSON\.parse\(\s*("(?:\\.|[^"\\])*")\s*\)\s*;?',
        re.DOTALL,
    )

    def __init__(
        self,
        config: BotConfig,
        logger: logging.Logger,
        playwright: Playwright | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        self.playwright = playwright
        self.last_blocked_reason = ""
        self.session = requests.Session(impersonate="chrome")
        self.session.headers.update(get_stealth_headers())

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

    def _is_job_viable(self, location: str, title: str, description: str = "") -> bool:
        return is_job_geographically_viable(location, title, description)

    def check_session(self) -> tuple[bool, str]:
        try:
            r = self.session.get(
                "https://www.infojobs.net/ofertas-trabajo/inteligencia-artificial",
                timeout=self.config.timeout_seconds,
            )
            if r.status_code == 200:
                return True, "infojobs_http_200"
            return False, f"infojobs_http_{r.status_code}"
        except Exception as exc:
            return False, f"infojobs_error_{exc}"

    @classmethod
    def _extract_embedded_offers(cls, html: str) -> list[dict[str, Any]]:
        """Decode InfoJobs' JSON.parse payload without depending on rendered HTML."""
        match = cls.INITIAL_PROPS_RE.search(html)
        if not match:
            return []

        encoded_payload = json.loads(match.group(1))
        payload = json.loads(encoded_payload)
        if not isinstance(payload, dict):
            return []

        offers = payload.get("offers", [])
        return (
            [offer for offer in offers if isinstance(offer, dict)]
            if isinstance(offers, list)
            else []
        )

    def fetch_jobs(self, startup_deep_scan: bool = False) -> list[JobItem]:
        self.last_blocked_reason = ""
        urls = (
            [self.config.infojobs_url]
            if self.config.infojobs_url
            else self.DEFAULT_SEARCH_URLS
        )
        found_jobs: dict[str, JobItem] = {}

        self.logger.info(
            "Fetching InfoJobs listings | URLs=%d target_max=%d",
            len(urls),
            self.config.infojobs_max_results,
        )

        for base_url in urls:
            sep = "&" if "?" in base_url else "?"
            for page_num in range(1, 2):
                target_url = f"{base_url}{sep}orden=feccre&page={page_num}"
                try:
                    time.sleep(random.uniform(1.2, 3.5))

                    html_content = ""
                    if self.playwright:
                        # Use Playwright to bypass DataDome automatically
                        from utils_stealth import apply_playwright_stealth

                        browser = self.playwright.chromium.launch(headless=True)
                        context, page = apply_playwright_stealth(browser)
                        try:
                            page.goto(target_url, wait_until="domcontentloaded")
                            time.sleep(
                                4.5
                            )  # Wait for DataDome JS interstitial to resolve
                            html_content = page.content()
                        finally:
                            context.close()
                            browser.close()
                    else:
                        r = self.session.get(
                            target_url, timeout=self.config.timeout_seconds
                        )
                        if r.status_code != 200:
                            self.logger.warning(
                                "InfoJobs HTTP %d on URL: %s", r.status_code, target_url
                            )
                            continue
                        html_content = r.text

                    # Primary: the server payload includes fields absent from listing cards.
                    extracted_any = False
                    try:
                        offers = self._extract_embedded_offers(html_content)
                        if offers:
                            added_from_payload = 0

                            for off in offers:
                                job_id = off.get("code") or ""
                                title = " ".join((off.get("title") or "").split())
                                company_name = (
                                    off.get("companyName")
                                    or "Empresa confidencial / No indicada"
                                )
                                city = off.get("city") or "España"
                                desc = off.get("description") or ""
                                link = off.get("link") or ""

                                # 1. Enrich with native teleworking modality
                                teleworking = off.get("teleworking")
                                if isinstance(teleworking, str) and teleworking:
                                    if (
                                        "teletrabajo" in teleworking.lower()
                                        or "remoto" in teleworking.lower()
                                    ):
                                        desc += "\nModalidad: 100% Remoto (Oficial InfoJobs)"
                                    elif (
                                        "híbrido" in teleworking.lower()
                                        or "hibrido" in teleworking.lower()
                                    ):
                                        desc += (
                                            "\nModalidad: Híbrido (Oficial InfoJobs)"
                                        )
                                    elif "presencial" in teleworking.lower():
                                        desc += (
                                            "\nModalidad: Presencial (Oficial InfoJobs)"
                                        )

                                # 2. Enrich with structured salary if provided by employer
                                sal_desc = off.get("salaryDescription")
                                if sal_desc:
                                    desc += f"\nSalario oficial: {sal_desc}"

                                # 3. Calculate recency from publishedAt
                                posted_recent = True
                                pub_at = off.get("publishedAt")
                                if pub_at:
                                    try:
                                        # Normalize ISO format
                                        pub_dt = datetime.fromisoformat(
                                            pub_at.replace("Z", "+00:00")
                                        )
                                        age_hours = (
                                            datetime.now(pub_dt.tzinfo) - pub_dt
                                        ).total_seconds() / 3600
                                        posted_recent = age_hours <= 2.0
                                    except Exception:
                                        posted_recent = True

                                if not job_id or not title or len(title) < 5:
                                    continue
                                if link.startswith("//"):
                                    link = "https:" + link
                                elif not link.startswith("http"):
                                    link = urljoin("https://www.infojobs.net", link)

                                if job_id in found_jobs:
                                    continue

                                if not self._is_job_relevant(title):
                                    continue

                                if not self._is_job_viable(city, title, desc):
                                    continue

                                item = JobItem(
                                    id=job_id,
                                    title=title,
                                    company=company_name,
                                    location=city,
                                    url=link,
                                    source=self.source,
                                    posted_within_1h=posted_recent,
                                    description=desc,
                                )
                                found_jobs[job_id] = item
                                extracted_any = True
                                added_from_payload += 1

                                if len(found_jobs) >= self.config.infojobs_max_results:
                                    break
                            self.logger.debug(
                                "InfoJobs embedded payload | offers=%d viable_added=%d",
                                len(offers),
                                added_from_payload,
                            )
                    except (json.JSONDecodeError, TypeError, ValueError) as json_err:
                        self.logger.warning(
                            "InfoJobs embedded payload could not be decoded: %s",
                            json_err,
                        )

                    # 2. Fallback: Parse via HTML BeautifulSoup if JSON extraction was empty
                    if not extracted_any:
                        soup = BeautifulSoup(html_content, "html.parser")
                        anchors = soup.select("a[href*='/of-']")

                        for a in anchors:
                            href = a.get("href", "").strip()
                            title = " ".join(a.get_text(" ", strip=True).split())
                            if not href or not title or len(title) < 5:
                                continue

                            if not href.startswith("http"):
                                href = urljoin("https://www.infojobs.net", href)

                            # Extract ID from /of-iXXXXXX
                            m_id = re.search(r"/of-i([a-zA-Z0-9]+)", href)
                            if not m_id:
                                continue
                            job_id = m_id.group(1)

                            if job_id in found_jobs:
                                continue

                            # Extract location guess from URL path
                            path_parts = urlparse(href).path.strip("/").split("/")
                            loc_guess = (
                                path_parts[0].replace("-", " ").title()
                                if path_parts
                                else "España"
                            )

                            if not self._is_job_relevant(title):
                                continue

                            if not self._is_job_viable(loc_guess, title):
                                continue

                            # Extract company name if available in the card hierarchy
                            company_name = "Empresa confidencial / No indicada"
                            parent = (
                                a.find_parent("li")
                                or a.find_parent("article")
                                or a.find_parent("div")
                            )
                            if parent:
                                comp_el = parent.select_one(
                                    "a[href*='/empresa-'], [class*='subtitle'], [class*='author'], [class*='company']"
                                )
                                if comp_el:
                                    clean_comp = " ".join(
                                        comp_el.get_text(" ", strip=True).split()
                                    )
                                    if clean_comp and clean_comp.lower() not in [
                                        "infojobs",
                                        "ofertas de empleo",
                                    ]:
                                        company_name = clean_comp

                            item = JobItem(
                                id=job_id,
                                title=title,
                                company=company_name,
                                location=loc_guess,
                                url=href,
                                source=self.source,
                                posted_within_1h=True,
                            )
                            found_jobs[job_id] = item

                            if len(found_jobs) >= self.config.infojobs_max_results:
                                break

                except Exception as exc:
                    self.logger.warning(
                        "Error fetching InfoJobs URL %s: %s", target_url, exc
                    )

        jobs_list = list(found_jobs.values())
        self.logger.info(
            "InfoJobs search complete | viable_jobs_found=%d", len(jobs_list)
        )
        return jobs_list
