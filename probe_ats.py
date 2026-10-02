import requests

urls = {
    "NTT Data": "https://careers.nttdata.com/",
    "Capgemini": "https://www.capgemini.com/es-es/careers/",
    "Indra": "https://www.minsait.com/es/unete-nuestro-equipo",
    "Accenture": "https://www.accenture.com/es-es/careers",
    "Edicom": "https://www.edicomgroup.es/ofertas-de-empleo",
    "S2 Grupo": "https://s2grupo.es/talento/",
    "Hiberus": "https://www.hiberus.com/trabaja-con-nosotros",
}

for name, url in urls.items():
    try:
        r = requests.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        txt = r.text.lower()
        ats = []
        if "workday" in txt or "wd3.myworkdayjobs" in txt:
            ats.append("Workday")
        if "successfactors" in txt or "career8.successfactors" in txt:
            ats.append("SuccessFactors")
        if "smartrecruiters" in txt:
            ats.append("SmartRecruiters")
        if "teamtailor" in txt:
            ats.append("TeamTailor")
        if "infojobs" in txt:
            ats.append("InfoJobs")
        if "icims" in txt:
            ats.append("iCIMS")
        if "taleo" in txt:
            ats.append("Taleo")
        print(f"{name}: {ats if ats else 'Custom/Unknown'}")
    except Exception:
        print(f"{name}: Error")
