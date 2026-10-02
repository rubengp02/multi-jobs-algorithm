from typing import Any

# Global status tracking dictionary shared across threads/tasks
CURRENT_STATUS: dict[str, Any] = {
    "is_scraping_now": False,
    "last_cycle_start": None,
    "last_cycle_end": None,
    "next_cycle_estimate": None,
    "total_cycles_completed": 0,
    "last_cycle_stats": {},
    "last_linkedin_extension_ingest": {},
    "linkedin_dual": {}
}

CYCLE_LOGS: list[dict[str, Any]] = []

BOT_PAUSED: bool = False
