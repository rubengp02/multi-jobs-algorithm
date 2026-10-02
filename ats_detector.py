from curl_cffi import requests

targets = {
    "Synergie": "https://www.synergie.es/busco-trabajo/",
    "Marlex": "https://www.marlex.net/es/candidaturas",
    "Grupo Crit": "https://empleo.grupo-crit.com/",
    "Prosolbia": "https://prosolbia.com/ofertas/",
    "Melt Group": "https://meltgroup.com/ofertas-de-empleo/",
    "Grupo Noas": "https://www.gruponoas.es/ofertas-de-trabajo/",
    "Faster": "https://faster.es/portal-de-empleo/",
}

for name, url in targets.items():
    try:
        resp = requests.get(url, impersonate="chrome", timeout=10)
        html = resp.text.lower()
        ats_found = []
        for ats in [
            "epreselec",
            "bizneo",
            "teamtailor",
            "infojobs",
            "greenhouse",
            "workday",
            "breezy",
            "lever",
        ]:
            if ats in html:
                ats_found.append(ats)
        print(f"{name}: {ats_found}")
    except Exception as e:
        print(f"{name}: Error {e}")
