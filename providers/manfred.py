"""
Módulo proveedor para la extracción de ofertas de empleo de Manfred.
Obtiene los listados a través del sitemap XML para mayor eficiencia.
"""
from __future__ import annotations

import logging
import re

import httpx
from utils_stealth import get_stealth_headers
from playwright.async_api import Playwright

from matcher import is_job_geographically_viable
from config import BotConfig
from models import JobItem


class ManfredProvider:
    """
    Proveedor para extraer ofertas de empleo desde Manfred.
    
    Analiza el sitemap XML de ofertas para encontrar los trabajos más recientes
    y utiliza expresiones regulares para deducir los roles y empresas desde los slugs.
    """
    source = "manfred"

    MADRID_AREA_STEMS = [
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

    SITEMAP_URL = "https://www.getmanfred.com/sitemap-offers.xml"

    def __init__(
        self,
        config: BotConfig,
        logger: logging.Logger,
        playwright: Playwright | None = None,
    ) -> None:
        """
        Inicializa el proveedor de Manfred.

        Args:
            config (BotConfig): Configuración global del bot.
            logger (logging.Logger): Instancia del logger para registrar eventos.
            playwright (Playwright | None, opcional): Instancia de Playwright (no utilizada aquí pero mantenida por interfaz).
        """
        self.config = config
        self.logger = logger
        self.last_blocked_reason = ""
        self.headers = get_stealth_headers()

    def _is_job_relevant(self, title: str) -> bool:
        """
        Determina si el título de la oferta contiene palabras clave relevantes tecnológicas.
        Ignora roles que pertenecen a la lista de exclusión.

        Args:
            title (str): El título de la oferta de trabajo.

        Returns:
            bool: True si la oferta es relevante según las palabras clave, False de lo contrario.
        """
        t_lower = title.lower()
        # Verificar si el rol está en la lista de excluidos
        if any(ex in t_lower for ex in self.EXCLUDE_ROLE_STEMS):
            return False

        # Verificar si contiene alguna de las tecnologías o roles principales
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
        Verifica si la oferta es geográficamente viable (ej. remoto o en zona de interés).

        Args:
            location (str): Ubicación de la oferta.
            title (str): Título de la oferta.
            description (str, opcional): Descripción de la oferta.

        Returns:
            bool: True si la ubicación es viable, False de lo contrario.
        """
        return is_job_geographically_viable(location, title, description)

    def check_session(self) -> tuple[bool, str]:
        """
        Comprueba si la sesión HTTP puede acceder a la página de ofertas de Manfred sin ser bloqueada.

        Returns:
            tuple[bool, str]: Un par que indica el éxito (True/False) y un mensaje descriptivo o código de estado.
        """
        try:
            import httpx
            with httpx.Client() as client:
                # Realiza una petición GET para comprobar la disponibilidad del servidor
                r = client.get(
                    "https://www.getmanfred.com/es/ofertas-empleo",
                    headers=self.headers,
                    timeout=self.config.timeout_seconds,
                )
                if r.status_code == 200:
                    return True, "manfred_http_200"
                return False, f"manfred_http_{r.status_code}"
        except Exception as exc:
            return False, f"manfred_error_{exc}"

    async def fetch_jobs(self, startup_deep_scan: bool = False) -> list[JobItem]:
        """
        Extrae y procesa las ofertas de empleo desde el sitemap XML de Manfred.
        Deduce roles y empresas a partir del slug de la URL.

        Args:
            startup_deep_scan (bool, opcional): Indica si se debe realizar un escaneo profundo al inicio. Por defecto es False.

        Returns:
            list[JobItem]: Lista de objetos JobItem representando las ofertas relevantes y viables encontradas.
        """
        self.last_blocked_reason = ""
        found_jobs: dict[str, JobItem] = {}

        self.logger.info("Fetching Manfred tech job sitemap...")

        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=self.config.timeout_seconds) as client:
                r = await client.get(self.SITEMAP_URL)
                if r.status_code != 200:
                    self.logger.warning("Manfred sitemap HTTP %d", r.status_code)
                    return []

                # Extraer todas las URLs de ofertas del sitemap
                urls = re.findall(
                    r"<loc>(https://www.getmanfred.com/ofertas-empleo/[^<]+)</loc>", r.text
                )
                self.logger.info("Manfred sitemap parsed | total_urls=%d", len(urls))

                # Inspeccionar las 40 ofertas más recientes para agilizar el procesamiento
                for url in urls[:40]:
                    # Formato esperado: https://www.getmanfred.com/ofertas-empleo/<id>/<slug>
                    m = re.search(r"/ofertas-empleo/(\d+)/(.+)", url)
                    if not m:
                        continue

                    job_id = m.group(1)
                    slug = m.group(2)

                    # Limpiar sufijos de fecha del slug (ej. -oct23) para mejor legibilidad
                    clean_slug = re.sub(
                        r"-(?:ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\d{2}$",
                        "",
                        slug,
                        flags=re.IGNORECASE,
                    )
                    slug_parts = clean_slug.split("-")
                    role_keywords = [
                        "developer",
                        "engineer",
                        "lead",
                        "architect",
                        "qa",
                        "data",
                        "analyst",
                        "consultant",
                        "devops",
                        "specialist",
                        "frontend",
                        "backend",
                        "fullstack",
                        "net",
                        "python",
                        "java",
                        "ai",
                        "ia",
                        "senior",
                        "junior",
                        "mid",
                    ]
                    
                    # Intentar inferir dónde termina el nombre de la empresa y dónde empieza el rol
                    split_idx = len(slug_parts) - 1
                    for i, p in enumerate(slug_parts):
                        if p.lower() in role_keywords and i > 0:
                            split_idx = i
                            break
                    comp_parts = slug_parts[:split_idx]
                    role_parts = slug_parts[split_idx:]
                    company_guess = (
                        " ".join(comp_parts).title() if comp_parts else "Empresa Tech"
                    )
                    title_guess = (
                        " ".join(role_parts).title()
                        if role_parts
                        else " ".join(slug_parts).title()
                    )

                    # Filtrar por relevancia tecnológica
                    if not self._is_job_relevant(title_guess):
                        continue

                    # Filtrar por viabilidad geográfica (Manfred asume 100% Remoto por defecto en este bloque)
                    if not self._is_job_viable("100% Remoto", title_guess):
                        continue

                    item = JobItem(
                        id=f"manfred_{job_id}",
                        title=title_guess,
                        company=company_guess,
                        location="100% Remoto (España)",
                        url=url,
                        source=self.source,
                        posted_within_1h=True,
                    )
                    found_jobs[job_id] = item

                    # Limitar a 15 trabajos encontrados para evitar sobrecarga
                    if len(found_jobs) >= 15:
                        break

        except Exception as exc:
            self.logger.warning("Error fetching Manfred: %s", exc)

        jobs_list = list(found_jobs.values())
        self.logger.info(
            "Manfred search complete | viable_jobs_found=%d", len(jobs_list)
        )
        return jobs_list
