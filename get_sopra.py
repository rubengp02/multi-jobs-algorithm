import requests

r = requests.get(
    "https://api.smartrecruiters.com/v1/companies/SopraSteria1/postings?country=es&limit=100"
)
jobs = r.json().get("content", [])
print(f"Total: {len(jobs)}")
for j in jobs[:20]:
    print(f"- {j['name']} ({j['location']['city']})")
