from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class BotConfig:
    poll_seconds: int
    jitter_seconds: int
    timeout_seconds: int
    telegram_poll_timeout_seconds: int
    max_notifs_per_cycle: int
    silent_on_start: bool
    retry_on_zero_attempts: int
    retry_on_zero_delay_sec: int
    provider_retry_attempts: int
    provider_retry_delay_sec: int
    log_level: str

    enabled_providers: list[str]
    include_words: list[str]
    exclude_words: list[str]

    telegram_bot_token: str
    telegram_chat_id: str

    linkedin_url: str
    linkedin_urls: list[str]
    linkedin_session_dir: str
    linkedin_browser_channel: str
    linkedin_headless: bool
    linkedin_auto_login: bool
    linkedin_force_login_flow_test: bool
    linkedin_email: str
    linkedin_password: str
    linkedin_first_page_only: bool
    linkedin_max_jobs: int
    linkedin_startup_scrolls: int
    linkedin_scrolls: int
    linkedin_scroll_pause_sec: float
    linkedin_min_expected: int
    linkedin_verbose_logs: bool
    # In dual mode Chromium is primary. The public reader runs only inside the
    # reconciliation coordinator, never as an independent provider cycle.
    linkedin_extension_enabled: bool
    linkedin_extension_host: str
    linkedin_extension_port: int
    linkedin_extension_refresh_seconds: int
    linkedin_time_windows_seconds: tuple[int, ...]
    linkedin_inter_search_min_seconds: float
    linkedin_inter_search_max_seconds: float

    indeed_url: str
    indeed_max_results: int
    indeed_headless: bool
    indeed_session_dir: str
    indeed_min_expected: int

    infojobs_url: str
    infojobs_max_results: int
    infojobs_headless: bool
    infojobs_auto_accept_cookies: bool
    infojobs_session_dir: str
    infojobs_challenge_wait_sec: int
    infojobs_scroll_mode: str
    infojobs_scroll_steps: int
    infojobs_scroll_pause_ms: int
    infojobs_pages_to_scan: int
    infojobs_min_expected: int
    infojobs_verbose_logs: bool

    experis_max_results: int
    accessiway_max_results: int

    # Public consultancy boards are deliberately opt-in: their validation
    # status and ENABLED_PROVIDERS entry must both allow the source.
    consultancy_max_pages: int
    consultancy_max_results: int
    provider_inter_request_min_seconds: float
    provider_inter_request_max_seconds: float
    provider_validation_dir: str
    provider_validation_auto_on_anomaly: bool
    provider_validation_max_pages: int
    provider_validation_max_results: int

    # The daily audit only evaluates persisted runtime evidence.  It never
    # performs another scrape, changes seen jobs, or creates job alerts.
    daily_coverage_dir: str
    daily_coverage_lookback_hours: int
    daily_coverage_min_cycle_ratio: float
    daily_coverage_max_stale_minutes: int
    daily_coverage_telegram_summary: bool
    job_audit_retention_days: int
    operational_metrics_retention_days: int
    daily_coverage_retention_days: int
    provider_validation_retention_days: int
    relevance_cache_retention_days: int
    relevance_cache_max_items: int
    browser_session_backup_retention_days: int
    browser_extension_runtime_retention_days: int

    seen_file: str
    debug_dir: str
    debug_retention_days: int
    debug_max_files: int
    proxy_url: str | None = None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _env_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def _env_urls(name: str, fallback_single: str = "") -> list[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return [fallback_single] if fallback_single else []
    items = []
    for line in raw.replace("|", "\n").replace(";", "\n").split("\n"):
        url = line.strip()
        if url:
            items.append(url)
    return items or ([fallback_single] if fallback_single else [])


def _env_positive_int_tuple(name: str, default: str) -> tuple[int, ...]:
    """Parse a comma-separated positive integer list in stable order."""
    values: list[int] = []
    for candidate in os.getenv(name, default).split(","):
        try:
            value = int(candidate.strip())
        except ValueError:
            continue
        if value > 0 and value not in values:
            values.append(value)
    return tuple(values) or tuple(
        int(candidate)
        for candidate in default.split(",")
        if candidate.strip().isdigit()
    )


def _env_nonnegative_float(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(name, str(default))))
    except ValueError:
        return default


def load_config() -> BotConfig:
    base_dir = Path(__file__).resolve().parent
    load_dotenv(base_dir / '.env')

    if not os.getenv('TELEGRAM_BOT_TOKEN') or not os.getenv('TELEGRAM_CHAT_ID'):
        raise ValueError('❌ ERROR CRÍTICO: Falta el TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en el archivo .env. Por favor, copia el archivo .env.example a .env y rellénalo con tus credenciales antes de arrancar.')

    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    seen_file = data_dir / "seen_jobs.txt"

    single_linkedin_url = os.getenv("LINKEDIN_URL", "").strip()
    linkedin_urls = _env_urls("LINKEDIN_URLS", single_linkedin_url)

    return BotConfig(
        poll_seconds=int(os.getenv("POLL_SECONDS", "900")),
        jitter_seconds=int(os.getenv("JITTER_SECONDS", "20")),
        timeout_seconds=int(os.getenv("TIMEOUT_SECONDS", "25")),
        telegram_poll_timeout_seconds=int(
            os.getenv("TELEGRAM_POLL_TIMEOUT_SECONDS", "20")
        ),
        # Zero deliberately means unlimited; a positive value is an explicit cap.
        max_notifs_per_cycle=max(0, int(os.getenv("MAX_NOTIFS_PER_CYCLE", "0"))),
        silent_on_start=_env_bool("SILENT_ON_START", False),
        retry_on_zero_attempts=int(os.getenv("RETRY_ON_ZERO_ATTEMPTS", "1")),
        retry_on_zero_delay_sec=int(os.getenv("RETRY_ON_ZERO_DELAY_SEC", "5")),
        provider_retry_attempts=int(os.getenv("PROVIDER_RETRY_ATTEMPTS", "0")),
        provider_retry_delay_sec=int(os.getenv("PROVIDER_RETRY_DELAY_SEC", "5")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        enabled_providers=_env_list(
            "ENABLED_PROVIDERS",
            "linkedin,infojobs,tecnoempleo,manfred,remotive,greenhouse_spain,upv_sie,experis,accessiway",
        ),
        include_words=_env_list("INCLUDE_WORDS", ""),
        exclude_words=_env_list("EXCLUDE_WORDS", ""),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        linkedin_url=single_linkedin_url,
        linkedin_urls=linkedin_urls,
        linkedin_session_dir=os.getenv(
            "LINKEDIN_SESSION_DIR", "./data/linkedin_session"
        ),
        linkedin_browser_channel=os.getenv("LINKEDIN_BROWSER_CHANNEL", "").strip(),
        linkedin_headless=_env_bool("LINKEDIN_HEADLESS", True),
        linkedin_auto_login=_env_bool("LINKEDIN_AUTO_LOGIN", False),
        linkedin_force_login_flow_test=_env_bool(
            "LINKEDIN_FORCE_LOGIN_FLOW_TEST", False
        ),
        linkedin_email=os.getenv("LINKEDIN_EMAIL", "").strip(),
        linkedin_password=os.getenv("LINKEDIN_PASSWORD", "").strip(),
        linkedin_first_page_only=_env_bool("LINKEDIN_FIRST_PAGE_ONLY", True),
        # LinkedIn's useful scope is its first, newest results page.  Older
        # installations used 0 for "unbounded"; treat it as the safe page cap.
        linkedin_max_jobs=min(
            25, max(1, int(os.getenv("LINKEDIN_MAX_JOBS", "25")) or 25)
        ),
        linkedin_startup_scrolls=int(os.getenv("LINKEDIN_STARTUP_SCROLLS", "12")),
        linkedin_scrolls=int(os.getenv("LINKEDIN_SCROLLS", "6")),
        linkedin_scroll_pause_sec=float(os.getenv("LINKEDIN_SCROLL_PAUSE_SEC", "1.2")),
        linkedin_min_expected=int(os.getenv("LINKEDIN_MIN_EXPECTED", "1")),
        linkedin_verbose_logs=_env_bool("LINKEDIN_VERBOSE_LOGS", False),
        linkedin_extension_enabled=_env_bool("LINKEDIN_EXTENSION_ENABLED", False),
        linkedin_extension_host=os.getenv(
            "LINKEDIN_EXTENSION_HOST", "127.0.0.1"
        ).strip()
        or "127.0.0.1",
        linkedin_extension_port=int(os.getenv("LINKEDIN_EXTENSION_PORT", "8765")),
        linkedin_extension_refresh_seconds=max(
            60,
            int(
                os.getenv(
                    "LINKEDIN_EXTENSION_REFRESH_SECONDS",
                    os.getenv("POLL_SECONDS", "900"),
                )
            ),
        ),
        linkedin_time_windows_seconds=_env_positive_int_tuple(
            "LINKEDIN_TIME_WINDOWS_SECONDS", "1200,3600"
        ),
        linkedin_inter_search_min_seconds=_env_nonnegative_float(
            "LINKEDIN_INTER_SEARCH_MIN_SECONDS", 3.0
        ),
        linkedin_inter_search_max_seconds=_env_nonnegative_float(
            "LINKEDIN_INTER_SEARCH_MAX_SECONDS", 6.0
        ),
        indeed_url=os.getenv("INDEED_URL", ""),
        indeed_max_results=int(os.getenv("INDEED_MAX_RESULTS", "60")),
        indeed_headless=_env_bool("INDEED_HEADLESS", True),
        indeed_session_dir=os.getenv("INDEED_SESSION_DIR", "./data/indeed_session"),
        indeed_min_expected=int(os.getenv("INDEED_MIN_EXPECTED", "1")),
        infojobs_url=os.getenv("INFOJOBS_URL", ""),
        infojobs_max_results=int(os.getenv("INFOJOBS_MAX_RESULTS", "60")),
        infojobs_headless=_env_bool("INFOJOBS_HEADLESS", True),
        infojobs_auto_accept_cookies=_env_bool("INFOJOBS_AUTO_ACCEPT_COOKIES", True),
        infojobs_session_dir=os.getenv(
            "INFOJOBS_SESSION_DIR", "./data/infojobs_session"
        ),
        infojobs_challenge_wait_sec=int(os.getenv("INFOJOBS_CHALLENGE_WAIT_SEC", "40")),
        infojobs_scroll_mode=os.getenv("INFOJOBS_SCROLL_MODE", "mouse"),
        infojobs_scroll_steps=int(os.getenv("INFOJOBS_SCROLL_STEPS", "10")),
        infojobs_scroll_pause_ms=int(os.getenv("INFOJOBS_SCROLL_PAUSE_MS", "700")),
        infojobs_pages_to_scan=int(os.getenv("INFOJOBS_PAGES_TO_SCAN", "3")),
        infojobs_min_expected=int(os.getenv("INFOJOBS_MIN_EXPECTED", "1")),
        infojobs_verbose_logs=_env_bool("INFOJOBS_VERBOSE_LOGS", False),
        experis_max_results=int(os.getenv("EXPERIS_MAX_RESULTS", "60")),
        accessiway_max_results=int(os.getenv("ACCESSIWAY_MAX_RESULTS", "100")),
        consultancy_max_pages=max(1, int(os.getenv("CONSULTANCY_MAX_PAGES", "2"))),
        consultancy_max_results=max(1, int(os.getenv("CONSULTANCY_MAX_RESULTS", "50"))),
        provider_inter_request_min_seconds=max(
            0.0, float(os.getenv("PROVIDER_INTER_REQUEST_MIN_SECONDS", "3"))
        ),
        provider_inter_request_max_seconds=max(
            0.0, float(os.getenv("PROVIDER_INTER_REQUEST_MAX_SECONDS", "6"))
        ),
        provider_validation_dir=os.getenv(
            "PROVIDER_VALIDATION_DIR", str(data_dir / "provider_validation")
        ),
        provider_validation_auto_on_anomaly=_env_bool(
            "PROVIDER_VALIDATION_AUTO_ON_ANOMALY", True
        ),
        provider_validation_max_pages=max(
            1, int(os.getenv("PROVIDER_VALIDATION_MAX_PAGES", "5"))
        ),
        provider_validation_max_results=max(
            1, int(os.getenv("PROVIDER_VALIDATION_MAX_RESULTS", "100"))
        ),
        daily_coverage_dir=os.getenv(
            "DAILY_COVERAGE_DIR", str(data_dir / "daily_coverage")
        ),
        daily_coverage_lookback_hours=max(
            1, int(os.getenv("DAILY_COVERAGE_LOOKBACK_HOURS", "26"))
        ),
        daily_coverage_min_cycle_ratio=min(
            1.0, max(0.0, float(os.getenv("DAILY_COVERAGE_MIN_CYCLE_RATIO", "0.80")))
        ),
        daily_coverage_max_stale_minutes=max(
            1, int(os.getenv("DAILY_COVERAGE_MAX_STALE_MINUTES", "50"))
        ),
        daily_coverage_telegram_summary=_env_bool(
            "DAILY_COVERAGE_TELEGRAM_SUMMARY", True
        ),
        job_audit_retention_days=max(
            1, int(os.getenv("JOB_AUDIT_RETENTION_DAYS", "35"))
        ),
        operational_metrics_retention_days=max(
            1, int(os.getenv("OPERATIONAL_METRICS_RETENTION_DAYS", "90"))
        ),
        daily_coverage_retention_days=max(
            1, int(os.getenv("DAILY_COVERAGE_RETENTION_DAYS", "90"))
        ),
        provider_validation_retention_days=max(
            1, int(os.getenv("PROVIDER_VALIDATION_RETENTION_DAYS", "180"))
        ),
        relevance_cache_retention_days=max(
            1, int(os.getenv("RELEVANCE_CACHE_RETENTION_DAYS", "7"))
        ),
        relevance_cache_max_items=max(
            1, int(os.getenv("RELEVANCE_CACHE_MAX_ITEMS", "4000"))
        ),
        browser_session_backup_retention_days=max(
            1, int(os.getenv("BROWSER_SESSION_BACKUP_RETENTION_DAYS", "14"))
        ),
        browser_extension_runtime_retention_days=max(
            1, int(os.getenv("BROWSER_EXTENSION_RUNTIME_RETENTION_DAYS", "30"))
        ),
        seen_file=str(seen_file),
        debug_dir=os.getenv("DEBUG_DIR", "./data/debug"),
        debug_retention_days=int(os.getenv("DEBUG_RETENTION_DAYS", "7")),
        debug_max_files=int(os.getenv("DEBUG_MAX_FILES", "400")),
        proxy_url=os.getenv("PROXY_URL"),
    )
