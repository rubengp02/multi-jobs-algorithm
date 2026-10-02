import json
import sqlite3
from datetime import datetime

try:
    conn = sqlite3.connect("data/bot_memory.db")
    c = conn.cursor()
    # Get all jobs from relevance_cache in the last 24 hours
    # timestamp is in seconds
    now = datetime.now().timestamp()
    yesterday = now - 24 * 3600

    c.execute(
        "SELECT id, source, job_id, decision, timestamp FROM relevance_cache WHERE timestamp > ? ORDER BY timestamp ASC",
        (yesterday,),
    )
    rows = c.fetchall()

    print(f"Total jobs evaluated in relevance cache (24h): {len(rows)}")

    accepted = []
    warnings = []
    rejected = []

    for r in rows:
        dec = json.loads(r[3])
        status = dec.get("status")
        score = dec.get("score", 0)
        family = dec.get("family", "")

        # We need location, company, etc. Those are not in relevance_cache!
        # But we can just count them.
        item = {
            "id": r[2],
            "source": r[1],
            "status": status,
            "score": score,
            "family": family,
        }

        if status == "accepted":
            accepted.append(item)
        elif status == "warning":
            warnings.append(item)
        else:
            rejected.append(item)

    print(f"Accepted: {len(accepted)}")
    print(f"Warnings: {len(warnings)}")
    print(f"Rejected: {len(rejected)}")

    print("\\n--- ACCEPTED ---")
    for a in accepted[-10:]:
        print(a)

    print("\\n--- WARNINGS ---")
    for w in warnings[-10:]:
        print(w)

    print("\\n--- REJECTED (SAMPLE) ---")
    for r in rejected[-10:]:
        print(r)

except Exception as e:
    print("Error:", e)
