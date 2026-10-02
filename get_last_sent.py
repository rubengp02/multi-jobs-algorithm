import json

try:
    with open("data/job_audit/2026-09-13.jsonl", "r") as f:
        lines = f.readlines()

    sent_jobs = []
    for line in lines:
        data = json.loads(line)
        if "jobs" in data:
            for job in data["jobs"]:
                if job.get("outcome", {}).get("action") == "sent":
                    sent_jobs.append(job)
        if "outcomes" in data:
            for k, outcome in data["outcomes"].items():
                if outcome.get("action") == "sent":
                    sent_jobs.append({"key": k, "outcome": outcome})

    print(f"Encontradas {len(sent_jobs)} ofertas enviadas hoy.")
    for j in sent_jobs[-3:]:
        out = j["outcome"]
        print(f"TITLE: {out.get('title')}")
        print(f"COMPANY: {out.get('company')}")
        print(f"LOCATION: {out.get('location')}")
        print(f"SCORE: {out.get('relevance_score')}")
        print(f"URL: {out.get('url')}")
        print("---")
except Exception as e:
    print("Error:", e)
