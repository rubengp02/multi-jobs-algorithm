import requests
from bs4 import BeautifulSoup

search_url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=python&location=Spain&start=0"
headers = {"User-Agent": "Mozilla/5.0"}
r = requests.get(search_url, headers=headers)
soup = BeautifulSoup(r.text, "html.parser")
link = soup.select_one('a[href*="/jobs/view/"]')
url = link["href"] if link else ""
print("URL:", url)
job_id = url.split("?")[0].split("-")[-1]
print("Job ID:", job_id)

api_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
r2 = requests.get(api_url, headers=headers)
print("Status:", r2.status_code)
s2 = BeautifulSoup(r2.text, "html.parser")
desc = s2.find("div", class_="show-more-less-html__markup")
if desc:
    print("Desc length:", len(desc.get_text()))
    print(desc.get_text(separator=" ").strip()[:200])
