from bs4 import BeautifulSoup
from curl_cffi import requests

resp = requests.get("https://montaner.com/candidatos/", impersonate="chrome")
soup = BeautifulSoup(resp.text, "html.parser")
for a in soup.find_all("a", href=True):
    href = a["href"]
    if "empleo" in href or "oferta" in href or "job" in href or "candidat" in href:
        print(href)
