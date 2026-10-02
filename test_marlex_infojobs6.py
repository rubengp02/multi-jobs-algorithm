from bs4 import BeautifulSoup
from curl_cffi import requests

resp = requests.get(
    "https://marlex.ofertas-trabajo.infojobs.net/ofertas", impersonate="chrome"
)
soup = BeautifulSoup(resp.text, "html.parser")
for a in soup.find_all("a", href=True):
    print(a["href"])
