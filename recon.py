import json

from bs4 import BeautifulSoup
from curl_cffi import requests

urls = {
    "eurofirms": "https://jobs.eurofirms.com/es/es/",
    "synergie": "https://www.synergie.es/busco-trabajo/",
    "talent_search_people": "https://www.talentsearchpeople.com/es/ofertas-de-empleo/",
    "marlex": "https://www.marlex.net/es/candidaturas",
    "grupo_crit": "https://empleo.grupo-crit.com/",
    "faster": "https://faster.es/portal-de-empleo/",
    "nortempo": "https://empleo.nortempo.com/search_offers/0/",
    "etalentum": "https://www.etalentum.com/es/candidatos/encuentra-trabajo.html",
    "prosolbia": "https://prosolbia.com/ofertas/",
    "montaner": "https://montaner.com/candidatos/",
}

results = {}
for name, url in urls.items():
    try:
        resp = requests.get(url, impersonate="chrome", timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")

        anchors = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if len(text) > 5 and (
                "ofer" in href
                or "job" in href
                or "vacan" in href
                or "candidat" in href
                or "offer" in href
            ):
                anchors.append(f"{text} -> {href}")

        classes = set()
        for d in soup.find_all(["div", "article", "li"]):
            c = d.get("class", [])
            if any(
                "card" in cls.lower()
                or "job" in cls.lower()
                or "oferta" in cls.lower()
                or "item" in cls.lower()
                for cls in c
            ):
                classes.add(" ".join(c))

        results[name] = {
            "status": resp.status_code,
            "anchors": anchors[:15],
            "classes": list(classes)[:10],
        }
    except Exception as e:
        results[name] = {"error": str(e)}

with open("/home/rubengaona/bots/bot_multi_jobs/recon_results.json", "w") as f:
    json.dump(results, f, indent=2)
