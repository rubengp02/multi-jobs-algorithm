from __future__ import annotations

import json
import logging
import time
from collections import Counter
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from matcher import calculate_match_score, extract_job_features
from models import JobItem
from database import DatabaseStorage, SQLiteRelevanceCache


class MetricsStorage:
    """
    Lightweight, append-only JSONL storage for all discovered and notified jobs.
    Allows historical analytics on demand without occupying heavy memory or disk.
    """

    def __init__(self, db: DatabaseStorage, logger: logging.Logger | None = None) -> None:
        self.db = db
        # Para compatibilidad reutilizamos la interfaz SQLiteRelevanceCache
        # que tiene los metodos add_metric y get_all_metrics
        self.sql_cache = SQLiteRelevanceCache(self.db)
        self.logger = logger or logging.getLogger("MetricsStorage")

    async def record_job(self, job: JobItem, description: str = "") -> dict[str, Any]:
        """
        Calculates all analytical dimensions and appends a single metric atomically.
        """
        description = description or job.description
        features = job.features or extract_job_features(
            job.title, description, job.location
        )
        score, tags, stack, salary, experience, modality, company_type, freshness = (
            calculate_match_score(
                job.title, description, job.location, job.company, job.posted_within_1h
            )
        )
        experience_details = features.get("experience", {})
        if isinstance(experience_details, dict):
            experience = str(experience_details.get("display") or experience)
        stack = list(features.get("stack") or stack)
        salary = str(features.get("salary") or salary)
        modality = str(features.get("modality") or modality)

        loc_l = job.location.lower()
        title_l = job.title.lower()

        is_valencia = any(
            v in loc_l or v in title_l
            for v in [
                "valencia",
                "valència",
                "paterna",
                "almussafes",
                "sagunto",
                "riba-roja",
                "torrent",
                "alboraya",
                "alzira",
                "gandia",
            ]
        )
        is_remote = (modality == "100% Remoto") or any(
            r in loc_l or r in title_l
            for r in ["remoto", "remote", "teletrabajo", "100% remoto", "full remote"]
        )

        record: dict[str, Any] = {
            "id": job.id,
            "source": job.source,
            "title": job.title,
            "company": job.company,
            "company_type": company_type,
            "freshness": freshness,
            "location": job.location,
            "url": job.url,
            "timestamp": int(time.time()),
            "datetime": datetime.now(timezone.utc).isoformat(),
            "match_score": score,
            "experience": experience,
            "modality": modality,
            "salary": salary,
            "tags": tags,
            "stack": stack,
            "features": features,
            "is_valencia": is_valencia,
            "is_remote": is_remote,
        }

        try:
            await self.sql_cache.add_metric(record)
        except Exception as exc:
            self.logger.error("Failed to insert metric to SQLite: %s", exc)

        return record

    async def iter_records(self) -> AsyncIterator[dict[str, Any]]:
        """Devuelve un iterador sobre las métricas almacenadas en SQLite."""
        try:
            records = await self.sql_cache.get_all_metrics()
            for r in records:
                yield r
        except Exception as exc:
            self.logger.error("Failed to read metrics from SQLite: %s", exc)

    async def load_all_records(self) -> list[dict[str, Any]]:
        """Compatibility helper for the rare callers that explicitly need a list."""
        records = []
        async for r in self.iter_records():
            records.append(r)
        return records

    async def generate_analytics_report(self) -> str:
        """
        Computes market statistics from all stored metrics records.
        """
        total_jobs = 0
        companies: Counter[str] = Counter()
        techs: Counter[str] = Counter()
        experiences: Counter[str] = Counter()
        sources: Counter[str] = Counter()
        product_count = consultancy_count = valencia_count = remote_count = 0
        async for record in self.iter_records():
            total_jobs += 1
            company = str(record.get("company") or "")
            if company and company != "Empresa no indicada":
                companies[company] += 1
            company_type = str(record.get("company_type") or "")
            product_count += int("Producto" in company_type)
            consultancy_count += int("Consultora" in company_type)
            for tech in record.get("stack", []):
                techs[str(tech)] += 1
            experiences[
                str(record.get("experience") or "Flexible / No especificada")
            ] += 1
            valencia_count += int(bool(record.get("is_valencia")))
            remote_count += int(bool(record.get("is_remote")))
            sources[str(record.get("source") or "unknown").upper()] += 1

        if not total_jobs:
            return "📊 *Métricas de Mercado*\n\nTodavía no hay registros acumulados en el archivo de métricas. Empezarán a generarse con cada nueva alerta."
        top_companies = companies.most_common(5)
        top_techs = techs.most_common(6)
        exp_counts = experiences.most_common()
        source_counts = sources.most_common()

        lines = [
            "📈 *ESTUDIO DE MERCADO Y MÉTRICAS DE EMPLEO*",
            f"📊 Total de vacantes analizadas: *{total_jobs}*\n",
            "🏢 *Distribución de Empleadores:*",
            f"  • 🚀 *Empresa de Producto / Cliente Final:* {product_count} ({product_count / total_jobs * 100:.0f}%)",
            f"  • 💼 *Consultora IT / Selección:* {consultancy_count} ({consultancy_count / total_jobs * 100:.0f}%)",
        ]

        if top_companies:
            lines.append("\n🏆 *Top Empresas con más vacantes:*")
            for comp, cnt in top_companies:
                lines.append(f"  • *{comp}*: {cnt} ofertas")

        lines.append("\n🛠️ *Radar de Tecnologías más Demandadas:*")
        for tech, cnt in top_techs:
            lines.append(
                f"  • *{tech}*: {cnt} menciones ({cnt / total_jobs * 100:.0f}% de ofertas)"
            )

        lines.append("\n🎓 *Distribución por Nivel de Experiencia:*")
        for exp, cnt in exp_counts:
            lines.append(f"  • *{exp}*: {cnt} ofertas ({cnt / total_jobs * 100:.0f}%)")

        lines.append("\n📍 *Distribución Geográfica:*")
        lines.append(
            f"  • 🍊 *Valencia y Área Metropolitana:* {valencia_count} ({valencia_count / total_jobs * 100:.0f}%)"
        )
        lines.append(
            f"  • 🏠 *100% Remoto (España):* {remote_count} ({remote_count / total_jobs * 100:.0f}%)"
        )

        lines.append("\n🌐 *Volumen por Portal:*")
        for src, cnt in source_counts:
            lines.append(f"  • *{src}*: {cnt} ofertas")

        return "\n".join(lines)
