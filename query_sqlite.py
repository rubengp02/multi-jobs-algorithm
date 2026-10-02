import json
import sqlite3

try:
    conn = sqlite3.connect("data/bot_memory.db")
    c = conn.cursor()
    c.execute(
        "SELECT id, source, job_id, decision FROM relevance_cache ORDER BY timestamp DESC LIMIT 5"
    )
    rows = c.fetchall()

    print(f"Encontradas {len(rows)} filas.")
    for r in rows:
        dec = json.loads(r[3])
        print(f"ID: {r[0]}")
        print(f"STATUS: {dec.get('status')}")
        print(f"SCORE: {dec.get('score')}")
        print("---")
except Exception as e:
    print("Error:", e)
