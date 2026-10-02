import glob
import hashlib
import json
from collections import Counter
from urllib.parse import urlsplit, urlunsplit


def _canonical_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        return urlunsplit(
            (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", "")
        )
    except ValueError:
        return url.strip()


def _job_key(source: str, job_id: str, url: str) -> str:
    source = (source or "unknown").strip().lower()
    value = "\x1f".join((source, str(job_id or ""), _canonical_url(url or "")))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


audit_files = sorted(glob.glob("data/job_audit/*.jsonl"))
outcomes = {}
for af in audit_files[-3:]:
    with open(af, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            if "jobs" in data:
                for job in data["jobs"]:
                    if job.get("outcome"):
                        outcomes[job["key"]] = job["outcome"]

jobs = []
with open("data/metrics_jobs.jsonl", "r", encoding="utf-8") as f:
    for line in f:
        jobs.append(json.loads(line))

jobs.sort(key=lambda x: x.get("timestamp", 0))

# We want the jobs processed since yesterday's patch (~ last 1000 jobs)
recent_jobs = jobs[-500:]

categories = Counter()
sent_jobs = []
rejected_jobs = []

for j in recent_jobs:
    k = _job_key(j.get("source"), j.get("id"), j.get("url"))
    outcome = outcomes.get(k)
    # Some older format outcomes might be a dict
    if isinstance(outcome, dict):
        outcome = outcome.get("action", "unknown")

    j["actual_outcome"] = str(outcome)
    categories[str(outcome)] += 1

    if str(outcome) == "sent":
        sent_jobs.append(j)
    elif str(outcome).startswith("discarded_relevance"):
        rejected_jobs.append(j)

print("--- AUDIT SUMMARY (LAST 500 JOBS) ---")
for k, v in categories.most_common():
    print(f"{k}: {v}")

print("\\n--- SENT JOBS (LAST 10) ---")
for j in sent_jobs[-10:]:
    print(f"[{j.get('id')}] {j.get('company')} - {j.get('title')}")
    print(f"  Loc: {j.get('location')} | Mod: {j.get('modality')}")
    rel = j.get("relevance", {})
    print(
        f"  Score: {rel.get('score')} | Family: {rel.get('family')} | Ev: {rel.get('positive_evidence')}"
    )

print("\\n--- REJECTED BY RELEVANCE (SAMPLE 10) ---")
for j in rejected_jobs[-10:]:
    print(f"[{j.get('id')}] {j.get('company')} - {j.get('title')}")
    print(f"  Loc: {j.get('location')} | Mod: {j.get('modality')}")
    rel = j.get("relevance", {})
    print(f"  Score: {rel.get('score')} | Family: {rel.get('family')}")
