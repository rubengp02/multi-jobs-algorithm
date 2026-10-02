import requests

url = "https://www.manpower.es/api/services/Jobs/searchjobs"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Content-Type": "application/json",
    "Accept": "application/json",
}
payload = {
    "Keyword": "",
    "Location": "",
    "JobType": "",
    "Industry": "",
    "PageNum": 1,
    "Sort": "Date",
}
r = requests.post(url, headers=headers, json=payload)
print(r.status_code)
try:
    data = r.json()
    items = data.get("jobsItems", [])
    print(f"Found {len(items)} jobs")
    for i in range(min(5, len(items))):
        job = items[i]
        print(f"{job.get('jobTitle')} - {job.get('jobID')} - {job.get('jobLocation')}")
except Exception as e:
    print(r.text[:500])
    print(e)
