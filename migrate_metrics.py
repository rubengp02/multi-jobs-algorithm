import json
import logging
from pathlib import Path
from database import DatabaseStorage, SQLiteRelevanceCache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MigrateMetrics")

def migrate():
    base_dir = Path(__file__).resolve().parent
    db_path = base_dir / "data" / "bot_memory.db"
    jsonl_path = base_dir / "data" / "metrics_jobs.jsonl"
    
    if not jsonl_path.exists():
        logger.info("No JSONL metrics file found. Skipping migration.")
        return
        
    db = DatabaseStorage(db_path)
    sql_cache = SQLiteRelevanceCache(db)
    
    migrated_count = 0
    with jsonl_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                if isinstance(record, dict):
                    sql_cache.add_metric(record)
                    migrated_count += 1
            except Exception as e:
                logger.error(f"Failed to migrate record: {e}")
                
    logger.info(f"Successfully migrated {migrated_count} records to SQLite database!")
    
if __name__ == "__main__":
    migrate()
