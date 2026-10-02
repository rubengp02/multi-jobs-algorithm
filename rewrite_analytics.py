import sys

with open('analytics.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('from operational_retention import jsonl_file_lock', 'from database import DatabaseStorage, SQLiteRelevanceCache')

c = c.replace(
'''    def __init__(self, file_path: Path, logger: logging.Logger | None = None) -> None:
        self.file_path = file_path
        self.logger = logger or logging.getLogger("MetricsStorage")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self.file_path.touch()''',
'''    def __init__(self, db: DatabaseStorage, logger: logging.Logger | None = None) -> None:
        self.db = db
        # Para compatibilidad reutilizamos la interfaz SQLiteRelevanceCache
        # que tiene los metodos add_metric y get_all_metrics
        self.sql_cache = SQLiteRelevanceCache(self.db)
        self.logger = logger or logging.getLogger("MetricsStorage")'''
)

c = c.replace(
'''        try:
            with (
                jsonl_file_lock(self.file_path),
                self.file_path.open("a", encoding="utf-8") as f,
            ):
                f.write(json.dumps(record, ensure_ascii=False) + "\\n")
        except (OSError, TypeError, ValueError) as exc:
            self.logger.error("Failed to append metrics record: %s", exc)''',
'''        try:
            self.sql_cache.add_metric(record)
        except Exception as exc:
            self.logger.error("Failed to insert metric to SQLite: %s", exc)'''
)

c = c.replace(
'''    def iter_records(self) -> Iterator[dict[str, Any]]:
        """Stream history instead of loading an unbounded JSONL file into memory."""
        if not self.file_path.exists():
            return
        try:
            with self.file_path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        continue
                    if isinstance(record, dict):
                        yield record
        except OSError as exc:
            self.logger.error("Failed to read metrics file: %s", exc)''',
'''    def iter_records(self) -> Iterator[dict[str, Any]]:
        """Devuelve un iterador sobre las métricas almacenadas en SQLite."""
        try:
            records = self.sql_cache.get_all_metrics()
            yield from records
        except Exception as exc:
            self.logger.error("Failed to read metrics from SQLite: %s", exc)'''
)

with open('analytics.py', 'w', encoding='utf-8') as f:
    f.write(c)

print("analytics.py rewritten successfully!")
