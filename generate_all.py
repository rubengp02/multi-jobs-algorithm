import csv
import logging

from config import load_config
from providers import (
    CONSULTANCY_SOURCE_IDS,
    AccentureProvider,
    AccessiwayProvider,
    ExperisProvider,
    GreenhouseSpainProvider,
    IndeedProvider,
    InfoJobsProvider,
    LinkedInProvider,
    ManfredProvider,
    RemoteOKProvider,
    RemotiveProvider,
    SopraSteriaProvider,
    SystraProvider,
    TecnoempleoProvider,
    UPVSIEProvider,
    WWRProvider,
    build_consultancy_provider,
)

config = load_config()
logger = logging.getLogger("report")
logger.setLevel(logging.ERROR)

results = []


def process_provider(name, p):
    try:
        jobs = p.fetch_jobs()

        total = len(jobs)
        titles = sum(1 for j in jobs if j.title and j.title.strip())
        locations = sum(1 for j in jobs if j.location and j.location.strip())

        keywords = [
            "híbrid",
            "hibrid",
            "teletrabajo",
            "remot",
            "presencial",
            "home office",
            "work from home",
        ]
        modalities = 0
        for j in jobs:
            has_mod = bool(j.features.get("modality"))
            if not has_mod:
                text = (j.description + " " + j.title + " " + j.location).lower()
                has_mod = any(k in text for k in keywords)
            if has_mod:
                modalities += 1

        results.append(
            {
                "Portal": name.replace("_", " ").title(),
                "Ofertas Extraídas": total,
                "Títulos Válidos": titles,
                "Ubicaciones Válidas": locations,
                "Modalidad Identificada": modalities,
            }
        )
        print(f"Done: {name} ({total} jobs)")
    except Exception as e:
        results.append(
            {
                "Portal": name.replace("_", " ").title(),
                "Ofertas Extraídas": 0,
                "Títulos Válidos": 0,
                "Ubicaciones Válidas": 0,
                "Modalidad Identificada": 0,
            }
        )
        print(f"Error: {name} -> {e}")


providers = [
    ("LinkedIn", LinkedInProvider(config, logger, None)),
    ("InfoJobs", InfoJobsProvider(config, logger, None)),
    ("Tecnoempleo", TecnoempleoProvider(config, logger, None)),
    ("Manfred", ManfredProvider(config, logger, None)),
    ("Indeed", IndeedProvider(config, logger, None)),
    ("Remotive", RemotiveProvider(config, logger, None)),
    ("WWR", WWRProvider(config, logger, None)),
    ("Greenhouse Spain", GreenhouseSpainProvider(config, logger, None)),
    ("RemoteOK", RemoteOKProvider(config, logger, None)),
    ("UPV SIE", UPVSIEProvider(config, logger, None)),
    ("Experis", ExperisProvider(config, logger, None)),
    ("Accessiway", AccessiwayProvider(config, logger, None)),
    ("Sopra Steria", SopraSteriaProvider(config, logger, None)),
    ("Systra", SystraProvider(config, logger, None)),
    ("Accenture", AccentureProvider(config, logger, None)),
]

for name, p in providers:
    process_provider(name, p)

for c_name in CONSULTANCY_SOURCE_IDS:
    p = build_consultancy_provider(c_name, config, logger, None)
    process_provider(c_name, p)

with open("reporte_todos.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "Portal",
            "Ofertas Extraídas",
            "Títulos Válidos",
            "Ubicaciones Válidas",
            "Modalidad Identificada",
        ],
    )
    writer.writeheader()
    writer.writerows(results)

print("\n--- REPORT ---")
print(
    "| Portal | Ofertas Extraídas | Títulos Válidos | Ubicaciones Válidas | Modalidad Identificada |"
)
print(
    "|--------|-------------------|-----------------|---------------------|------------------------|"
)
for r in results:
    print(
        f"| {r['Portal']} | {r['Ofertas Extraídas']} | {r['Títulos Válidos']} | {r['Ubicaciones Válidas']} | {r['Modalidad Identificada']} |"
    )
