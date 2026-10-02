import sys

with open('relevance.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('"""Deterministic, explainable relevance decisions for job offers.', '"""\nMotor de Relevancia (Relevance Engine)\n=======================================\n\nDecisiones de relevancia deterministas y explicables para las ofertas de empleo.\nEvalúa el título y la descripción de una oferta contra un sistema de puntos.\n')

c = c.replace('def relevance_fingerprint(job: JobItem) -> str:', 'def relevance_fingerprint(job: JobItem) -> str:\n    """\n    Genera una huella digital (hash) única basada en los campos clave de la oferta.\n    Si la oferta cambia (por ejemplo, el texto de la descripción), la huella cambia\n    y el sistema sabe que debe volver a evaluarla.\n    """')

c = c.replace('def evaluate_relevance(', 'def evaluate_relevance(\n    job: JobItem, description: str | None = None\n) -> RelevanceDecision:\n    """\n    Clasifica una vacante buscando evidencias del perfil objetivo (IA, Datos, Python),\n    descartando explícitamente aquellas que pertenezcan a familias negativas (Ventas, RRHH).\n\n    Retorna una decisión (RelevanceDecision) con el estado (accepted/rejected), la\n    puntuación de afinidad (Match Score) y las etiquetas encontradas.\n    """\n')
# We have to be careful with multiline replaces. Let's just do it manually with regex.
import re
c = re.sub(r'def evaluate_relevance\([\s\S]*?\) -> RelevanceDecision:\n\s+"""Classify a vacancy from profile evidence, with explicit negative families."""', 'def evaluate_relevance(\n    job: JobItem, description: str | None = None\n) -> RelevanceDecision:\n    """\n    Clasifica una vacante buscando evidencias del perfil (IA, Datos, Backend),\n    descartando explícitamente aquellas que pertenezcan a familias negativas.\n    Retorna una decisión con el Match Score y las etiquetas encontradas.\n    """', c)

with open('relevance.py', 'w', encoding='utf-8') as f:
    f.write(c)

print("relevance.py updated")
