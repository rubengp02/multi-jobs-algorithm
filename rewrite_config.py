import os
import re

with open('config.py', 'r', encoding='utf-8') as f:
    config_code = f.read()

# We will just write the exact Pydantic equivalent!
# Since I am doing it with care, I will write it as a drop-in replacement that uses @field_validator for complex parsing.
pydantic_code = '''from __future__ import annotations
import os
from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class BotConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    poll_seconds: int = Field(default=900)
    jitter_seconds: int = Field(default=20)
    timeout_seconds: int = Field(default=25)
    telegram_poll_timeout_seconds: int = Field(default=20)
    max_notifs_per_cycle: int = Field(default=0)
    silent_on_start: bool = Field(default=False)
    retry_on_zero_attempts: int = Field(default=1)
    retry_on_zero_delay_sec: int = Field(default=5)
    provider_retry_attempts: int = Field(default=0)
    provider_retry_delay_sec: int = Field(default=5)
    log_level: str = Field(default="INFO")
    
    enabled_providers: list[str] = Field(default=["linkedin","infojobs","tecnoempleo","manfred","remotive","greenhouse_spain","upv_sie","experis","accessiway"])
    include_words: list[str] = Field(default=[])
    exclude_words: list[str] = Field(default=[])
    
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")
    
    linkedin_url: str = Field(default="")
    linkedin_urls: list[str] = Field(default=[])
    linkedin_session_dir: str = Field(default="./data/linkedin_session")
    linkedin_browser_channel: str = Field(default="")
    linkedin_headless: bool = Field(default=True)
    linkedin_auto_login: bool = Field(default=False)
    linkedin_force_login_flow_test: bool = Field(default=False)
    linkedin_email: str = Field(default="")
    linkedin_password: str = Field(default="")
    linkedin_first_page_only: bool = Field(default=True)
    linkedin_max_jobs: int = Field(default=25)
    linkedin_startup_scrolls: int = Field(default=12)
    linkedin_scrolls: int = Field(default=6)
    linkedin_scroll_pause_sec: float = Field(default=1.2)
    linkedin_min_expected: int = Field(default=1)
    linkedin_verbose_logs: bool = Field(default=False)
    linkedin_extension_enabled: bool = Field(default=False)
    linkedin_extension_host: str = Field(default="127.0.0.1")
    linkedin_extension_port: int = Field(default=8765)
    linkedin_extension_refresh_seconds: int = Field(default=900)
    linkedin_time_windows_seconds: tuple[int, ...] = Field(default=(1200, 3600))
    linkedin_inter_search_min_seconds: float = Field(default=3.0)
    linkedin_inter_search_max_seconds: float = Field(default=6.0)

    indeed_url: str = Field(default="")
    indeed_max_results: int = Field(default=60)
    indeed_headless: bool = Field(default=True)
    indeed_session_dir: str = Field(default="./data/indeed_session")
    indeed_min_expected: int = Field(default=1)

    infojobs_url: str = Field(default="")
    infojobs_max_results: int = Field(default=60)
    infojobs_headless: bool = Field(default=True)
    infojobs_auto_accept_cookies: bool = Field(default=True)
    infojobs_session_dir: str = Field(default="./data/infojobs_session")
    infojobs_challenge_wait_sec: int = Field(default=40)
    infojobs_scroll_mode: str = Field(default="mouse")
    infojobs_scroll_steps: int = Field(default=10)
    infojobs_scroll_pause_ms: int = Field(default=700)
    infojobs_pages_to_scan: int = Field(default=3)
    infojobs_min_expected: int = Field(default=1)
    infojobs_verbose_logs: bool = Field(default=False)

    experis_max_results: int = Field(default=60)
    accessiway_max_results: int = Field(default=100)
    consultancy_max_pages: int = Field(default=2)
    consultancy_max_results: int = Field(default=50)
    
    provider_inter_request_min_seconds: float = Field(default=3.0)
    provider_inter_request_max_seconds: float = Field(default=6.0)
    provider_validation_dir: str = Field(default="./data/provider_validation")
    provider_validation_auto_on_anomaly: bool = Field(default=True)
    provider_validation_max_pages: int = Field(default=5)
    provider_validation_max_results: int = Field(default=100)

    daily_coverage_dir: str = Field(default="./data/daily_coverage")
    daily_coverage_lookback_hours: int = Field(default=26)
    daily_coverage_min_cycle_ratio: float = Field(default=0.80)
    daily_coverage_max_stale_minutes: int = Field(default=50)
    daily_coverage_telegram_summary: bool = Field(default=True)
    
    job_audit_retention_days: int = Field(default=35)
    operational_metrics_retention_days: int = Field(default=90)
    daily_coverage_retention_days: int = Field(default=90)
    provider_validation_retention_days: int = Field(default=180)
    relevance_cache_retention_days: int = Field(default=7)
    relevance_cache_max_items: int = Field(default=4000)
    browser_session_backup_retention_days: int = Field(default=14)
    browser_extension_runtime_retention_days: int = Field(default=30)

    seen_file: str = Field(default="./data/seen_jobs.txt")
    debug_dir: str = Field(default="./data/debug")
    debug_retention_days: int = Field(default=7)
    debug_max_files: int = Field(default=400)
    proxy_url: str | None = Field(default=None)

    @field_validator("max_notifs_per_cycle", mode="before")
    def validate_max_notifs(cls, v):
        return max(0, int(v))

    @field_validator("linkedin_max_jobs", mode="before")
    def validate_linkedin_max(cls, v):
        return min(25, max(1, int(v or 25)))

    @field_validator("enabled_providers", "include_words", "exclude_words", mode="before")
    def validate_lists(cls, v):
        if isinstance(v, list): return v
        return [item.strip().lower() for item in str(v).split(",") if item.strip()]
        
    @field_validator("linkedin_urls", mode="before")
    def validate_urls(cls, v):
        if isinstance(v, list): return v
        raw = str(v).strip()
        if not raw: return []
        return [line.strip() for line in raw.replace("|", "\\n").replace(";", "\\n").split("\\n") if line.strip()]

    @field_validator("linkedin_time_windows_seconds", mode="before")
    def validate_time_windows(cls, v):
        if isinstance(v, tuple): return v
        return tuple(int(x.strip()) for x in str(v).split(",") if x.strip().isdigit() and int(x.strip()) > 0)
        
    @field_validator("daily_coverage_min_cycle_ratio", mode="before")
    def validate_ratio(cls, v):
        return min(1.0, max(0.0, float(v)))

    @field_validator("consultancy_max_pages", "consultancy_max_results", "provider_validation_max_pages", "provider_validation_max_results", "daily_coverage_lookback_hours", "daily_coverage_max_stale_minutes", "job_audit_retention_days", "operational_metrics_retention_days", "daily_coverage_retention_days", "provider_validation_retention_days", "relevance_cache_retention_days", "relevance_cache_max_items", "browser_session_backup_retention_days", "browser_extension_runtime_retention_days", mode="before")
    def validate_minimum_1(cls, v):
        return max(1, int(v))

def load_config() -> BotConfig:
    return BotConfig()
'''

with open('config_pydantic.py', 'w', encoding='utf-8') as f:
    f.write(pydantic_code)

print("config_pydantic.py created")
