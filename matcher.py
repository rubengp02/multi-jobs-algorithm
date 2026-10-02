from __future__ import annotations

import json
import os
import re
from typing import Any

from business_rules import (
    DENSE_STACK_BONUS,
    FALLBACK_SALARY,
    PRODUCT_COMPANY_PREMIUM,
    REMOTE_PREMIUM,
    SALARY_RULES,
)
from models import JobItem
from relevance import evaluate_relevance

RULES_PATH = os.path.join(os.path.dirname(__file__), "config", "rules.json")
if not os.path.exists(RULES_PATH):
    raise FileNotFoundError("❌ ERROR CRÍTICO: No se ha encontrado config/rules.json.\nPor favor, copia o renombra 'config/rules.example.json' a 'config/rules.json' y rellénalo con tu Stack Tecnológico y zona geográfica antes de iniciar el bot.")

with open(RULES_PATH, "r", encoding="utf-8") as f:
    RULES = json.load(f)
KNOWN_CONSULTANCIES = RULES["KNOWN_CONSULTANCIES"]
TECH_TOOLS_CATALOG = RULES["TECH_TOOLS_CATALOG"]
PRIMARY_AREA = RULES["PRIMARY_AREA"]
OTHER_CITIES = RULES["OTHER_CITIES"]
REMOTE_KEYWORDS = RULES["REMOTE_KEYWORDS"]

# Direct-evidence catalog. A label is returned only when an offer names the tool,
# platform, language, or technology family itself; role names never imply a stack.

PROFILE_CORE_TERMS = {
    "ai": 15,
    "ia": 15,
    "machine learning": 20,
    "computer vision": 20,
    "vision artificial": 20,
    "visión artificial": 20,
    "deep learning": 20,
    "llm": 25,
    "rag": 25,
    "generative": 15,
    "generativa": 15,
    "data scientist": 20,
    "data engineer": 20,
    "python": 20,
    "fastapi": 15,
    "mantenimiento predictivo": 20,
    "predictive maintenance": 20,
    "automatización": 15,
    "automatizacion": 15,
    "opencv": 15,
    "pytorch": 20,
    "tensorflow": 15,
}


def extract_salary(text: str) -> str:
    """
    Analiza el texto de la oferta y extrae el rango salarial si está publicado explícitamente.
    Normaliza y formatea el resultado a rangos anuales en euros.
    
    Args:
        text (str): El texto a analizar.
        
    Returns:
        str: El rango salarial o el nivel de seniority extraído.
    """
    reference = maximum_years if maximum_years is not None else minimum_years
    if reference is None:
        return "No especificado"
    if reference <= 2:
        return "Junior"
    if reference <= 4:
        return "Mid"
    if reference <= 7:
        return "Senior"
    return "Lead / Principal"


def _experience_requirement(context: str) -> str:
    """
    Determina si la experiencia es 'Valorada', 'Requerida' o 'Indicada' basado en el contexto.

    Args:
        context (str): Fragmento de texto circundante a la mención de años.

    Returns:
        str: El nivel de requerimiento deducido.
    """
    if re.search(
        r"\b(se\s+valorar[aá]|deseable|preferible|plus|nice[- ]to[- ]have|would\s+be\s+a\s+plus)\b",
        context,
        re.IGNORECASE,
    ):
        return "Valorada"
    if re.search(
        r"\b(se\s+requiere|requisito|imprescindible|obligatori[oa]|must\s+have|required|minimum|m[ií]nimo|al\s+menos|at\s+least)\b",
        context,
        re.IGNORECASE,
    ):
        return "Requerida"
    return "Indicada"


def _experience_evidence(text: str, start: int, end: int) -> str:
    """
    Conserva un fragmento de texto corto y legible como evidencia para el historial o la alerta.

    Args:
        text (str): El texto completo.
        start (int): Índice de inicio.
        end (int): Índice de fin.

    Returns:
        str: El fragmento de texto de evidencia.
    """
    left = max(0, text.rfind(".", 0, start) + 1)
    right_marker = text.find(".", end)
    right = len(text) if right_marker < 0 else right_marker + 1
    return " ".join(text[left:right].split())[:280]


def _is_company_experience_claim(text: str, start: int) -> bool:
    """
    Rechaza afirmaciones sobre la historia de la empresa, como "empresa con 20 años de experiencia".

    Args:
        text (str): El texto a analizar.
        start (int): El índice inicial de la mención de años.

    Returns:
        bool: True si la mención pertenece a la empresa, False en caso contrario.
    """
    prefix = text[max(0, start - 120) : start].lower()
    return bool(
        re.search(
            r"\b(?:empresa|compa[ñn][ií]a|consultora|organizaci[oó]n|equipo)"
            r"(?:\s+\w+){0,8}\s+(?:con|de)\s*$|"
            r"\b(?:llevamos|contamos\s+con|trayectoria\s+de)\b[^.]{0,70}$",
            prefix,
            re.IGNORECASE,
        )
    )


def extract_experience_details(text: str) -> dict[str, Any]:
    """
    Extrae los requisitos explícitos de experiencia sin inventar números.

    El mismo analizador es utilizado por todos los proveedores después del enriquecimiento de la descripción.
    El campo ``evidence`` permite auditar el valor mostrado en Telegram.

    Args:
        text (str): El texto de la oferta.

    Returns:
        dict[str, Any]: Diccionario con los detalles de la experiencia extraída.
    """
    empty: dict[str, Any] = {
        "minimum_years": None,
        "maximum_years": None,
        "level": "No especificado",
        "requirement": "No especificada",
        "skills": [],
        "evidence": "",
        "display": "¿?",
    }
    if not text:
        return empty

    lowered = text.lower()
    no_experience = re.search(
        r"\b(sin\s+experiencia(?:\s+previa)?|no\s+se\s+requiere\s+experiencia|no\s+es\s+necesaria\s+experiencia|no\s+requerida|primer\s+empleo|reci[ée]n\s+graduad[oa]|fresh\s+graduate|entry[- ]?level)\b",
        lowered,
    )
    if no_experience:
        evidence = _experience_evidence(
            text, no_experience.start(), no_experience.end()
        )
        return {
            **empty,
            "minimum_years": 0,
            "maximum_years": 1,
            "level": "Entry",
            "requirement": "No requerida",
            "evidence": evidence,
            "display": "Sin experiencia previa (0-1 años / Entry)",
        }

    internship_matches = list(
        re.finditer(
            r"\b(pr[áa]cticas|beca|becari[oa]|intern|internship|trainee)\b", lowered
        )
    )
    if internship_matches:
        valid_internship = False
        evidence = ""
        for m in internship_matches:
            start = max(0, m.start() - 25)
            end = min(len(lowered), m.end() + 25)
            window = lowered[start:end]
            if not re.search(
                r"(buenas|mejores|best)\s+pr[áa]cticas", window
            ) and not re.search(r"beca\s+(comedor|transporte|comida)", window):
                valid_internship = True
                evidence = _experience_evidence(text, m.start(), m.end())
                break
        if valid_internship:
            return {
                **empty,
                "minimum_years": 0,
                "maximum_years": 0,
                "level": "Entry",
                "requirement": "No requerida",
                "evidence": evidence,
                "display": "Prácticas / Beca (0 años)",
            }

    patterns = (
        r"\b(?P<min>1[0-5]|[0-9])\s*(?:-|–|hasta|al|a|y|to)\s*(?P<max>1[0-5]|[0-9])\s*(?:a[ñn]os?|years?)\b",
        r"\b(?:entre\s+)?(?P<min>1[0-5]|[0-9])\s*(?:-|–|hasta|al|a|y|to)\s*(?P<max>1[0-5]|[0-9])\s*(?:a[ñn]os?|years?)\s*(?:de\s+)?(?:experiencia|experience)?",
        r"\b(?:experiencia|experience)\s*(?:m[ií]nima|required|demostrable|previa)?\s*(?:de|of)?\s*(?P<min>1[0-5]|[0-9])\s*(?:\+)?\s*(?:a[ñn]os?|years?)\b",
        r"(?:al\s+menos|m[íi]nimo|min\.?|a\s+partir\s+de|m[áa]s\s+de|at\s+least|minimum|over|more\s+than|\+)\s*(?P<min>1[0-5]|[0-9])\s*(?:\+)?\s*(?:a[ñn]os?|years?)\b",
        r"\b(?P<min>1[0-5]|[0-9])\s*\+\s*(?:a[ñn]os?|years?)\b",
        r"\b(?P<min>1[0-5]|[0-9])\s*(?:a[ñn]os?|years?)\s*(?:de\s+)?(?:experiencia|experience)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, lowered, re.IGNORECASE)
        if not match:
            continue
        if _is_company_experience_claim(text, match.start()):
            continue
        minimum = int(match.group("min"))
        maximum_raw = match.groupdict().get("max")
        maximum = int(maximum_raw) if maximum_raw is not None else None
        evidence = _experience_evidence(text, match.start(), match.end())
        context = text[max(0, match.start() - 160) : min(len(text), match.end() + 160)]
        level = _experience_level(minimum, maximum)
        if maximum is not None:
            display = f"{minimum}-{maximum} años ({level})"
        elif minimum <= 1:
            display = f"Al menos {minimum} año ({level})"
        elif minimum <= 2:
            display = f"{minimum} años (Junior / Mid)"
        elif minimum <= 4:
            display = f"{minimum}-{minimum + 2} años ({level})"
        else:
            display = f"+{minimum} años ({level})"
        return {
            **empty,
            "minimum_years": minimum,
            "maximum_years": maximum,
            "level": level,
            "requirement": _experience_requirement(context),
            "skills": extract_tech_stack(context),
            "evidence": evidence,
            "display": display,
        }

    seniority = re.search(
        r"\b(lead|principal|staff|tech lead|team lead|director|head of|manager|arquitecto|architect|senior|sr\.?|experto|expert|semi[- ]?senior|mid[- ]?level|mid|ssr|intermedio|junior|jr\.?|graduate|early career)\b",
        lowered,
    )
    if seniority:
        token = seniority.group(1).lower()
        if token in {
            "lead",
            "principal",
            "staff",
            "tech lead",
            "team lead",
            "director",
            "head of",
            "manager",
            "arquitecto",
            "architect",
        }:
            display, level = "+5-8 años (Lead / Principal)", "Lead / Principal"
        elif token in {"senior", "sr.", "experto", "expert"} or token.startswith("sr"):
            display, level = "3-5+ años (Senior)", "Senior"
        elif token in {"semi-senior", "mid-level", "mid", "ssr", "intermedio"}:
            display, level = "2-4 años (Mid)", "Mid"
        else:
            display, level = "0-2 años (Junior)", "Junior"
        return {
            **empty,
            "level": level,
            "requirement": "Indicada",
            "evidence": _experience_evidence(text, seniority.start(), seniority.end()),
            "display": display,
        }
    return empty


def extract_experience(text: str) -> str:
    """
    Extractor generalizable de los años exactos de experiencia requeridos y el seniority.
    Devuelve formatos claros como:
    - 'Sin experiencia previa (0-1 años / Entry)'
    - 'Prácticas / Beca (0 años)'
    - '1-2 años (Junior)'
    - 'Al menos 1 año (Junior)'
    - '2-4 años (Mid)'
    - '3-5 años (Mid / Senior)'
    - '+5 años (Senior)'
    - '+8 años (Lead / Principal)'
    - '¿?' (cuando no se especifica)
    
    Args:
        text (str): El texto de la oferta.
        
    Returns:
        str: El texto formateado con la experiencia.
    """
    return str(extract_experience_details(text)["display"])


def _named_features(text: str, catalog: list[tuple[str, list[str]]]) -> list[str]:
    """
    Devuelve solo las etiquetas con evidencia textual directa, preservando el orden del catálogo.

    Args:
        text (str): El texto a analizar.
        catalog (list[tuple[str, list[str]]]): Lista de tuplas (etiqueta, patrones regex).

    Returns:
        list[str]: Lista con las etiquetas encontradas.
    """
    found: list[str] = []
    for label, patterns in catalog:
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
            found.append(label)
    return found


def extract_contract_types(text: str) -> list[str]:
    """
    Extrae los tipos de contrato mencionados en la oferta.

    Args:
        text (str): El texto a analizar.

    Returns:
        list[str]: Lista de tipos de contrato encontrados.
    """
    return _named_features(
        text,
        [
            (
                "Indefinido",
                [
                    r"\bcontrato\s+indefinido\b",
                    r"\bindefinid[oa]\b",
                    r"\bpermanent\s+contract\b",
                ],
            ),
            (
                "Temporal",
                [r"\bcontrato\s+temporal\b", r"\btemporal\b", r"\bfixed[- ]term\b"],
            ),
            ("Fijo discontinuo", [r"\bfij[oa]\s+discontinu[oa]\b"]),
            (
                "Practicas / Beca",
                [
                    r"(?<!buenas\s)(?<!mejores\s)(?<!best\s)\bpr[áa]cticas\b",
                    r"\bbeca\b(?!\scomedor)(?!\scomida)",
                    r"\binternship\b",
                    r"\btrainee\b",
                ],
            ),
            (
                "Freelance / Autonomo",
                [r"\baut[oó]nom[oa]\b", r"\bfreelance\b", r"\bcontractor\b"],
            ),
            (
                "Obra y servicio",
                [r"\bobra\s+y\s+servicio\b", r"\bproject[- ]based\s+contract\b"],
            ),
        ],
    )


def extract_work_schedules(text: str) -> list[str]:
    """
    Extrae los horarios de trabajo mencionados en la oferta.

    Args:
        text (str): El texto a analizar.

    Returns:
        list[str]: Lista de horarios encontrados.
    """
    return _named_features(
        text,
        [
            ("Jornada completa", [r"\bjornada\s+completa\b", r"\bfull[- ]time\b"]),
            ("Jornada parcial", [r"\bjornada\s+parcial\b", r"\bpart[- ]time\b"]),
            (
                "Jornada intensiva",
                [r"\bjornada\s+intensiva\b", r"\bcompressed\s+workweek\b"],
            ),
            (
                "Horario flexible",
                [
                    r"\bhorario\s+flexible\b",
                    r"\bflexible\s+hours?\b",
                    r"\bflexibilidad\s+horaria\b",
                ],
            ),
            ("Turnos", [r"\bturnos?\b", r"\bshift\s+work\b", r"\brotativ[oa]s?\b"]),
            ("Guardias", [r"\bguardias?\b", r"\bon[- ]call\b"]),
            (
                "Semana de 4 dias",
                [r"\bsemana\s+de\s+4\s+d[ií]as\b", r"\bfour[- ]day\s+week\b"],
            ),
        ],
    )


def extract_education_requirements(text: str) -> list[str]:
    """
    Extrae los requisitos educativos mencionados en la oferta.

    Args:
        text (str): El texto a analizar.

    Returns:
        list[str]: Lista de requisitos educativos encontrados.
    """
    return _named_features(
        text,
        [
            ("Doctorado", [r"\bdoctorad[oa]\b", r"\bph\.?d\b"]),
            ("Master", [r"\bm[aá]ster\b", r"\bmaster'?s\s+degree\b"]),
            (
                "Grado universitario",
                [
                    r"\bgrado\s+(?:en|universitario)\b",
                    r"\bdegree\s+in\b",
                    r"\bbachelor'?s\s+degree\b",
                ],
            ),
            (
                "Ingenieria",
                [
                    r"\bingenier[ií]a\s+(?:en|industrial|inform[aá]tica|telecomunicaciones)\b",
                    r"\bengineering\s+degree\b",
                ],
            ),
            (
                "FP / Ciclo formativo",
                [
                    r"\bformaci[oó]n\s+profesional\b",
                    r"\bfp\b",
                    r"\bciclo\s+formativo\b",
                    r"\bvocational\s+training\b",
                ],
            ),
        ],
    )


def extract_language_requirements(text: str) -> list[str]:
    """
    Extrae los requisitos de idiomas mencionados en la oferta.

    Args:
        text (str): El texto a analizar.

    Returns:
        list[str]: Lista de idiomas requeridos encontrados.
    """
    languages = [
        ("Ingles", [r"\bingl[eé]s\b", r"\benglish\b"]),
        ("primary_cityno", [r"\bprimary_cityn[oa]\b", r"\bvalenci[aà]\b", r"\bcatal[aà]n\b"]),
        ("Frances", [r"\bfranc[eé]s\b", r"\bfrench\b"]),
        ("Aleman", [r"\balem[aá]n\b", r"\bgerman\b"]),
        ("Italiano", [r"\bitalian[oa]\b", r"\bitalian\b"]),
        ("Portugues", [r"\bportugu[eé]s\b", r"\bportuguese\b"]),
    ]
    return _named_features(text, languages)


def extract_certifications(text: str) -> list[str]:
    """
    Extrae las certificaciones profesionales mencionadas en la oferta.

    Args:
        text (str): El texto a analizar.

    Returns:
        list[str]: Lista de certificaciones encontradas.
    """
    return _named_features(
        text,
        [
            ("AWS Certification", [r"\baws\s+(?:certified|certification)\b"]),
            ("Azure Certification", [r"\bazure\s+(?:certified|certification)\b"]),
            (
                "Google Cloud Certification",
                [r"\bgoogle\s+cloud\s+(?:certified|certification)\b"],
            ),
            ("ITIL", [r"\bitil\b"]),
            ("Scrum", [r"\bscrum\s+(?:master|certified|certification)\b"]),
            ("PMP", [r"\bpmp\b", r"\bproject management professional\b"]),
            ("PRINCE2", [r"\bprince2\b"]),
            ("ISO 27001", [r"\biso\s*27001\b"]),
            ("CISSP", [r"\bcissp\b"]),
            ("CEH", [r"\bceh\b"]),
            ("CCNA", [r"\bccna\b"]),
        ],
    )


def extract_benefits(text: str) -> list[str]:
    """
    Extrae los beneficios ofrecidos mencionados en la oferta.

    Args:
        text (str): El texto a analizar.

    Returns:
        list[str]: Lista de beneficios encontrados.
    """
    return _named_features(
        text,
        [
            ("Seguro medico", [r"\bseguro\s+m[eé]dico\b", r"\bhealth\s+insurance\b"]),
            (
                "Ticket restaurante",
                [
                    r"\bticket\s+restaurant\b",
                    r"\bcheque\s+comida\b",
                    r"\bmeal\s+voucher\b",
                ],
            ),
            (
                "Retribucion flexible",
                [r"\bretribuci[oó]n\s+flexible\b", r"\bflexible\s+compensation\b"],
            ),
            (
                "Formacion",
                [
                    r"\bpresupuesto\s+de\s+formaci[oó]n\b",
                    r"\btraining\s+budget\b",
                    r"\bformaci[oó]n\s+continua\b",
                ],
            ),
            (
                "Vacaciones adicionales",
                [r"\bd[ií]as\s+extra\s+de\s+vacaciones\b", r"\bextra\s+vacation\b"],
            ),
            (
                "Plan de pensiones",
                [r"\bplan\s+de\s+pensiones\b", r"\bpension\s+plan\b"],
            ),
        ],
    )


def extract_architecture_patterns(text: str) -> list[str]:
    """
    Extrae prácticas de arquitectura sin confundirlas con herramientas concretas.

    Args:
        text (str): El texto a analizar.

    Returns:
        list[str]: Lista de patrones arquitectónicos encontrados.
    """
    return _named_features(
        text,
        [
            ("Microservicios", [r"\bmicroservices?\b", r"\bmicroservicios?\b"]),
            ("API REST", [r"\bapi(?:s)?\s+rest\b", r"\brestful\b"]),
            (
                "Event-driven",
                [r"\bevent[- ]driven\b", r"\barquitectura\s+orientada\s+a\s+eventos\b"],
            ),
            ("Serverless", [r"\bserverless\b", r"\bfunctions?\s+as\s+a\s+service\b"]),
            ("Domain-driven design", [r"\bddd\b", r"\bdomain[- ]driven\s+design\b"]),
            ("SOA", [r"\bsoa\b", r"\bservice[- ]oriented\b"]),
        ],
    )


def extract_job_features(
    title: str, description: str = "", location: str = ""
) -> dict[str, Any]:
    """
    Normaliza todos los hechos mostrables de la oferta a partir del texto público.

    Los proveedores no deciden la relevancia aquí. La salida puede estar ausente
    o vacía de forma segura cuando un portal publica solo una tarjeta de lista corta.

    Args:
        title (str): Título de la oferta.
        description (str, optional): Descripción de la oferta. Por defecto es "".
        location (str, optional): Ubicación de la oferta. Por defecto es "".

    Returns:
        dict[str, Any]: Diccionario con todas las características extraídas.
    """
    content = " ".join(part for part in (title, description, location) if part)
    return {
        "experience": extract_experience_details(content),
        "stack": extract_tech_stack(content),
        "architecture": extract_architecture_patterns(content),
        "salary": extract_salary(content),
        "modality": extract_modality(content, location),
        "contract_types": extract_contract_types(content),
        "work_schedules": extract_work_schedules(content),
        "education": extract_education_requirements(content),
        "languages": extract_language_requirements(content),
        "certifications": extract_certifications(content),
        "benefits": extract_benefits(content),
    }


def extract_modality(text: str, location: str = "") -> str:
    """
    Clasificador de modalidad de trabajo de alta confianza, consciente de negaciones 
    y sensible a disfraces híbridos. 
    Prioriza las restricciones híbridas, las divisiones explícitas de días y los 
    patrones remotos negados.

    Args:
        text (str): Texto combinado a analizar.
        location (str, optional): Ubicación declarada en la oferta. Por defecto es "".

    Returns:
        str: La modalidad de trabajo inferida (Presencial, Híbrido, 100% Remoto, etc.).
    """
    full_text = f"{text} {location}".lower()
    loc_lower = location.lower()

    # 1. Check for NEGATED Remote (e.g., "no teletrabajo", "sin opción a remoto", "no se admite teletrabajo")
    negated_remote_patterns = [
        r"\b(?:no|sin)\s+(?:opci[óo]n\s+a\s+|posibilidad\s+de\s+)?(?:teletrabajo|remoto|trabajo\s+en\s+remoto)\b",
        r"\b(?:teletrabajo|remoto)\s+(?:no\s+disponible|no\s+posible|no\s+admitido)\b",
        r"\bno\s+se\s+admite\s+(?:teletrabajo|remoto|trabajo\s+en\s+remoto)\b",
        r"\bno\s+remoto\b",
        r"\bno\s+teletrabajo\b",
        r"\b100%\s*presencial\b",
        r"\bcompletamente\s+presencial\b",
        r"\btotalmente\s+presencial\b",
        r"\bmodalidad\s+100%\s*presencial\b",
        r"\b(?:no|not)\s+(?:remote|telecommute|wfh)\b",
        r"\b100%\s*(?:on-site|onsite|in-office)\b",
        r"\bon-site\s+only\b",
        r"\bfully\s+(?:on-site|onsite|in-office)\b",
    ]
    if any(re.search(pat, full_text, re.IGNORECASE) for pat in negated_remote_patterns):
        return "Presencial"

    # 2. Explicit Multi-Day & Hybrid split patterns
    # e.g. "3 días oficina y 2 casa", "2 días presenciales, 3 teletrabajo"
    if getattr(extract_modality, "_m_split_compiled", None) is None:
        extract_modality._m_split_compiled = re.compile(
            r"(\b[1-4]\s*(?:d[íi]as?|days?)\s*(?:de\s*|en\s*|in\s*|to\s*)?(?:oficina|presencial(?:idad)?|sede|planta|casa|teletrabajo|remoto|office|wfh|onsite))\s*(?:y|,|\/|\+|and)\s*(\b[1-4]\s*(?:d[íi]as?|days?)\s*(?:de\s*|en\s*|in\s*|to\s*)?(?:oficina|presencial(?:idad)?|sede|planta|casa|teletrabajo|remoto|office|wfh|onsite))",
            re.IGNORECASE,
        )
    m_split = extract_modality._m_split_compiled.search(full_text)
    if m_split:
        return "Híbrido"

    # e.g. "2 días de teletrabajo a la semana", "hasta 3 días en remoto", "2 días en oficina"
    m_days = re.search(
        r"\b(?:hasta\s+|m[áa]ximo\s+|m[íi]nimo\s+)?([1-4])\s*(?:d[íi]as?|days?)\s*(?:de\s*|en\s*|a\s*la\s*semana\s*(?:de\s*)?)?(?:oficina|presencial(?:idad)?|presenciales|sede|planta|teletrabajo|remoto|casa|wfh|onsite|office)",
        full_text,
        re.IGNORECASE,
    )
    if m_days and not re.search(
        r"\bd[íi]as?\s+(?:de\s+)?vacaciones\b",
        full_text[max(0, m_days.start() - 10) : min(len(full_text), m_days.end() + 25)],
    ):
        return "Híbrido"

    # Fractional/Pattern splits: "modelo 3/2", "formato 2/3", "4/1", "1/4", "3 días/semana"
    if re.search(r"\b(?:modelo|formato|esquema)?\s*[1-4]\s*[\/]\s*[1-4]\b", full_text):
        return "Híbrido"
    if re.search(r"\b[1-4]\s*d[íi]as?\s*(?:\/|por|a\s*la)\s*semana\b", full_text):
        return "Híbrido"

    # Hybrid keywords & nuances (teletrabajo parcial, ocasional, flexible, teletrabajo con días en oficina, híbridos, % teletrabajo)
    hybrid_signals = [
        r"\bh[íi]brid[oas]{1,2}\b",
        r"\bhybrid\b",
        r"\btrabajo\s+h[íi]brido\b",
        r"\bdays?\s+in\s+office\b",
        r"\bdays?\s+on-site\b",
        r"\bdays?\s+a\s+week\s+in\b",
        r"\b(?:two|three|four)\s+days\b",
        r"\bmodalidad\s+h[íi]brida\b",
        r"\bjornada\s+h[íi]brida\b",
        r"\bformato\s+h[íi]brido\b",
        r"\bteletrabajo\s+parcial\b",
        r"\bteletrabajo\s+ocasional\b",
        r"\bremoto\s+ocasional\b",
        r"\bremoto\s+flexible\b",
        r"\bteletrabajo\s+flexible\b",
        r"\bflexibilidad\s+de\s+teletrabajo\b",
        r"\bopci[óo]n\s+a\s+teletrabajo\b",
        r"\bposibilidad\s+de\s+teletrabajo\b",
        r"\bd[íi]as\s+presenciales\b",
        r"\bd[íi]as\s+en\s+oficina\b",
        r"\basistencia\s+a\s+oficina\b",
        r"\basistencia\s+puntual\b",
        r"\breuniones\s+presenciales\b",
        r"\beventos\s+presenciales\b",
        r"\bvisitas\s+a\s+clientes\b",
        r"\bd[íi]as\s+de\s+teletrabajo\b",
        r"\bflexible\s*\/\s*h[íi]brido\b",
        r"\bteletrabajo\s*\/\s*presencial\b",
        r"\bremoto\s*\/\s*h[íi]brido\b",
        r"\bremoto\s*\/\s*presencial\b",
        r"\bluego\s+h[íi]brido\b",
        r"\btras\s+onboarding\s+h[íi]brido\b",
        r"\b(?:teletrabajo|remoto)\s*(?:al\s*)?[1-9][0-9]?%\b",
        r"\b[1-9][0-9]?%\s*(?:de\s*)?(?:teletrabajo|remoto)\b",
    ]
    if any(re.search(hs, full_text, re.IGNORECASE) for hs in hybrid_signals):
        return "Híbrido"

    # 3. 100% Remote Signals (Strict, unconditional)
    strict_remote_signals = [
        r"\b100%\s*remoto\b",
        r"\b100%\s*remote\b",
        r"\bfull\s*remote\b",
        r"\bteletrabajo\s*100%\b",
        r"\b100%\s*teletrabajo\b",
        r"\bremoto\s*100%\b",
        r"\btotalmente\s+remoto\b",
        r"\bremote-first\b",
        r"\bfull-remote\b",
        r"\bremote\s+in\s+spain\b",
        r"\bremoto\s*\(\s*espa[ñn]a\s*\)",
        r"\bremoto\s+espa[ñn]a\b",
        r"\bsolo\s+teletrabajo\b",
        r"\bwork\s+from\s+anywhere\b",
        r"\b100%\s+a\s+distancia\b",
        r"\bsin\s+presencialidad\b",
    ]
    if any(re.search(ro, full_text, re.IGNORECASE) for ro in strict_remote_signals):
        return "100% Remoto"

    # 4. Strict Presencial Signals
    strict_presencial_signals = [
        "presencial en planta",
        "presencial en fábrica",
        "presencial en fabrica",
        "trabajo presencial",
        "modalidad presencial",
        "trabajo en fábrica",
        "trabajo en planta",
        "asistencia física a planta",
        "asistencia diaria a oficina",
    ]
    if any(
        re.search(r"\b" + re.escape(ps) + r"\b", full_text, re.IGNORECASE)
        for ps in strict_presencial_signals
    ):
        return "Presencial"

    # 5. General Remote word (when no negation and no hybrid was found)
    if any(
        re.search(r"\b" + re.escape(rs) + r"\b", full_text, re.IGNORECASE)
        for rs in REMOTE_KEYWORDS
    ):
        if "remoto" in loc_lower or "remote" in loc_lower or "teletrabajo" in loc_lower:
            return "100% Remoto"
        if any(v in loc_lower for v in (PRIMARY_AREA + OTHER_CITIES)):
            return "Híbrido"
        return "100% Remoto"

    # 6. Geolocation fallback
    if any(v in loc_lower for v in PRIMARY_AREA):
        return "Presencial / Híbrido"
    if any(v in loc_lower for v in OTHER_CITIES):
        return "Presencial / Híbrido"

    return "Flexible / No especificada"


def is_job_geographically_viable(
    location: str, title: str = "", description: str = ""
) -> bool:
    """
    Filtro crítico de ubicación. Comprueba si el candidato puede acceder a la oferta:
    - Si está en la zona de primary_city o alrededores: Permite cualquier modalidad (Presencial/Híbrido/Remoto).
    - Si está fuera de primary_city (Madrid, Barcelona, etc.): Solo permite ofertas 100% Remoto.

    Args:
        location (str): La ubicación indicada en la oferta.
        title (str, optional): Título de la oferta. Por defecto "".
        description (str, optional): Descripción de la oferta. Por defecto "".

    Returns:
        bool: True si la oferta es viable geográficamente, False si no.
    """
    if is_PRIMARY_AREA(location, title):
        return True

    modality = extract_modality(f"{title} {description} {location}", location)
    if modality == "100% Remoto":
        return True

    # If modality is Presencial, Híbrido, Presencial / Híbrido, or Unspecified outside primary_city -> Reject
    return False


def classify_company_type(company: str, description: str = "") -> str:
    """
    Clasifica si la entidad que publica la oferta es una Consultora IT (selección/staffing)
    o una Empresa de Producto (cliente final), basándose en palabras clave de la descripción.

    Args:
        company (str): Nombre de la empresa.
        description (str, optional): Descripción de la oferta. Por defecto "".

    Returns:
        str: El tipo de empresa clasificado con un emoji.
    """
    comp_l = company.lower()
    desc_l = description.lower()

    if any(c in comp_l for c in KNOWN_CONSULTANCIES):
        return "💼 Consultora IT / Selección"

    if any(
        phrase in desc_l
        for phrase in [
            "para importante cliente",
            "nuestro cliente",
            "empresa cliente",
            "consultora líder",
            "consultora lider",
            "selección de personal",
            "headhunting",
            "servicios de selección",
            "empresa nos confía",
        ]
    ):
        return "💼 Consultora IT / Selección"

    return "🚀 Empresa de Producto / Cliente Final"


def estimate_market_salary(
    title: str,
    description: str = "",
    experience: str = "Mid / Semi-Senior",
    location: str = "",
    company_type: str = "🚀 Empresa de Producto / Cliente Final",
    tech_stack: list[str] | None = None,
) -> str:
    """
    Estima un salario de mercado basado en el título, experiencia, ubicación, 
    tipo de empresa y cantidad de tecnologías requeridas (stack tecnológico).

    Args:
        title (str): Título del puesto.
        description (str, optional): Descripción de la oferta.
        experience (str, optional): Nivel de experiencia extraído.
        location (str, optional): Ubicación del trabajo.
        company_type (str, optional): Tipo de empresa clasificado.
        tech_stack (list[str] | None, optional): Pila tecnológica extraída.

    Returns:
        str: Texto formateado con el rango salarial estimado.
    """
    full_text = f"{title} {description}".lower()
    exp_l = experience.lower()
    loc_l = location.lower()
    techs = tech_stack or []

    if (
        "práctica" in exp_l
        or "practica" in exp_l
        or "beca" in exp_l
        or "intern" in exp_l
    ):
        return "~12.000€ – 18.000€/año (~1.000€ – 1.500€/mes) (Beca estimada)"

    base_min, base_max = FALLBACK_SALARY

    for keywords, (s_min, s_max) in SALARY_RULES.items():
        if any(k in full_text for k in keywords):
            base_min, base_max = s_min, s_max
            break

    if "Producto" in company_type:
        base_min += PRODUCT_COMPANY_PREMIUM[0]
        base_max += PRODUCT_COMPANY_PREMIUM[1]

    if "remoto" in loc_l or "100% remoto" in full_text:
        base_min += REMOTE_PREMIUM[0]
        base_max += REMOTE_PREMIUM[1]

    if len(techs) >= 4:
        base_max += DENSE_STACK_BONUS

    return f"~{base_min}.000€ – {base_max}.000€/año (Tu rango objetivo)"


def detect_job_freshness(posted_within_1h: bool = False, description: str = "") -> str:
    """
    Clasifica si la oferta es reciente o si es potencialmente una republicación.

    Args:
        posted_within_1h (bool, optional): Indica si la oferta fue publicada en la última hora.
        description (str, optional): La descripción de la oferta.

    Returns:
        str: Etiqueta con el estado de frescura de la oferta.
    """
    desc_l = description.lower()
    if any(
        r in desc_l
        for r in ["reused", "repost", "publicada de nuevo", "republicada", "bump"]
    ):
        return "⚠️ Posible Repost / Actualizada"
    if posted_within_1h:
        return "✨ 100% Nueva (<24h)"
    return "🟢 Reciente"


def calculate_match_score(
    title: str,
    description: str = "",
    location: str = "",
    company: str = "",
    posted_within_1h: bool = False,
) -> Tuple[int, List[str], List[str], Optional[str], str, str, str, str]:
    """
    Calcula la puntuación global de afinidad (Match Score del 0-100%) entre la oferta
    y el perfil del candidato. También extrae todas las insignias (stack tecnológico,
    salario, experiencia, modalidad, tipo de empresa y frescura).

    Args:
        title (str): Título de la oferta.
        description (str, optional): Descripción de la oferta.
        location (str, optional): Ubicación de la oferta.
        company (str, optional): Nombre de la empresa.
        posted_within_1h (bool, optional): Si se publicó hace menos de una hora.

    Returns:
        Tuple: Puntuación de match (int) y varias características extraídas (etiquetas, stack, salario, experiencia, modalidad, empresa, frescura).
    """
    decision = evaluate_relevance(
        JobItem(
            id="score-preview",
            title=title,
            company=company,
            location=location,
            url="",
            source="matcher",
            description=description,
            posted_within_1h=posted_within_1h,
        )
    )
    match_tags = [
        evidence.split(":", 1)[-1].upper() for evidence in decision.positive_evidence
    ]
    if decision.status == "warning":
        match_tags.insert(0, "A revisar")

    # Presentation facts never affect relevance. They only help the candidate
    # decide between vacancies that the central classifier already accepted.
    combined_content = f"{title} {description}"
    tech_stack = extract_tech_stack(combined_content)
    real_salary = extract_salary(combined_content)
    experience = extract_experience(combined_content)
    modality = extract_modality(combined_content, location)
    company_type = classify_company_type(company, description)
    freshness = detect_job_freshness(posted_within_1h, description)

    # Use real salary if present; otherwise use hyper-calibrated estimated market salary
    final_salary = (
        real_salary
        if real_salary
        else estimate_market_salary(
            title=title,
            description=description,
            experience=experience,
            location=location,
            company_type=company_type,
            tech_stack=tech_stack,
        )
    )

    return (
        decision.score,
        match_tags[:4],
        tech_stack,
        final_salary,
        experience,
        modality,
        company_type,
        freshness,
    )
def extract_tech_stack(text: str) -> list[str]:
    """
    Extrae la pila tecnológica explícita basándose en el catálogo predefinido.
    Solo devuelve las herramientas si están claramente mencionadas.

    Args:
        text (str): Texto a analizar.

    Returns:
        list[str]: Lista de tecnologías encontradas.
    """
    if not text:
        return []

    found: list[str] = []

    for canonical_name, aliases in TECH_TOOLS_CATALOG:
        for alias in aliases:
            if alias.startswith("(?") or "\\" in alias:
                pattern = alias
            elif any(c in alias for c in ["+", "#", ".", "-", "/", " "]):
                pattern = r"(?<![@\/\w])" + re.escape(alias) + r"(?!\w|\.(?:com|org|net|es|io|ai|co))"
            else:
                pattern = r"\b" + re.escape(alias) + r"\b"

            if re.search(pattern, text, re.IGNORECASE):
                found.append(canonical_name)
                break

    return found
def is_PRIMARY_AREA(location: str, title: str = "") -> bool:
    """
    Comprueba si una localización o título pertenece a primary_city o a su área metropolitana.

    Args:
        location (str): La ubicación extraída de la oferta.
        title (str, optional): Título de la oferta. Por defecto "".

    Returns:
        bool: True si pertenece a la zona de primary_city, False en caso contrario.
    """
    full = f"{location} {title}".lower()
    return any(re.search(r"\b" + re.escape(v) + r"\b", full) for v in PRIMARY_AREA)
