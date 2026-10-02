"""Compare the real automatic provider calls with the current /scan calls.

This diagnostic never sends Telegram messages and never writes to seen_jobs.txt.
It is deliberately kept separate from the bot runtime so it can inspect a
discrepancy without changing the state that the next production cycle uses.
"""

from __future__ import annotations

import argparse
import inspect
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from config import load_config
from main import build_providers, configure_logging, job_filter_reason
from storage import SeenStorage


def _error_text(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _job_record(job: Any, storage: SeenStorage, config: Any) -> dict[str, Any]:
    reason = job_filter_reason(job, config)
    return {
        "id": job.id,
        "source": job.source,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "url": job.url,
        "filter_reason": reason,
        "seen": storage.is_seen(job.source, job.id),
    }


def _summary(jobs: list[Any], storage: SeenStorage, config: Any) -> dict[str, Any]:
    reasons: dict[str, int] = {}
    valid_unseen = 0
    for job in jobs:
        reason = job_filter_reason(job, config) or "eligible"
        reasons[reason] = reasons.get(reason, 0) + 1
        if reason == "eligible" and not storage.is_seen(job.source, job.id):
            valid_unseen += 1
    return {"count": len(jobs), "reasons": reasons, "valid_unseen": valid_unseen}


def _normal_fetch(
    provider: Any, provider_name: str, first_iteration: bool
) -> list[Any]:
    # This mirrors run(): only LinkedIn receives the startup argument.
    if provider_name == "linkedin":
        return provider.fetch_jobs(startup_deep_scan=first_iteration)
    return provider.fetch_jobs()


def _scan_fetch(provider: Any) -> list[Any]:
    # This intentionally mirrors the current /scan command, including TypeError.
    return provider.fetch_jobs(startup_deep_scan=True)


def run_comparison(
    iterations: int, delay_seconds: float, selected_providers: set[str] | None
) -> dict[str, Any]:
    config = load_config()
    logger = configure_logging("INFO")
    providers = build_providers(config, logger)
    if selected_providers is not None:
        providers = {
            name: provider
            for name, provider in providers.items()
            if name in selected_providers
        }
    storage = SeenStorage(Path(config.seen_file))
    report: dict[str, Any] = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "state_changed": False,
        "telegram_sent": False,
        "config": {
            "enabled_providers": list(providers),
            "max_notifs_per_cycle": config.max_notifs_per_cycle,
            "silent_on_start": config.silent_on_start,
        },
        "iterations": [],
    }

    for iteration in range(1, iterations + 1):
        iteration_result: dict[str, Any] = {"number": iteration, "providers": []}
        for name, provider in providers.items():
            started = time.monotonic()
            normal_error: str | None = None
            scan_error: str | None = None
            try:
                normal_jobs = _normal_fetch(
                    provider, name, first_iteration=iteration == 1
                )
            except Exception as exc:
                normal_jobs = []
                normal_error = _error_text(exc)
            try:
                scan_jobs = _scan_fetch(provider)
            except Exception as exc:
                scan_jobs = []
                scan_error = _error_text(exc)

            normal_by_id = {job.id: job for job in normal_jobs}
            scan_by_id = {job.id: job for job in scan_jobs}
            scan_only = [
                job for job_id, job in scan_by_id.items() if job_id not in normal_by_id
            ]
            normal_only = [
                job for job_id, job in normal_by_id.items() if job_id not in scan_by_id
            ]

            iteration_result["providers"].append(
                {
                    "name": name,
                    "fetch_signature": str(inspect.signature(provider.fetch_jobs)),
                    "seconds": round(time.monotonic() - started, 2),
                    "normal": _summary(normal_jobs, storage, config),
                    "scan": _summary(scan_jobs, storage, config),
                    "normal_error": normal_error,
                    "scan_error": scan_error,
                    "scan_only_valid_unseen": [
                        _job_record(job, storage, config)
                        for job in scan_only
                        if job_filter_reason(job, config) is None
                        and not storage.is_seen(job.source, job.id)
                    ],
                    "normal_only_valid_unseen": [
                        _job_record(job, storage, config)
                        for job in normal_only
                        if job_filter_reason(job, config) is None
                        and not storage.is_seen(job.source, job.id)
                    ],
                }
            )
        report["iterations"].append(iteration_result)
        if iteration < iterations and delay_seconds:
            time.sleep(delay_seconds)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--delay-seconds", type=float, default=5)
    parser.add_argument(
        "--providers",
        help="Comma-separated enabled providers to audit; defaults to all enabled providers.",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/scan_equivalence_report.json")
    )
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be at least 1")

    selected_providers = (
        {name.strip().lower() for name in args.providers.split(",") if name.strip()}
        if args.providers
        else None
    )
    report = run_comparison(args.iterations, args.delay_seconds, selected_providers)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {"output": str(args.output), "iterations": args.iterations},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
