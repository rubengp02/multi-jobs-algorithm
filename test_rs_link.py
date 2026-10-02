import requests
from bs4 import BeautifulSoup

r = requests.get(
    "https://www.randstad.es/candidatos/ofertas-empleo/",
    headers={"User-Agent": "Mozilla/5.0"},
)
soup = BeautifulSoup(r.text, "html.parser")
link = soup.select_one('a[href*="/oferta/"]')
print("Link HTML:", str(link)[:1000])
