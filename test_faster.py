from bs4 import BeautifulSoup
from curl_cffi import requests

r = requests.get("https://jobs.faster.es/jobs", impersonate="chrome")
soup = BeautifulSoup(r.text, "html.parser")
for a in soup.find_all("a", href=True):
    if "/jobs/" in a["href"]:
        print(a["href"], a.text.strip()[:30])
