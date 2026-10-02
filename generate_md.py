import csv
import logging

from config import load_config
from providers.consultancies import build_consultancy_provider

config = load_config()
logger = logging.getLogger("report")
logger.setLevel(logging.ERROR)

portals = [
    "synergie",
    "marlex",
    "melt_group",
    "grupo_noas",
    "faster",
    "grupo_crit",
    "prosolbia",
]
keywords = [
    "híbrid",
    "hibrid",
    "teletrabajo",
    "remot",
    "presencial",
    "home office",
    "work from home",
]

results = []

print(
    "| Consultora | Ofertas Extraídas | Títulos Válidos | Ubicaciones Válidas | Modalidad Identificada | Estrategia |"
)
print(
    "|------------|-------------------|-----------------|---------------------|------------------------|------------|"
)

for p_name in portals:
    try:
        p = build_consultancy_provider(p_name, config, logger, None)
        jobs = p.fetch_jobs(max_pages=20, max_results=1000)

        total = len(jobs)
        titles = sum(1 for j in jobs if j.title and j.title.strip())
        locations = sum(1 for j in jobs if j.location and j.location.strip())

        modalities = 0
        for j in jobs:
            has_mod = bool(j.features.get("modality"))
            if not has_mod:
                text = (j.description + " " + j.title + " " + j.location).lower()
                has_mod = any(k in text for k in keywords)
            if has_mod:
                modalities += 1

        if p_name == "synergie":
            note = "Direct Astro API (Instant)"
        elif p_name == "marlex":
            note = "InfoJobs API Bypass"
        elif p_name == "melt_group":
            note = "Matador WP-JSON API Bypass"
        elif p_name == "grupo_noas":
            note = "Native HTML Scraping"
        elif p_name == "faster" or p_name == "grupo_crit":
            note = "Direct Bizneo ATS Scraping"
        elif p_name == "prosolbia":
            note = "Native PDF Extraction"

        display_name = p_name.replace("_", " ").title()
        print(
            f"| {display_name} | {total} | {titles} | {locations} | {modalities} | {note} |"
        )

        results.append(
            {
                "Consultora": display_name,
                "Ofertas": total,
                "Títulos": titles,
                "Ubicaciones": locations,
                "Modalidad": modalities,
                "Estrategia": note,
            }
        )
    except Exception as e:
        print(f"| {p_name} | ERROR | {e} | - | - | - |")

with open("reporte_extraccion.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "Consultora",
            "Ofertas",
            "Títulos",
            "Ubicaciones",
            "Modalidad",
            "Estrategia",
        ],
    )
    writer.writeheader()
    writer.writerows(results)
