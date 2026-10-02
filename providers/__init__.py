from __future__ import annotations

from models import JobItem, JobProvider
from providers.accenture import AccentureProvider
from providers.accessiway import AccessiwayProvider
from providers.consultancies import (
    CONSULTANCY_SOURCE_IDS,
    CONSULTANCY_SOURCES,
    PublicConsultancyProvider,
    build_consultancy_provider,
)
from providers.experis import ExperisProvider
from providers.greenhouse_spain import GreenhouseSpainProvider
from providers.indeed import IndeedProvider
from providers.infojobs import InfoJobsProvider
from providers.linkedin import LinkedInProvider
from providers.manfred import ManfredProvider
from providers.remoteok import RemoteOKProvider
from providers.remotive import RemotiveProvider
from providers.sopra_steria import SopraSteriaProvider
from providers.systra import SystraProvider
from providers.tecnoempleo import TecnoempleoProvider
from providers.upv_sie import UPVSIEProvider
from providers.wwr import WWRProvider

__all__ = [
    "CONSULTANCY_SOURCES",
    "CONSULTANCY_SOURCE_IDS",
    "AccentureProvider",
    "AccessiwayProvider",
    "ExperisProvider",
    "GreenhouseSpainProvider",
    "IndeedProvider",
    "InfoJobsProvider",
    "JobItem",
    "JobProvider",
    "LinkedInProvider",
    "ManfredProvider",
    "PublicConsultancyProvider",
    "RemoteOKProvider",
    "RemotiveProvider",
    "SopraSteriaProvider",
    "SystraProvider",
    "TecnoempleoProvider",
    "UPVSIEProvider",
    "WWRProvider",
    "build_consultancy_provider",
]
