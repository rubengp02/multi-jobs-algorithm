from bs4 import BeautifulSoup
from curl_cffi import requests

r = requests.get("https://www.gruponoas.es/ofertas-de-trabajo/", impersonate="chrome")
soup = BeautifulSoup(r.text, "html.parser")

for a in soup.find_all("a", href=True):
    if "/oferta/" in a["href"]:
        text = a.get_text(" ", strip=True)
        print(f"Length: {len(text)} | Text: {text[:50]}...")
