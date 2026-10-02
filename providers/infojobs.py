"""
Módulo proveedor para la extracción de ofertas de empleo de InfoJobs.
Implementa scraping defensivo y llamadas vía Playwright como respaldo para evitar bloqueos.
"""
from __future__ import annotations
import asyncio

import json
import logging
import random
import re
import sys


from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import httpx
from curl_cffi import requests

from utils_stealth import get_stealth_headers

if TYPE_CHECKING:
    from playwright.async_api import Playwright

from config import BotConfig
from matcher import is_job_geographically_viable
from models import JobItem


class InfoJobsProvider:
    """
    Proveedor para extraer y filtrar ofertas de empleo desde InfoJobs.
    Maneja esquivas básicas antibot, analiza payloads JSON embebidos y usa Playwright si es bloqueado.
    """
    source = "infojobs"

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
    DEFAULT_SEARCH_URLS = [
        # 1. madrid & Área Metropolitana
        "https://www.infojobs.net/ofertas-trabajo/madrid/ia",
        "https://www.infojobs.net/ofertas-trabajo/madrid/python",
        "https://www.infojobs.net/ofertas-trabajo/madrid/data-science",
        "https://www.infojobs.net/ofertas-trabajo/madrid/vision-artificial",
        # 2. España / 100% Remoto
        "https://www.infojobs.net/ofertas-trabajo/inteligencia-artificial",
        "https://www.infojobs.net/ofertas-trabajo/python",
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
        """
        Inicializa el proveedor de InfoJobs.

        Args:
            config (BotConfig): Configuraci?n global del bot.
            logger (logging.Logger): Instancia del logger para registrar eventos.
            playwright (Playwright | None, opcional): Instancia de Playwright para resolver bloqueos de CAPTCHA/Kasada.
        """
        self.config = config
        self.logger = logger
        self.playwright = playwright
        self.last_blocked_reason = ""
        self.session = requests.Session(
            impersonate="chrome120",
            proxies={"http": config.proxy_url, "https": config.proxy_url}
            if config.proxy_url
            else None,
        )
        self.session.headers.update(get_stealth_headers())

    def _is_job_relevant(self, title: str) -> bool:
        """
        Determina si el t?tulo de la oferta contiene palabras clave relevantes tecnol?gicas.

        Args:
            title (str): El t?tulo de la oferta de trabajo.

        Returns:
            bool: True si la oferta es relevante, False de lo contrario.
        """
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
        """
        Verifica si la oferta es geogr?ficamente viable (ej. remoto o en zona de inter?s).

        Args:
            location (str): Ubicaci?n de la oferta.
            title (str): T?tulo de la oferta.
            description (str, opcional): Descripci?n de la oferta.

        Returns:
            bool: True si la ubicaci?n es viable, False de lo contrario.
        """
        return is_job_geographically_viable(location, title, description)

    async def check_session(self) -> tuple[bool, str]:
        """
        Comprueba si la sesi?n HTTP puede acceder a InfoJobs sin ser bloqueada.

        Returns:
            tuple[bool, str]: Un par que indica el ?xito (True/False) y un mensaje descriptivo o c?digo de estado.
        """
        try:
            async with httpx.AsyncClient(headers=getattr(self, "headers", {})) as client:
                r = await client.get("https://www.infojobs.net/ofertas-trabajo/inteligencia-artificial", timeout=self.config.timeout_seconds,
            )
            if r.status_code == 200:
                return True, "infojobs_http_200"
            return False, f"infojobs_http_{r.status_code}"
        except Exception as exc:
            return False, f"infojobs_error_{exc}"

    @classmethod
    def _extract_embedded_offers(cls, html: str) -> list[dict[str, Any]]:
        """
        Decodifica el payload JSON de InfoJobs incrustado en el HTML.
        
        Extrae los datos de las ofertas sin depender del renderizado completo del HTML,
        lo que mejora la velocidad y confiabilidad del scraping.

        Args:
            html (str): Contenido HTML de la p?gina.

        Returns:
            list[dict[str, Any]]: Lista de diccionarios con los datos de las ofertas.
        """
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

    async def fetch_jobs(self, startup_deep_scan: bool = False) -> list[JobItem]:
        """
        Extrae y procesa las ofertas de empleo desde InfoJobs.
        
        Utiliza endpoints directos y fallback a Playwright si detecta bloqueos antibot (Kasada/Imperva).

        Args:
            startup_deep_scan (bool, opcional): Si es True, realiza un escaneo profundo en el inicio.

        Returns:
            list[JobItem]: Lista de ofertas de trabajo viables y relevantes.
        """
        now_ts = time.time()
        last_run = getattr(self, "_last_successful_run", 0)
        # Si el tiempo actual es menor al tiempo de bloqueo, omitimos el ciclo para evitar bloqueos prolongados.
        if now_ts < getattr(self, "_playwright_blocked_until", 0):
            self.logger.warning(
                "InfoJobs | Tactical Retreat Active: Skipping cycle to cool down Kasada IP block."
            )
            return []
        # Limitamos la frecuencia de scraping a una vez cada 25-30 minutos aprox (1500s) para no ser detectados.
        if now_ts - last_run < 1500:
            self.logger.info("InfoJobs | Skipping cycle to enforce 30-minute interval.")
            return []
        self._last_successful_run = now_ts
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

        for target_url in urls:
            try:
                await asyncio.sleep(random.uniform(1.2, 3.5))
                async with httpx.AsyncClient(headers=getattr(self, "headers", {})) as client:
                    r = await client.get(target_url, timeout=self.config.timeout_seconds)
                if r.status_code != 200:
                    self.logger.warning(
                        "InfoJobs HTTP %d on URL: %s", r.status_code, target_url
                    )
                    self.last_blocked_reason = f"http_{r.status_code}"
                    continue

                # Estrategia principal: extraer el payload JSON que contiene detalles que no est?n en las tarjetas HTML.
                extracted_any = False
                try:
                    offers = self._extract_embedded_offers(r.text)
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

                            # 1. Enriquecer la descripci?n con la modalidad nativa de teletrabajo de InfoJobs
                            teleworking = off.get("teleworking")
                            if isinstance(teleworking, str) and teleworking:
                                if (
                                    "teletrabajo" in teleworking.lower()
                                    or "remoto" in teleworking.lower()
                                ):
                                    desc += (
                                        "\nModalidad: 100% Remoto (Oficial InfoJobs)"
                                    )
                                elif (
                                    "híbrido" in teleworking.lower()
                                    or "hibrido" in teleworking.lower()
                                ):
                                    desc += "\nModalidad: Híbrido (Oficial InfoJobs)"
                                elif "presencial" in teleworking.lower():
                                    desc += "\nModalidad: Presencial (Oficial InfoJobs)"

                            # 2. Enriquecer con el salario estructurado si la empresa lo ha proporcionado
                            sal_desc = off.get("salaryDescription")
                            if sal_desc:
                                desc += f"\nSalario oficial: {sal_desc}"

                            # 3. Calcular qu? tan reciente es la oferta basado en el campo publishedAt
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
                        "InfoJobs embedded payload could not be decoded: %s", json_err
                    )

                # 2. Estrategia secundaria (Fallback): Parsear mediante BeautifulSoup si la extracci?n del JSON fall?
                if not extracted_any:
                    soup = BeautifulSoup(r.text, "html.parser")
                    anchors = soup.select("a[href*='/of-']")

                    for a in anchors:
                        href = a.get("href", "").strip()
                        title = " ".join(a.get_text(" ", strip=True).split())
                        if not href or not title or len(title) < 5:
                            continue

                        if not href.startswith("http"):
                            href = urljoin("https://www.infojobs.net", href)

                        # Extraer el ID ?nico de la oferta desde la URL
                        m_id = re.search(r"/of-i([a-zA-Z0-9]+)", href)
                        if not m_id:
                            continue
                        job_id = m_id.group(1)

                        if job_id in found_jobs:
                            continue

                        # Deducir la ubicaci?n aproximada a partir de los segmentos de la ruta de la URL
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

                        # Extraer el nombre de la empresa navegando por la jerarqu?a del DOM si est? disponible
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
        if not jobs_list and self.playwright:
            self.logger.warning(
                "InfoJobs returned 0 jobs (likely Kasada/Imperva CAPTCHA block). Falling back to Playwright stealth..."
            )
            jobs_list = await self._fetch_via_playwright(urls)
            if not jobs_list:
                self.last_blocked_reason = "playwright_zero_jobs"


                self._playwright_blocked_until = time.time() + 3600
                self.logger.error(
                    "InfoJobs | Playwright stealth also blocked! Initiating 1-hour tactical retreat for IP."
                )

        self.logger.info(
            "InfoJobs search complete | viable_jobs_found=%d", len(jobs_list)
        )
        return jobs_list

    async def _fetch_via_playwright(self, urls: list[str]) -> list[JobItem]:
        """
        Utiliza Playwright para eludir bloqueos antibot cuando las peticiones HTTP fallan.

        Args:
            urls (list[str]): Lista de URLs de InfoJobs a scrapear.

        Returns:
            list[JobItem]: Lista de ofertas de trabajo viables obtenidas mediante navegador real.
        """

        from utils_stealth import apply_playwright_stealth

        found_jobs: dict[str, JobItem] = {}

        # Solo intentamos con las primeras URLs para no demorar demasiado el proceso en Playwright si hay fallos recurrentes
        attempt_urls = urls[:10]

        try:
            ignored_default_args = ["--enable-automation"]
            if not sys.platform.startswith("linux"):
                ignored_default_args.append("--no-sandbox")

            browser = self.playwright.chromium.launch(
                headless=False,
                ignore_default_args=ignored_default_args,
                proxy={"server": self.config.proxy_url}
                if self.config.proxy_url
                else None,
            )
            context, page = apply_playwright_stealth(browser)

            for target_url in attempt_urls:
                try:
                    await page.goto(
                        target_url,
                        wait_until="domcontentloaded",
                        timeout=self.config.timeout_seconds * 1000,
                    )
                    await page.wait_for_timeout(random.uniform(2000, 4000))

                    html = await page.content()

                    # Intentar extraer el payload JSON tambi?n desde Playwright para consistencia de datos
                    extracted_any = False
                    try:
                        offers = self._extract_embedded_offers(html)
                        if offers:
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

                                sal_desc = off.get("salaryDescription")
                                if sal_desc:
                                    desc += f"\nSalario oficial: {sal_desc}"

                                posted_recent = True
                                pub_at = off.get("publishedAt")
                                if pub_at:
                                    try:
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

                                if len(found_jobs) >= self.config.infojobs_max_results:
                                    break
                    except Exception as e:
                        self.logger.warning("Playwright JSON extraction failed: %s", e)

                    if len(found_jobs) >= self.config.infojobs_max_results:
                        break

                except Exception as e:
                    self.logger.warning(
                        "Playwright failed on URL %s: %s", target_url, e
                    )

            await browser.close()

        except Exception as e:
            self.logger.error("Failed to launch Playwright for InfoJobs: %s", e)

        return list(found_jobs.values())
