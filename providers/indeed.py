from __future__ import annotations
import asyncio

import logging
import sys
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import Playwright

from config import BotConfig
from models import JobItem


class IndeedProvider:
    source = "indeed"

    def __init__(
        self,
        config: BotConfig,
        logger: logging.Logger,
        playwright: Playwright | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        self.playwright = playwright
        self.last_blocked_reason = ""
        self._detail_cache: dict[str, tuple[str, str, str]] = {}
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        }
        self.page = None

    async def _ensure_browser(self):
        if self.playwright is not None and self.page is None:
            launch_args: list[str] = []
            if sys.platform.startswith("linux"):
                launch_args.extend(
                    [
                        "--no-sandbox",
                        "--password-store=basic",
                        "--disable-gpu",
                        "--use-gl=swiftshader",
                        "--disable-dev-shm-usage",
                    ]
                )
            session_dir = Path(self.config.indeed_session_dir)
            if not session_dir.is_absolute():
                session_dir = (
                    Path(__file__).resolve().parents[1] / session_dir
                ).resolve()
            session_dir.mkdir(parents=True, exist_ok=True)
            ignored_default_args = ["--enable-automation"]
            if not sys.platform.startswith("linux"):
                ignored_default_args.append("--no-sandbox")
            context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(session_dir),
                headless=self.config.indeed_headless,
                ignore_default_args=ignored_default_args,
                user_agent=self.headers["User-Agent"],
                proxy={"server": self.config.proxy_url}
                if self.config.proxy_url
                else None,
                locale="es-ES",
                args=launch_args,
            )
            self.context = context
            await self.context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            await self.context.add_init_script("window.chrome = { runtime: {} };")
            self.page = context.pages[0] if context.pages else await context.new_page()


