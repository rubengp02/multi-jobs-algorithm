import json

errors = []
with open("metrics_jobs_rpi.jsonl", "r", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        try:
            job = json.loads(line)
            title = str(job.get("title", "")).lower()
            company = str(job.get("company", "")).lower()
            if (
                "error" in title
                or "error" in company
                or "error" in str(job.get("location", "")).lower()
            ):
                errors.append(
                    f"{job['source']} | {job['title']} | {job['company']} | {job['url']}"
                )
        except:
            pass

for e in errors[-20:]:
    print(e)
