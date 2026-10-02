from bs4 import BeautifulSoup
from curl_cffi import requests

r = requests.get(
    "https://www.infojobs.net/jobsearch/search-results/list.xhtml?keyword=python",
    impersonate="chrome",
)
soup = BeautifulSoup(r.text, "html.parser")

links = soup.select("a[href*='/oferta/']")
print("Links containing /oferta/:", len(links))
for a in links[:10]:
    print(a.get("href"), "->", a.get_text(strip=True)[:50])

print("\\nLooking for __NEXT_DATA__ or __INITIAL_PROPS__")
for s in soup.find_all("script"):
    if s.string:
        if "__NEXT_DATA__" in s.string:
            print("Found __NEXT_DATA__")
        if "__INITIAL_PROPS__" in s.string:
            print("Found __INITIAL_PROPS__")
