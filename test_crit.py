from bs4 import BeautifulSoup
from curl_cffi import requests

r = requests.get("https://empleo.grupo-crit.com/jobs", impersonate="chrome")
soup = BeautifulSoup(r.text, "html.parser")
for a in soup.find_all("a", href=True):
    if "/jobs/" in a["href"]:
        print(a["href"], a.text.strip())
