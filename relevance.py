"""
Motor de Relevancia (Relevance Engine)
=======================================

Decisiones de relevancia deterministas y explicables para las ofertas de empleo.
Evalúa el título y la descripción de una oferta contra un sistema de puntos.


Location, salary and seniority deliberately do not participate here: they can
help a candidate choose between relevant offers, but must never turn an
unrelated vacancy into a notification.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Literal

from models import JobItem

RelevanceStatus = Literal["accepted", "warning", "rejected"]

# Bump this whenever the classification rules change materially.  It is part
# of the cache key so an offer rejected by an older policy is evaluated again.
RELEVANCE_POLICY_VERSION = 4


def _normalise(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    return " ".join(
        "".join(char for char in value if not unicodedata.combining(char))
        .casefold()
        .split()
    )


def _contains(text: str, terms: Sequence[str]) -> list[str]:
    # A raw substring turns unrelated words such as "maintain" into an
    # apparent "AI" hit.  The vocabulary is deliberately matched as terms.
    return [
        term
        for term in terms
        if re.search(rf"(?<![a-z0-9]){re.escape(_normalise(term))}(?![a-z0-9])", text)
    ]


@dataclass(frozen=True)
class RelevanceDecision:
    status: RelevanceStatus
    score: int
    family: str
    positive_evidence: tuple[str, ...]
    negative_evidence: tuple[str, ...]
    needs_description: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def decision_from_dict(value: object) -> RelevanceDecision | None:
    """Restore only complete, known-safe cached relevance decisions."""
    if not isinstance(value, dict):
        return None
    status = value.get("status")
    if status not in {"accepted", "warning", "rejected"}:
        return None
    try:
        return RelevanceDecision(
            status=status,
            score=max(0, min(100, int(value.get("score", 0)))),
            family=str(value.get("family") or "sin_evidencia_digital"),
            positive_evidence=tuple(
                str(item) for item in value.get("positive_evidence", ())
            ),
            negative_evidence=tuple(
                str(item) for item in value.get("negative_evidence", ())
            ),
            needs_description=bool(value.get("needs_description", False)),
        )
    except (TypeError, ValueError):
        return None


from business_rules import (
    AI_EVIDENCE as _AI,
)
from business_rules import (
    ANALYTICS_EVIDENCE as _ANALYTICS,
)
from business_rules import (
    AUTOMATION_EVIDENCE as _AUTOMATION,
)
from business_rules import (
    DATA_EVIDENCE as _DATA,
)
from business_rules import (
    INDUSTRIAL_DIGITAL as _INDUSTRIAL_DIGITAL,
)
from business_rules import (
    SOFTWARE_CONTEXTUAL as _SOFTWARE_CONTEXTUAL,
)
from business_rules import (
    SOFTWARE_DIRECT as _SOFTWARE_DIRECT,
)
from business_rules import (
    SOFTWARE_EVIDENCE as _SOFTWARE,
)
from business_rules import (
    SOFTWARE_GENERIC as _SOFTWARE_GENERIC,
)
from business_rules import (
    UNWANTED_ROLES as _UNWANTED_ROLES,
)

_HR = (
    "nomina",
    "nominas",
    "payroll",
    "recursos humanos",
    "rrhh",
    "talent acquisition",
    "seleccion de personal",
    "recruiter",
    "tecnico laboral",
)
_CAD = ("autocad", "bim", "revit", "delineante", "delineacion", "modelador bim")
_GRAPHIC = (
    "disenador grafico",
    "diseno grafico",
    "grafista",
    "arte final",
    "illustrator",
    "photoshop",
)
_MECHANICAL = (
    "soldador",
    "tornero",
    "fresador",
    "mecanizado",
    "operario de produccion",
    "operario de fabricacion",
    "montador mecanico",
    "mantenimiento mecanico",
    "fabricacion mecanica",
)
_PLC = ("plc", "scada", "tia portal", "programador plc", "automatista industrial")


def relevance_fingerprint(job: JobItem) -> str:
    """
    Genera una huella digital (hash) única basada en los campos clave de la oferta.
    Si la oferta cambia (por ejemplo, el texto de la descripción), la huella cambia
    y el sistema sabe que debe volver a evaluarla.
    """
    """Fingerprint mutable card/detail fields so changed vacancies are rechecked."""
    parts = (
        f"policy:{RELEVANCE_POLICY_VERSION}",
        job.id,
        job.url,
        job.title,
        job.company,
        job.location,
        job.description,
    )
    return hashlib.sha256(
        "\x1f".join(_normalise(part) for part in parts).encode("utf-8")
    ).hexdigest()


def _term_weight(term: str, text: str) -> int:
    term_escaped = re.escape(_normalise(term))
    matches = list(re.finditer(rf"(?<![a-z0-9]){term_escaped}(?![a-z0-9])", text))
    if not matches:
        return 0

    weak_pattern = re.compile(
        r"(valorable|deseable|plus|bonus|ventaja|no excluyente|nice to have)"
    )
    negated_pattern = re.compile(
        r"(no\s+(?:requerimos|necesitamos|buscamos|es\s+necesario|requerido|excluyente))"
    )

    best_score = 0
    for m in matches:
        start_idx = max(0, m.start() - 60)
        window = text[start_idx : m.start()]
        if negated_pattern.search(window):
            score = 0
        elif weak_pattern.search(window):
            score = 1
        else:
            score = 4
        best_score = max(best_score, score)
    return best_score


def _score_group(terms: list[str], text: str) -> int:
    return sum(_term_weight(t, text) for t in terms)


def evaluate_relevance(
    job: JobItem, description: str | None = None
) -> RelevanceDecision:
    """
    Clasifica una vacante buscando evidencias del perfil (IA, Datos, Backend),
    descartando explícitamente aquellas que pertenezcan a familias negativas.
    Retorna una decisión con el Match Score y las etiquetas encontradas.
    """
    title = _normalise(job.title)
    company = _normalise(job.company)
    detail = _normalise(description if description is not None else job.description)
    title_company = f"{title} {company}".strip()
    text = f"{title_company} {detail}".strip()
    linkedin_candidate = _normalise(job.source) == "linkedin"

    positive: list[str] = []
    for family, evidence_terms in (
        ("ai_ml", _AI),
        ("data", _DATA),
        ("python_api", _SOFTWARE),
        ("industrial_digital", _INDUSTRIAL_DIGITAL),
        ("analytics", _ANALYTICS),
        ("automation", _AUTOMATION),
    ):
        matches = _contains(text, evidence_terms)
        if matches:
            positive.extend(f"{family}:{term}" for term in matches[:3])

    negative_groups: tuple[tuple[str, Sequence[str]], ...] = (
        ("rol_no_tecnico_o_gestion", _UNWANTED_ROLES),
        ("rrhh_nominas", _HR),
        ("cad_bim", _CAD),
        ("diseno_grafico", _GRAPHIC),
    )
    for family, negative_terms in negative_groups:
        matches = _contains(title_company, negative_terms)
        if matches:
            return RelevanceDecision(
                "rejected", 0, family, tuple(positive[:5]), tuple(matches)
            )

    # Industrial maintenance is only relevant when the vacancy explicitly
    # connects it with predictive/digital technology.  Do not reject that
    # combination merely because its title also says "mantenimiento".
    mechanical = _contains(title_company, _MECHANICAL)
    digital_evidence = _contains(
        text, _AI + _DATA + _SOFTWARE_DIRECT + _INDUSTRIAL_DIGITAL
    )
    if mechanical and not digital_evidence:
        return RelevanceDecision(
            "rejected", 0, "mecanica_fabricacion", (), tuple(mechanical)
        )

    plc = _contains(title_company, _PLC)
    if plc and not digital_evidence:
        return RelevanceDecision("rejected", 20, "plc_scada_puro", (), tuple(plc))

    ai = _contains(text, _AI)
    data = _contains(text, _DATA)
    software = _contains(text, _SOFTWARE_DIRECT)
    generic_software = _contains(text, _SOFTWARE_CONTEXTUAL + _SOFTWARE_GENERIC)
    industrial = _contains(text, _INDUSTRIAL_DIGITAL)
    analytics = _contains(text, _ANALYTICS)
    automation = _contains(text, _AUTOMATION)
    if ai:
        return RelevanceDecision(
            "accepted",
            min(100, 80 + min(18, _score_group(ai, text))),
            "ai_ml",
            tuple(positive[:6]),
            (),
        )
    if data:
        return RelevanceDecision(
            "accepted",
            min(95, 74 + min(20, _score_group(data, text))),
            "data",
            tuple(positive[:6]),
            (),
        )
    if industrial and (
        software
        or any(
            term in text
            for term in ("predictivo", "iot", "digital", "vision", "datos", "data")
        )
    ):
        return RelevanceDecision(
            "accepted",
            min(
                88,
                72
                + _score_group(industrial, text)
                + min(6, _score_group(software, text)),
            ),
            "industrial_digital",
            tuple(positive[:6]),
            (),
        )
    if software:
        return RelevanceDecision(
            "accepted",
            min(85, 70 + min(15, _score_group(software, text))),
            "python_api",
            tuple(positive[:6]),
            (),
        )
    if generic_software:
        has_detail = bool(description) and len(description.strip()) > 50
        if has_detail:
            return RelevanceDecision(
                "accepted",
                75,
                "software_generico",
                tuple(positive[:6]),
                (),
            )
        elif linkedin_candidate:
            return RelevanceDecision(
                "warning",
                65,
                "linkedin_search_candidate",
                tuple(positive[:6]),
                (),
                True,
            )
        else:
            return RelevanceDecision(
                "rejected",
                20,
                "software_sin_stack_objetivo",
                (),
                (),
            )
    if analytics:
        score = min(69, 56 + _score_group(analytics, text))
        return RelevanceDecision(
            "warning",
            score,
            "analytics",
            tuple(positive[:6]),
            (),
        )
    if automation:
        score = min(69, 56 + _score_group(automation, text))
        return RelevanceDecision(
            "warning",
            score,
            "automation",
            tuple(positive[:6]),
            (),
        )

    plausible = any(
        term in title_company
        for term in (
            "ingenier",
            "engineer",
            "datos",
            "data",
            "digital",
            "automatiz",
            "software",
            "tecnolog",
        )
    )

    return RelevanceDecision(
        "rejected",
        35 if plausible else 0,
        "sin_evidencia_digital",
        (),
        (),
        plausible and not bool(detail),
    )
