import re

from curl_cffi import requests

resp = requests.get(
    "https://marlex.ofertas-trabajo.infojobs.net/ofertas", impersonate="chrome"
)
urls = re.findall(r"href=[\"\']([^\"\']+)[\"\']", resp.text)
for u in urls:
    if (
        "oferta" in u.lower()
        or "job" in u.lower()
        or "ofertas-trabajo" in u.lower()
        or "empleo" in u.lower()
    ):
        print(u)
