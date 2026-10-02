from dataclasses import dataclass, field
import logging
import threading
from typing import Any
from config import BotConfig
from notifier import TelegramNotifier
from storage import SeenStorage, RelevanceDecisionCache
from analytics import MetricsStorage
from audit import JobAuditLedger

@dataclass
class RuntimeContext:
    config: BotConfig
    logger: logging.Logger
    notifier: TelegramNotifier
    storage: SeenStorage
    metrics: MetricsStorage
    audit_ledger: JobAuditLedger | None = field(default=None, repr=False)
    relevance_cache: RelevanceDecisionCache | None = field(default=None, repr=False)
    scrape_lock: Any = field(default_factory=threading.RLock, repr=False)
    linkedin_lock: Any = field(default_factory=threading.RLock, repr=False)

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
TODAY_DISCOVERED_JOBS: list = []
TODAY_DISCOVERED_DATE = None
LATEST_JOBS_CACHE: list = []
