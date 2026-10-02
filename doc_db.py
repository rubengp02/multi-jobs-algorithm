import sys

with open('database.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('class DatabaseStorage:\n    """Synchronous SQLite database storage for thread-safe persistence."""', 'class DatabaseStorage:\n    """\n    Almacenamiento síncrono en SQLite para persistencia segura entre hilos.\n    \n    Esta clase gestiona la base de datos principal del bot, utilizando el modo WAL\n    para permitir que el bot de Telegram y el ciclo de scraping consulten y guarden\n    datos de forma concurrente sin bloqueos de base de datos.\n    """')
c = c.replace('def _get_connection(self):', 'def _get_connection(self):\n        """Obtiene una conexión a SQLite optimizada para alta concurrencia (modo WAL)."""')
c = c.replace('def is_seen(self, source: str, job_id: str) -> bool:', 'def is_seen(self, source: str, job_id: str) -> bool:\n        """Comprueba si una oferta ya ha sido vista y procesada anteriormente."""')
c = c.replace('def is_seen_any(self, source: str, job_ids: list[str] | tuple[str, ...]) -> bool:', 'def is_seen_any(self, source: str, job_ids: list[str] | tuple[str, ...]) -> bool:\n        """Comprueba si alguna de las variantes del ID de la oferta ya ha sido vista."""')
c = c.replace('def add_seen(self, source: str, job_id: str, timestamp: int | None = None) -> None:', 'def add_seen(self, source: str, job_id: str, timestamp: int | None = None) -> None:\n        """Añade una oferta a la tabla de vistas para no volver a notificarla en el futuro."""')
c = c.replace('def purge_seen_older_than_days(self, max_days: int = 7) -> int:', 'def purge_seen_older_than_days(self, max_days: int = 7) -> int:\n        """Elimina de la base de datos las ofertas vistas que sean más antiguas que `max_days`."""')

with open('database.py', 'w', encoding='utf-8') as f:
    f.write(c)

print("database.py updated")
