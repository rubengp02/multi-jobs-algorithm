import sys
import re

with open('matcher.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = re.sub(r'def extract_salary\([\s\S]*?\) -> str:', 'def extract_salary(text: str) -> str:\n    """\n    Analiza el texto de la oferta y extrae el rango salarial si está publicado explícitamente.\n    Normaliza y formatea el resultado a rangos anuales en euros.\n    """', c)
c = re.sub(r'def is_job_geographically_viable\([\s\S]*?\) -> bool:\n\s+"""[\s\S]*?"""', 'def is_job_geographically_viable(location: str, title: str = "", description: str = "") -> bool:\n    """\n    Filtro crítico de ubicación. Comprueba si el candidato puede acceder a la oferta:\n    - Si está en la zona de Valencia o alrededores: Permite cualquier modalidad (Presencial/Híbrido/Remoto).\n    - Si está fuera de Valencia (Madrid, Barcelona, etc.): Solo permite ofertas 100% Remoto.\n    """', c)
c = re.sub(r'def classify_company_type\([\s\S]*?\) -> str:\n\s+"""[\s\S]*?"""', 'def classify_company_type(company: str, description: str = "") -> str:\n    """\n    Clasifica si la entidad que publica la oferta es una Consultora IT (selección/staffing)\n    o una Empresa de Producto (cliente final), basándose en palabras clave de la descripción.\n    """', c)
c = re.sub(r'def calculate_match_score\([\s\S]*?\) -> [^:]+:\n\s+"""[\s\S]*?"""', 'def calculate_match_score(title: str, description: str = "", location: str = "", company: str = "", posted_within_1h: bool = False) -> Tuple[int, List[str], List[str], Optional[str], str, str, str, str]:\n    """\n    Calcula la puntuación global de afinidad (Match Score del 0-100%) entre la oferta\n    y el perfil del candidato. También extrae todas las insignias (stack tecnológico,\n    salario, experiencia, modalidad, tipo de empresa y frescura).\n    """', c)

with open('matcher.py', 'w', encoding='utf-8') as f:
    f.write(c)

print("matcher.py updated")
