import requests

url = "https://www.manpower.es/api/services/Jobs/searchjobs"
headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
payload = {
    "filter": {
        "offset": 0,
        "totalCount": 0,
        "limit": 50,
        "searchkeyword": None,
        "haslocation": False,
        "language": "es",
    }
}
r = requests.post(url, headers=headers, json=payload)
data = r.json()
items = data.get("jobsItems", [])
print(f"Found {len(items)} jobs")
if items:
    for job in items[:5]:
        print(job.get("jobTitle"), job.get("jobID"), job.get("jobLocation"))
