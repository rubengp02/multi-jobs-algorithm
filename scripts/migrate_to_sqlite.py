import json
import sqlite3
import time
from pathlib import Path


def migrate():
    base_dir = Path(__file__).resolve().parent.parent
    db_path = base_dir / "data" / "bot_memory.db"
    seen_txt = base_dir / "data" / "seen_jobs.txt"
    cache_json = base_dir / "data" / "relevance_decisions.json"

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))

    conn.execute("""CREATE TABLE IF NOT EXISTS seen_jobs (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        job_id TEXT NOT NULL,
        timestamp INTEGER NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS relevance_cache (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        job_id TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        decision TEXT NOT NULL,
        timestamp INTEGER NOT NULL
    )""")

    count_seen = 0
    if seen_txt.exists():
        with open(seen_txt, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(":", 1)
                if len(parts) == 2:
                    source, job_id = parts
                    conn.execute(
                        "INSERT OR IGNORE INTO seen_jobs (id, source, job_id, timestamp) VALUES (?, ?, ?, ?)",
                        (line, source, job_id, int(time.time())),
                    )
                    count_seen += 1

    count_rel = 0
    if cache_json.exists():
        try:
            with open(cache_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                parts = k.split(":", 1)
                if len(parts) == 2:
                    source, job_id = parts
                    conn.execute(
                        "INSERT OR REPLACE INTO relevance_cache (id, source, job_id, fingerprint, decision, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            k,
                            source,
                            job_id,
                            v.get("fingerprint", ""),
                            json.dumps(v.get("decision", {})),
                            int(time.time()),
                        ),
                    )
                    count_rel += 1
        except Exception:
            pass

    conn.commit()
    conn.close()
    print(f"Migrated {count_seen} seen jobs and {count_rel} relevance cache entries.")


if __name__ == "__main__":
    migrate()
