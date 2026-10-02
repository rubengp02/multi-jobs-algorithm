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


def process_provider(name, p):
    clean_name = name.replace("_", " ").title()
    try:
        jobs = p.fetch_jobs(max_results=50)  # strict cap to avoid hangs

        total = len(jobs)
        titles = sum(1 for j in jobs if getattr(j, "title", None) and j.title.strip())
        locations = sum(
            1 for j in jobs if getattr(j, "location", None) and j.location.strip()
        )

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
            has_mod = (
                bool(j.features.get("modality")) if hasattr(j, "features") else False
            )
            if not has_mod:
                text = (
                    getattr(j, "description", "")
                    + " "
                    + getattr(j, "title", "")
                    + " "
                    + getattr(j, "location", "")
                ).lower()
                has_mod = any(k in text for k in keywords)
            if has_mod:
                modalities += 1

        print(f"{clean_name}|{total}|{titles}|{locations}|{modalities}", flush=True)
    except Exception as e:
        print(f"{clean_name}|ERROR|{e}|0|0", flush=True)


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

print(
    "Portal|Ofertas Extraídas|Títulos Válidos|Ubicaciones Válidas|Modalidad Identificada",
    flush=True,
)
for name, p in providers:
    process_provider(name, p)

for c_name in CONSULTANCY_SOURCE_IDS:
    p = build_consultancy_provider(c_name, config, logger, None)
    process_provider(c_name, p)
