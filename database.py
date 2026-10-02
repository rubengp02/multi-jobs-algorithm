import json
import logging
import sqlite3
import time
import aiosqlite
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DatabaseStorage:
    """Clase para el almacenamiento asíncrono en SQLite.

    Proporciona persistencia segura de datos utilizando `aiosqlite`.
    La inicialización de las tablas se realiza de forma síncrona para
    facilitar la instanciación de la clase antes de entrar al bucle asíncrono.

    Args:
        db_path (Path): La ruta al archivo de la base de datos SQLite.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        # Crea el directorio padre si no existe para evitar errores al conectar
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db_sync()

    def _init_db_sync(self) -> None:
        """Crea las tablas y configura el esquema inicial de forma síncrona.
        
        Configura el modo WAL (Write-Ahead Logging) para un mejor rendimiento
        concurrente y crea las tablas principales si no existen.
        """
        with sqlite3.connect(str(self.db_path)) as conn:
            # Habilita WAL para permitir lecturas y escrituras concurrentes
            conn.execute("PRAGMA journal_mode=WAL")
            # NORMAL es seguro con WAL y ofrece mejor rendimiento
            conn.execute("PRAGMA synchronous=NORMAL")
            
            # Tabla para registrar trabajos ya procesados y evitar duplicidad
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_jobs (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    timestamp INTEGER NOT NULL
                )
                """
            )
            # Tabla de caché para almacenar las evaluaciones de relevancia y no reevaluar
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS relevance_cache (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    timestamp INTEGER NOT NULL
                )
                """
            )
            # Tabla de métricas para análisis de datos de los trabajos encontrados
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metrics (
                    id TEXT PRIMARY KEY,
                    source TEXT,
                    title TEXT,
                    company TEXT,
                    company_type TEXT,
                    freshness TEXT,
                    location TEXT,
                    url TEXT,
                    timestamp INTEGER,
                    datetime TEXT,
                    match_score REAL,
                    experience TEXT,
                    modality TEXT,
                    salary TEXT,
                    tags TEXT,
                    stack TEXT,
                    is_local_area BOOLEAN,
                    is_remote BOOLEAN
                )
                """
            )
            # Índices para mejorar la velocidad de las consultas por fecha al purgar datos
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_seen_timestamp ON seen_jobs(timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_relevance_timestamp ON relevance_cache(timestamp)"
            )

    def _key(self, source: str, job_id: str) -> str:
        """Genera una clave única combinando la fuente y el ID del trabajo.

        Args:
            source (str): La fuente o proveedor del trabajo (ej. 'linkedin').
            job_id (str): El identificador único del trabajo.

        Returns:
            str: La clave compuesta que servirá como clave primaria (ID).
        """
        return f"{source}::{job_id}"

    # --- Seen Jobs Methods (Async) ---
    async def is_seen(self, source: str, job_id: str) -> bool:
        """Comprueba si un trabajo ya ha sido visto.

        Args:
            source (str): La fuente del trabajo.
            job_id (str): El identificador del trabajo.

        Returns:
            bool: True si el trabajo ya existe en la tabla `seen_jobs`, False de lo contrario.
        """
        key = self._key(source, job_id)
        async with aiosqlite.connect(self.db_path) as db:
            # Solo consultamos la existencia (SELECT 1) para mayor eficiencia
            async with db.execute("SELECT 1 FROM seen_jobs WHERE id = ?", (key,)) as cursor:
                row = await cursor.fetchone()
                return row is not None

    async def is_seen_any(self, source: str, job_ids: list[str] | tuple[str, ...]) -> bool:
        """Comprueba si alguno de los trabajos en una lista ya ha sido visto.

        Args:
            source (str): La fuente de los trabajos.
            job_ids (list[str] | tuple[str, ...]): Lista de identificadores de trabajos.

        Returns:
            bool: True si al menos uno de los trabajos ya fue visto, False en caso contrario.
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Iteramos sobre los IDs y comprobamos uno a uno.
            # Se podría optimizar con un IN clause si la lista fuera muy grande.
            for job_id in job_ids:
                if not job_id: 
                    continue
                key = self._key(source, job_id)
                async with db.execute("SELECT 1 FROM seen_jobs WHERE id = ?", (key,)) as cursor:
                    row = await cursor.fetchone()
                    if row is not None:
                        return True
        return False

    async def add_seen(self, source: str, job_id: str, timestamp: int | None = None) -> None:
        """Añade un trabajo a la tabla de trabajos vistos.

        Args:
            source (str): La fuente del trabajo.
            job_id (str): El identificador del trabajo.
            timestamp (int | None, optional): La marca de tiempo UNIX. Si es None, se usa el tiempo actual.
        """
        key = self._key(source, job_id)
        ts = timestamp if timestamp is not None else int(time.time())
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # INSERT OR IGNORE previene errores si el trabajo ya fue insertado concurrentemente
                await db.execute(
                    "INSERT OR IGNORE INTO seen_jobs (id, source, job_id, timestamp) VALUES (?, ?, ?, ?)",
                    (key, source, job_id, ts),
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to insert seen job {key}: {e}")

    async def count_seen(self) -> int:
        """Obtiene la cantidad total de trabajos vistos.

        Returns:
            int: El número de registros en la tabla `seen_jobs`.
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM seen_jobs") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def purge_seen_older_than_days(self, max_days: int = 7) -> int:
        """Elimina los trabajos vistos que sean más antiguos que los días especificados.

        Args:
            max_days (int, optional): Número de días límite. Por defecto es 7.

        Returns:
            int: El número de registros eliminados.
        """
        cutoff = int(time.time()) - max_days * 86400
        async with aiosqlite.connect(self.db_path) as db:
            # Primero contamos cuántos se van a eliminar para retornarlo
            async with db.execute("SELECT COUNT(*) FROM seen_jobs WHERE timestamp < ?", (cutoff,)) as cursor:
                row = await cursor.fetchone()
                removed = row[0] if row else 0
            
            # Procedemos a la eliminación
            await db.execute("DELETE FROM seen_jobs WHERE timestamp < ?", (cutoff,))
            await db.commit()
        return removed

    # --- Relevance Cache Methods (Async) ---
    async def get_relevance(self, source: str, job_id: str, fingerprint: str) -> dict[str, Any] | None:
        """Obtiene el caché de relevancia para un trabajo específico.

        Args:
            source (str): La fuente del trabajo.
            job_id (str): El identificador del trabajo.
            fingerprint (str): Huella digital para validar que la caché coincide con los datos actuales.

        Returns:
            dict[str, Any] | None: El diccionario con la decisión de relevancia si es válido, de lo contrario None.
        """
        key = self._key(source, job_id)
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT fingerprint, decision, timestamp FROM relevance_cache WHERE id = ?",
                (key,),
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                stored_fingerprint, decision_json, timestamp = row

                # Si la huella digital no coincide (ej. la descripción cambió), se ignora la caché.
                if stored_fingerprint != fingerprint:
                    return None
                
                # Invalida proactivamente y borra si el registro tiene más de 7 días.
                if timestamp < int(time.time()) - 7 * 86400:
                    await db.execute("DELETE FROM relevance_cache WHERE id = ?", (key,))
                    await db.commit()
                    return None
                
                try:
                    return json.loads(decision_json)
                except Exception:
                    return None

    async def put_relevance(self, source: str, job_id: str, fingerprint: str, decision: dict[str, Any]) -> None:
        """Guarda o actualiza la decisión de relevancia en la caché.

        Args:
            source (str): La fuente del trabajo.
            job_id (str): El identificador del trabajo.
            fingerprint (str): Huella digital asociada a los datos evaluados.
            decision (dict[str, Any]): El diccionario de decisión a almacenar.
        """
        key = self._key(source, job_id)
        ts = int(time.time())
        # ensure_ascii=False permite guardar caracteres especiales como acentos o 'ñ' sin escapar
        decision_json = json.dumps(decision, ensure_ascii=False)
        
        async with aiosqlite.connect(self.db_path) as db:
            # INSERT OR REPLACE asegura que si hay un registro con la misma id, se sobrescriba.
            await db.execute(
                "INSERT OR REPLACE INTO relevance_cache (id, source, job_id, fingerprint, decision, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (key, source, job_id, fingerprint, decision_json, ts),
            )
            await db.commit()

    async def purge_relevance(self, max_days: int = 7) -> int:
        """Limpia la caché de relevancia eliminando registros antiguos o excedentes.

        Args:
            max_days (int, optional): Número de días límite. Por defecto es 7.

        Returns:
            int: El número de registros que fueron eliminados por ser antiguos.
        """
        cutoff = int(time.time()) - max_days * 86400
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM relevance_cache WHERE timestamp < ?", (cutoff,)) as cursor:
                row = await cursor.fetchone()
                removed = row[0] if row else 0

            # Elimina registros que superan el límite de tiempo
            await db.execute("DELETE FROM relevance_cache WHERE timestamp < ?", (cutoff,))
            
            # Conserva únicamente los 4000 registros más recientes para no inflar la DB indefinidamente
            await db.execute("""
                DELETE FROM relevance_cache 
                WHERE id NOT IN (
                    SELECT id FROM relevance_cache ORDER BY timestamp DESC LIMIT 4000
                )
            """)
            await db.commit()
        return removed


class SQLiteSeenStorage:
    """Wrapper para la gestión de trabajos vistos en SQLite.

    Proporciona métodos convenientes que delegan a la instancia `DatabaseStorage`
    para operar con la tabla de trabajos vistos (`seen_jobs`).

    Args:
        db (DatabaseStorage): Instancia de almacenamiento de la base de datos principal.
    """
    def __init__(self, db: DatabaseStorage):
        """Inicializa el envoltorio de almacenamiento de trabajos vistos.
        
        Args:
            db (DatabaseStorage): La instancia principal de la base de datos.
        """
        self.db = db

    async def is_seen(self, source: str, job_id: str) -> bool:
        """Delega la comprobación de un trabajo visto.
        
        Args:
            source (str): La fuente del trabajo (ej. 'linkedin').
            job_id (str): El identificador del trabajo.
            
        Returns:
            bool: True si ya ha sido visto, False si no.
        """
        return await self.db.is_seen(source, job_id)

    async def is_seen_any(self, source: str, job_ids: list[str] | tuple[str, ...]) -> bool:
        """Delega la comprobación múltiple de trabajos vistos.
        
        Args:
            source (str): La fuente de los trabajos.
            job_ids (list[str] | tuple[str, ...]): Colección de identificadores.
            
        Returns:
            bool: True si al menos uno ya fue visto.
        """
        return await self.db.is_seen_any(source, job_ids)

    async def add(self, source: str, job_id: str, timestamp: int | None = None) -> None:
        """Delega la adición de un trabajo a la base de datos.
        
        Args:
            source (str): La fuente del trabajo.
            job_id (str): El identificador del trabajo.
            timestamp (int | None, optional): Marca de tiempo UNIX personalizada.
        """
        await self.db.add_seen(source, job_id, timestamp)

    async def count(self) -> int:
        """Delega la obtención del recuento total de trabajos vistos.
        
        Returns:
            int: Número de trabajos ya procesados.
        """
        return await self.db.count_seen()

    async def purge_older_than_days(self, max_days: int = 7) -> int:
        """Delega la purga de trabajos vistos según su antigüedad.
        
        Args:
            max_days (int, optional): Días de antigüedad máximos a conservar. Por defecto es 7.
            
        Returns:
            int: Cantidad de registros eliminados.
        """
        return await self.db.purge_seen_older_than_days(max_days)


class SQLiteRelevanceCache:
    """Wrapper para la gestión de la caché de relevancia en SQLite.

    Permite obtener, guardar y limpiar las decisiones de relevancia de los trabajos.
    También proporciona un registro (métricas) de trabajos evaluados.

    Args:
        db (DatabaseStorage): Instancia de almacenamiento de la base de datos principal.
    """
    def __init__(self, db: DatabaseStorage):
        """Inicializa el envoltorio para la caché de relevancia.
        
        Args:
            db (DatabaseStorage): La instancia principal de la base de datos.
        """
        self.db = db

    async def get(self, source: str, job_id: str, fingerprint: str) -> dict | None:
        """Obtiene la decisión de relevancia almacenada si coincide la huella.
        
        Args:
            source (str): La fuente del trabajo.
            job_id (str): El identificador del trabajo.
            fingerprint (str): Huella digital del contenido del trabajo para validar frescura.
            
        Returns:
            dict | None: El diccionario con la decisión si es válida, de lo contrario None.
        """
        return await self.db.get_relevance(source, job_id, fingerprint)

    async def put(self, source: str, job_id: str, fingerprint: str, decision: dict) -> None:
        """Almacena o actualiza la decisión de relevancia en la base de datos.
        
        Args:
            source (str): La fuente del trabajo.
            job_id (str): El identificador del trabajo.
            fingerprint (str): Huella digital del contenido evaluado.
            decision (dict): Resultado de la evaluación de relevancia.
        """
        await self.db.put_relevance(source, job_id, fingerprint, decision)

    async def purge(self, max_days: int | None = None) -> int:
        """Limpia los registros antiguos de la caché de relevancia.
        
        Args:
            max_days (int | None, optional): Días de antigüedad máximos. Por defecto es 7.
            
        Returns:
            int: Cantidad de registros purgadores.
        """
        return await self.db.purge_relevance(max_days or 7)

    async def add_metric(self, record: dict) -> None:
        """Inserta o actualiza un registro de métricas para un trabajo específico.

        Almacena detalles clave de la oferta como título, empresa, salario y ubicación
        para su posterior análisis. Utiliza INSERT OR REPLACE para evitar duplicados.
        
        Args:
            record (dict): Diccionario con los detalles de la oferta de trabajo.
        """
        try:
            async with aiosqlite.connect(self.db.db_path) as db:
                await db.execute(
                    """
                    INSERT OR REPLACE INTO metrics 
                    (id, source, title, company, company_type, freshness, location, url, timestamp, 
                    datetime, match_score, experience, modality, salary, tags, stack, is_local_area, is_remote)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.get("id"),
                        record.get("source"),
                        record.get("title"),
                        record.get("company"),
                        record.get("company_type"),
                        record.get("freshness"),
                        record.get("location"),
                        record.get("url"),
                        record.get("timestamp"),
                        record.get("datetime"),
                        record.get("match_score"),
                        record.get("experience"),
                        record.get("modality"),
                        record.get("salary"),
                        # Serializa listas complejas en JSON para poder guardarlas en SQLite
                        json.dumps(record.get("tags", [])),
                        json.dumps(record.get("stack", [])),
                        record.get("is_local_area"),
                        record.get("is_remote"),
                    ),
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to insert metric {record.get('id')}: {e}")

    async def get_all_metrics(self) -> list[dict]:
        """Recupera todas las métricas almacenadas de trabajos.

        Los campos en formato JSON (`tags` y `stack`) se deserializan nuevamente a listas.
        
        Returns:
            list[dict]: Lista de diccionarios donde cada uno representa un registro de métricas.
        """
        async with aiosqlite.connect(self.db.db_path) as db:
            # db.row_factory permite acceder a las columnas por nombre en lugar de índice
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM metrics ORDER BY timestamp DESC") as cursor:
                rows = await cursor.fetchall()

                results = []
                for row in rows:
                    r = dict(row)
                    # Deserializa los datos estructurados devueltos como cadenas JSON
                    r["tags"] = json.loads(r["tags"]) if r["tags"] else []
                    r["stack"] = json.loads(r["stack"]) if r["stack"] else []
                    results.append(r)
                return results
