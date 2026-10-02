import json

providers = [
    "accenture",
    "sopra_steria",
    "bo_growth",
    "grupo_brio",
    "manfred",
    "remotive",
    "accessiway",
]

discards = {p: [] for p in providers}

with open("data/metrics_jobs.jsonl", "r") as f:
    lines = f.readlines()

for line in lines[-10000:]:
    try:
        data = json.loads(line)
        source = data.get("source")
        if source in providers:
            features = data.get("features", {})
            rel = features.get("relevance", {})
            status = rel.get("status")
            score = rel.get("score")
            if status == "rejected":
                discards[source].append(
                    {
                        "title": data.get("title"),
                        "score": score,
                        "neg": rel.get("negative_evidence"),
                    }
                )
    except:
        pass

for p in providers:
    print(f"\n--- {p.upper()} ({len(discards[p])} discarded) ---")
    for d in discards[p][-10:]:
        print(f"[{d['score']}] {d['title']} -> Neg: {d['neg']}")
