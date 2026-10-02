import glob
import hashlib
import json
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


# 1. Get all sent hashes
sent_hashes = set()
audit_files = sorted(glob.glob("data/job_audit/*.jsonl"))
for af in audit_files[-3:]:  # last 3 days
    with open(af, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            if "jobs" in data:
                for job in data["jobs"]:
                    if job.get("outcome") == "sent":
                        sent_hashes.add(job["key"])
            if "outcomes" in data:
                for idx, outcome in data["outcomes"].items():
                    if outcome == "sent":
                        # need to get the key from jobs array
                        for job in data["jobs"]:
                            pass  # outcomes format changed
                    if isinstance(outcome, dict) and outcome.get("action") == "sent":
                        pass  # old format

# Actually, the job_audit format is:
# "jobs": [{"key": "hash", "outcome": "sent"}, ...]
for af in audit_files[-3:]:
    with open(af, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            if "jobs" in data:
                for job in data["jobs"]:
                    if job.get("outcome") == "sent":
                        sent_hashes.add(job["key"])

# 2. Find those jobs in metrics_jobs.jsonl
sent_jobs = []
with open("data/metrics_jobs.jsonl", "r", encoding="utf-8") as f:
    for line in f:
        job = json.loads(line)
        key = _job_key(job.get("source"), job.get("id"), job.get("url"))
        if key in sent_hashes:
            sent_jobs.append(job)

# Sort by timestamp
sent_jobs.sort(key=lambda x: x.get("timestamp", 0))

print(f"Total sent jobs found: {len(sent_jobs)}")
for job in sent_jobs[-20:]:
    print(f"ID: {job.get('id')} - {job.get('company')}")
    print(f"Puesto: {job.get('title')}")
    print(f"Ubicacion: {job.get('location')}")
    print(f"Modalidad: {job.get('modality')}")
    print("---")
