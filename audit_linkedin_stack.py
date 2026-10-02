"""Audit LinkedIn descriptions and extracted technology labels without side effects.

This module deliberately avoids ``main.py``, storage and Telegram. It is useful
to validate the live guest endpoint after changing the description extractor or
the direct-evidence technology catalog.
"""

from __future__ import annotations

import logging
import urllib.parse
from collections import Counter

from config import load_config
from enricher import enrich_job_description
from matcher import extract_tech_stack
from providers.linkedin import LinkedInProvider


def _sample_jobs(provider: LinkedInProvider, count: int) -> list:
    """Collect up to ``count`` distinct jobs using the provider's guest parser."""
    configured_urls = list(
        dict.fromkeys(
            url.strip()
            for url in (provider.config.linkedin_urls + [provider.config.linkedin_url])
            if url.strip()
        )
    )
    jobs_by_id = {}
    for url_index, url in enumerate(configured_urls, start=1):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        params = {key: values[0] for key, values in query.items() if values}
        params.update({"sortBy": "DD", "f_TPR": "r86400"})
        for offset in (0, 25, 50, 75):
            params["start"] = str(offset)
            batch = provider._fetch_guest_page(params, is_1h_step=False)
            print(
                f"FETCH url={url_index} start={offset} cards={len(batch)} "
                f"distinct={len(jobs_by_id)}",
                flush=True,
            )
            if not batch:
                break
            for _, job in batch:
                jobs_by_id.setdefault(job.id, job)
            if len(jobs_by_id) >= count:
                return list(jobs_by_id.values())[:count]
    return list(jobs_by_id.values())[:count]


def main() -> None:
    logger = logging.getLogger("linkedin-stack-audit")
    logger.setLevel(logging.WARNING)
    provider = LinkedInProvider(load_config(), logger)
    jobs = _sample_jobs(provider, count=30)
    print(f"AUDIT_INPUT jobs={len(jobs)}", flush=True)

    ui_phrase = "usa la ia para evaluar cómo encajarías"
    empty_descriptions = 0
    ui_leaks = 0
    tool_counts: Counter[str] = Counter()
    for index, job in enumerate(jobs, start=1):
        description = enrich_job_description(job, logger=logger)
        stack = extract_tech_stack(f"{job.title} {description}")
        empty_descriptions += int(len(description) <= 50)
        ui_leaks += int(ui_phrase in description.lower())
        tool_counts.update(stack)
        print(
            f"JOB {index:02d} | id={job.id} | description_chars={len(description)} | "
            f"stack={', '.join(stack) if stack else '-'} | title={job.title}",
            flush=True,
        )

    print(
        f"AUDIT_RESULT analysed={len(jobs)} empty_descriptions={empty_descriptions} "
        f"linkedin_ui_leaks={ui_leaks} unique_tools={len(tool_counts)}",
        flush=True,
    )
    print(
        "TOOLS "
        + ", ".join(f"{tool}:{count}" for tool, count in tool_counts.most_common()),
        flush=True,
    )


if __name__ == "__main__":
    main()
