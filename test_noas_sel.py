import re

from bs4 import BeautifulSoup
from curl_cffi import requests

r = requests.get("https://www.gruponoas.es/ofertas-de-trabajo/", impersonate="chrome")
soup = BeautifulSoup(r.text, "html.parser")

print("ALL A TAGS WITH /oferta/:")
for a in soup.find_all("a", href=True):
    if "/oferta/" in a["href"]:
        print(a["href"], a.text.strip())

# Test regex logic from consultancies.py
print("\nREGEX TEST:")
patterns = [re.compile(r"/oferta/[^?#]+")]
selectors = ["a[href*='/oferta/']"]
for sel in selectors:
    for a in soup.select(sel):
        href = a.get("href")
        if not href:
            continue
        for p in patterns:
            if p.search(href):
                print(f"Matched {href}: {a.get_text(' ', strip=True)[:30]}")
