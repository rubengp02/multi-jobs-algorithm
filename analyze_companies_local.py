import json
from collections import defaultdict

jobs_file = "metrics_jobs.jsonl"
company_jobs = defaultdict(list)

with open(jobs_file, "r", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        try:
            job = json.loads(line)
            loc = job.get("location", "").lower()
            is_val = job.get("is_valencia", False)
            if (
                is_val
                or "valencia" in loc
                or "gandia" in loc
                or "almussafes" in loc
                or "paterna" in loc
            ):
                title = job.get("title", "")
                company = job.get("company", "Desconocida")
                company_jobs[company].append(title)
        except:
            pass

print("=== EMPRESAS DE VALENCIA (SIN FILTRO DE RELEVANCIA) ===")
for company, titles in sorted(
    company_jobs.items(), key=lambda x: len(x[1]), reverse=True
)[:25]:
    unique = list(set(titles))
    print(
        f"\nEmpresa: {company} ({len(titles)} publicaciones, {len(unique)} roles distintos)"
    )
    for t in unique[:3]:
        print(f"  - {t}")
