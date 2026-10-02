import sys

def replace_in_file(filepath, replacements):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    for old, new in replacements:
        if old not in content:
            print(f"ERROR: Could not find substring in {filepath}:\n{old[:100]}...")
            return False
        content = content.replace(old, new)
        
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    return True

linkedin_replacements = [
    (
        '''@dataclass(frozen=True)\nclass LinkedInFetchResult:\n    search_url: str''',
        '''@dataclass(frozen=True)\nclass LinkedInFetchResult:\n    """Representa el resultado de una solicitud de obtención de empleos en LinkedIn.\n\n    Atributos:\n        search_url (str): La URL de búsqueda solicitada.\n        endpoint_url (str): La URL del endpoint interno al que se realizó la solicitud.\n        state (FetchState): Estado final de la solicitud (ok, empty, partial, blocked, etc.).\n        http_status (int | None): Código de estado HTTP de la respuesta.\n        jobs (tuple[JobItem, ...]): Tupla de trabajos extraídos exitosamente.\n        raw_cards (int): Número bruto de tarjetas devueltas por la respuesta.\n        parsed_cards (int): Número de tarjetas analizadas con éxito.\n        incomplete_cards (int): Número de tarjetas que tenían información incompleta.\n        error (str): Mensaje de error, si hubo alguno.\n    """\n    search_url: str'''
    ),
    (
        '''    @property\n    def complete(self) -> bool:\n        return self.state in {"ok", "empty"}''',
        '''    @property\n    def complete(self) -> bool:\n        """Indica si el resultado se obtuvo completamente sin errores ni bloqueos.\n\n        Devuelve:\n            bool: Verdadero si el estado es 'ok' o 'empty'.\n        """\n        return self.state in {"ok", "empty"}'''
    ),
    (
        '''    def as_dict(self) -> dict[str, object]:\n        return {''',
        '''    def as_dict(self) -> dict[str, object]:\n        """Convierte los resultados en un diccionario para la serialización.\n\n        Devuelve:\n            dict[str, object]: Diccionario que contiene las propiedades del resultado.\n        """\n        return {'''
    ),
    (
        '''class LinkedInProvider:\n    source = "linkedin"\n\n    def __init__(\n        self,\n        config: BotConfig,\n        logger: logging.Logger,\n        playwright: object | None = None,\n    ) -> None:\n        self.config = config''',
        '''class LinkedInProvider:\n    """Proveedor que encapsula la lógica para extraer trabajos desde LinkedIn.\n\n    Utiliza el endpoint de invitado (guest) público de LinkedIn y técnicas\n    de evasión (stealth) para evitar bloqueos por límite de peticiones (Rate Limit).\n\n    Atributos:\n        source (str): Nombre del proveedor ("linkedin").\n    """\n    source = "linkedin"\n\n    def __init__(\n        self,\n        config: BotConfig,\n        logger: logging.Logger,\n        playwright: object | None = None,\n    ) -> None:\n        """Inicializa el proveedor de LinkedIn.\n\n        Argumentos:\n            config (BotConfig): Objeto de configuración del bot.\n            logger (logging.Logger): Logger para registrar información y errores.\n            playwright (object | None, opcional): Referencia a Playwright.\n                Mantenido por compatibilidad, aunque este proveedor usa 'requests'.\n        """\n        self.config = config'''
    ),
    (
        '''    def configured_urls(self) -> list[str]:\n        values = [''',
        '''    def configured_urls(self) -> list[str]:\n        """Obtiene y expande las URLs configuradas de LinkedIn.\n\n        Inyecta parámetros necesarios como 'f_E=2%2C3' (filtros de experiencia)\n        y expande las URLs en ventanas de tiempo.\n\n        Devuelve:\n            list[str]: Lista de URLs de búsqueda de LinkedIn listas para consultar.\n        """\n        # Recopila todas las URLs definidas en la configuración\n        values = ['''
    ),
    (
        '''    def _inter_search_delay_bounds(self) -> tuple[float, float]:\n        lower = max(''',
        '''    def _inter_search_delay_bounds(self) -> tuple[float, float]:\n        """Calcula los límites de tiempo de espera entre búsquedas.\n\n        Devuelve:\n            tuple[float, float]: Una tupla con (mínimo, máximo) en segundos de retraso.\n        """\n        lower = max('''
    ),
    (
        '''    @staticmethod\n    def _guest_endpoint(search_url: str) -> str:\n        parts = urlsplit(search_url)''',
        '''    @staticmethod\n    def _guest_endpoint(search_url: str) -> str:\n        """Transforma una URL de búsqueda normal en la URL del endpoint para invitados.\n\n        Argumentos:\n            search_url (str): La URL de búsqueda original.\n\n        Devuelve:\n            str: URL apuntando a la API pública de invitados de LinkedIn.\n        """\n        parts = urlsplit(search_url)'''
    ),
    (
        '''    @staticmethod\n    def _text(card: BeautifulSoup, selectors: tuple[str, ...], fallback: str) -> str:\n        for selector in selectors:''',
        '''    @staticmethod\n    def _text(card: BeautifulSoup, selectors: tuple[str, ...], fallback: str) -> str:\n        """Extrae el texto de un elemento HTML utilizando una lista de selectores.\n\n        Argumentos:\n            card (BeautifulSoup): El nodo HTML desde donde extraer.\n            selectors (tuple[str, ...]): Selectores CSS a intentar.\n            fallback (str): Valor de retorno si no se encuentra ningún selector.\n\n        Devuelve:\n            str: Texto extraído y limpio, o el valor de 'fallback' si falla.\n        """\n        for selector in selectors:'''
    ),
    (
        '''    def _parse_cards(\n        self, html: str, search_url: str = ""\n    ) -> tuple[list[JobItem], int, int, int]:\n        soup = BeautifulSoup(html, "html.parser")''',
        '''    def _parse_cards(\n        self, html: str, search_url: str = ""\n    ) -> tuple[list[JobItem], int, int, int]:\n        """Analiza el HTML de respuesta para extraer las tarjetas de empleo.\n\n        Argumentos:\n            html (str): Contenido HTML devuelto por LinkedIn.\n            search_url (str, opcional): La URL de búsqueda usada, para referenciar.\n\n        Devuelve:\n            tuple[list[JobItem], int, int, int]: Una tupla conteniendo:\n                - Lista de trabajos analizados sin duplicados.\n                - Total de tarjetas HTML detectadas.\n                - Total de tarjetas analizadas con éxito.\n                - Total de tarjetas ignoradas por falta de información.\n        """\n        # Analiza el documento HTML buscando los contenedores de los empleos\n        soup = BeautifulSoup(html, "html.parser")'''
    ),
    (
        '''    async def fetch_url(self, search_url: str) -> LinkedInFetchResult:\n        search_url = exact_search_url(search_url)''',
        '''    async def fetch_url(self, search_url: str) -> LinkedInFetchResult:\n        """Realiza la petición HTTP para una URL de búsqueda y extrae sus ofertas.\n\n        Gestiona la paginación de la API de invitados (en fragmentos de 10) hasta\n        alcanzar el límite configurado. Maneja códigos de error y límites de tasa.\n\n        Argumentos:\n            search_url (str): La URL de búsqueda de LinkedIn a consultar.\n\n        Devuelve:\n            LinkedInFetchResult: El resultado detallado de la consulta.\n        """\n        search_url = exact_search_url(search_url)'''
    ),
    (
        '''    async def fetch_snapshots(self) -> list[LinkedInFetchResult]:\n        \n\n        now_ts = time.time()''',
        '''    async def fetch_snapshots(self) -> list[LinkedInFetchResult]:\n        """Obtiene instantáneas de todas las URLs configuradas iterativamente.\n\n        Controla el tiempo de ejecución mínimo entre ciclos globales para\n        evitar penalizaciones (Rate Limit 429) por peticiones excesivas.\n\n        Devuelve:\n            list[LinkedInFetchResult]: Lista de los resultados para cada URL de búsqueda.\n        """\n        now_ts = time.time()'''
    ),
    (
        '''    async def check_session(self) -> tuple[bool, str]:\n        """Report the actual public endpoint state, never a false success."""\n        urls = self.configured_urls()''',
        '''    async def check_session(self) -> tuple[bool, str]:\n        """Verifica el estado de la sesión consultando la primera URL disponible.\n        \n        Reporta el estado real del endpoint público sin generar un éxito falso.\n\n        Devuelve:\n            tuple[bool, str]: (Éxito, Mensaje con el estado detallado).\n        """\n        urls = self.configured_urls()'''
    ),
    (
        '''    async def fetch_jobs(self, startup_deep_scan: bool = False) -> list[JobItem]:\n        """Compatibility wrapper: raw union of exactly one configured page per URL."""\n        if startup_deep_scan:''',
        '''    async def fetch_jobs(self, startup_deep_scan: bool = False) -> list[JobItem]:\n        """Obtiene los trabajos combinados de todas las instantáneas (snapshots).\n\n        Actúa como adaptador de compatibilidad: une todos los resultados de una\n        sola página configurada por URL y elimina duplicados lógicos.\n\n        Argumentos:\n            startup_deep_scan (bool, opcional): Si es True, indica que es un escaneo\n                inicial profundo.\n\n        Devuelve:\n            list[JobItem]: Lista unificada de todos los trabajos encontrados sin duplicados.\n        """\n        if startup_deep_scan:'''
    )
]

business_replacements = [
    (
        '''"""\nMódulo de Reglas de Negocio (Business Rules)\n============================================\n\nEste archivo centraliza todas las reglas lógicas que definen el comportamiento\ndel bot de empleo. Aquí se establecen los términos de búsqueda, los roles que se\ndesean descartar, y los algoritmos base para estimar los salarios de mercado.\n\nModificando este archivo, puedes adaptar el bot a un nuevo perfil sin necesidad\nde alterar la lógica del código principal de extracción o evaluación.\n"""''',
        '''"""Módulo de Reglas de Negocio (Business Rules).\n\nEste archivo centraliza todas las reglas lógicas que definen el comportamiento\ndel bot de empleo. Aquí se establecen los términos de búsqueda, los roles que se\ndesean descartar, y los algoritmos base para estimar los salarios de mercado.\n\nModificando este archivo, puedes adaptar el bot a un nuevo perfil sin necesidad\nde alterar la lógica del código principal de extracción o evaluación.\n\nContiene agrupaciones de términos (evidencias) que se utilizan para clasificar\nofertas, descartar roles no deseados, y reglas de mercado para estimar los\nrangos salariales en función de las tecnologías detectadas.\n"""'''
    )
]

try:
    if replace_in_file('c:/Users/Ruben/Desktop/Python/bot_linkedin/bot_multi_jobs/providers/linkedin.py', linkedin_replacements) and \
       replace_in_file('c:/Users/Ruben/Desktop/Python/bot_linkedin/bot_multi_jobs/business_rules.py', business_replacements):
        print("Replacements successful.")
    else:
        print("Some replacements failed.")
except Exception as e:
    print(f"Error: {e}")
