"""Módulo de Reglas de Negocio (Business Rules).

Este archivo centraliza todas las reglas lógicas que definen el comportamiento
del bot de empleo. Aquí se establecen los términos de búsqueda, los roles que se
desean descartar, y los algoritmos base para estimar los salarios de mercado.

Modificando este archivo, puedes adaptar el bot a un nuevo perfil sin necesidad
de alterar la lógica del código principal de extracción o evaluación.

Contiene agrupaciones de términos (evidencias) que se utilizan para clasificar
ofertas, descartar roles no deseados, y reglas de mercado para estimar los
rangos salariales en función de las tecnologías detectadas.
"""

# 1. Reglas de Descarte (Roles no deseados)
# -----------------------------------------
# Cualquier oferta cuyo título o contexto coincida fuertemente con estas
# palabras clave será descartada automáticamente, ahorrando tiempo de procesamiento.
UNWANTED_ROLES: tuple[str, ...] = (
    "ventas",
    "sales",
    "comercial",
    "soporte tecnico",
    "helpdesk",
    "help desk",
    "atencion al cliente",
    "customer support",
    "scrum master",
    "agile coach",
    "marketing",
    "seo",
    "sem",
    "community manager",
    "account manager",
    "business development",
    "sdr",
    "consultor sap",
    "sap fico",
    "sap sd",
    "sap mm",
    "profesor",
    "docente",
    "formador",
    "tutor",
    "ciberseguridad",
    "cybersecurity",
    "administrador de sistemas",
    "sysadmin",
    "legal",
    "abogado",
    # Roles descartados por nivel de experiencia superior al deseado:
    "senior",
    "sr",
    "lead",
    "principal",
    "director",
    "jefe",
    "responsable",
    "head of",
    "manager",
)

# 2. Familias de Relevancia (Evidencias de perfil)
# ------------------------------------------------
# Estas tuplas definen las palabras clave que el algoritmo buscará para
# confirmar que una oferta coincide con las habilidades de Inteligencia Artificial,
# Datos y Desarrollo de Software del candidato.

AI_EVIDENCE: tuple[str, ...] = (
    "inteligencia artificial",
    "artificial intelligence",
    "ai",
    "machine learning",
    "deep learning",
    "nlp",
    "llm",
    "generative ai",
    "ia generativa",
    "computer vision",
    "vision artificial",
    "openai",
    "pytorch",
    "tensorflow",
    "scikit-learn",
)

DATA_EVIDENCE: tuple[str, ...] = (
    "data engineer",
    "ingeniero de datos",
    "data scientist",
    "cientifico de datos",
    "etl",
    "data pipeline",
    "big data",
    "spark",
    "hadoop",
    "databricks",
    "snowflake",
)

# Herramientas directas de desarrollo Backend:
SOFTWARE_DIRECT: tuple[str, ...] = (
    "python",
    "fastapi",
    "django",
    "flask",
    "api rest",
    "microservicios",
    "backend",
    "desarrollo backend",
)
# Términos contextuales que apoyan el desarrollo Backend:
SOFTWARE_CONTEXTUAL: tuple[str, ...] = ("backend", "software engineer")
# Términos genéricos de programación:
SOFTWARE_GENERIC: tuple[str, ...] = (
    "desarrollador",
    "developer",
    "programador",
    "programmer",
)

# Familia combinada de todo el espectro de Software:
SOFTWARE_EVIDENCE: tuple[str, ...] = (
    SOFTWARE_DIRECT + SOFTWARE_CONTEXTUAL + SOFTWARE_GENERIC
)

INDUSTRIAL_DIGITAL: tuple[str, ...] = (
    "mantenimiento predictivo",
    "predictive maintenance",
    "industria 4.0",
    "industry 4.0",
    "digital twin",
    "gemelo digital",
    "iot",
    "iiot",
    "edge computing",
    "condition monitoring",
    "machine vision",
    "vision artificial",
    "robotica",
    "robotics",
)

ANALYTICS_EVIDENCE: tuple[str, ...] = (
    "data analyst",
    "analista de datos",
    "power bi",
    "tableau",
    "business intelligence",
    "sql",
)

AUTOMATION_EVIDENCE: tuple[str, ...] = (
    "automatizacion",
    "automation",
    "rpa",
    "power automate",
    "ui path",
    "uipath",
)

# 3. Reglas de Estimación Salarial de Mercado
# -------------------------------------------
# Este diccionario mapea agrupaciones de tecnologías con rangos salariales
# estimados (mínimo, máximo) en miles de euros anuales.
# El sistema evaluará estas reglas en orden y aplicará la primera que coincida.
SALARY_RULES: dict[tuple[str, ...], tuple[int, int]] = {
    # Perfil 1: IA Generativa y MLOps (Alta demanda, mayor banda salarial)
    (
        "llm",
        "rag",
        "generativ",
        "agent",
        "gpt",
        "langchain",
        "mlops",
        "ia generativa",
    ): (30, 36),
    # Perfil 2: Visión Artificial y Deep Learning
    (
        "computer vision",
        "vision artificial",
        "opencv",
        "yolo",
        "deep learning",
        "cnn",
        "reinforcement learning",
    ): (29, 35),
    # Perfil 3: Ingeniería de Datos y Cloud
    (
        "data engineer",
        "ingeniero de datos",
        "spark",
        "snowflake",
        "databricks",
        "kafka",
    ): (28, 35),
    # Perfil 4: Automatización Industrial e IoT
    (
        "plc",
        "scada",
        "automatizacion",
        "automatización",
        "robotica",
        "robótica",
        "industrial",
        "mantenimiento predictivo",
        "predictivo",
        "tia portal",
    ): (28, 34),
    # Perfil 5: Desarrollo Backend Estándar
    ("python", "fastapi", "django", "flask", "backend"): (28, 34),
    # Perfil 6: Análisis de Datos (BI)
    ("bi", "business intelligence", "power bi", "powerbi", "tableau", "data analyst"): (
        25,
        30,
    ),
}

# Salario base por defecto si no encaja en ninguna categoría premium:
FALLBACK_SALARY: tuple[int, int] = (27, 33)

# Modificadores adicionales:
PRODUCT_COMPANY_PREMIUM: tuple[int, int] = (
    1,
    2,
)  # Aumento (mín, máx) si es empresa de producto.
REMOTE_PREMIUM: tuple[int, int] = (1, 1)  # Aumento si el puesto es 100% remoto.
DENSE_STACK_BONUS: int = 1  # Aumento en el rango superior si exigen muchas tecnologías.
