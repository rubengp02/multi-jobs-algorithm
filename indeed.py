from __future__ import annotations

import logging
import sys
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests
from playwright.sync_api import Playwright

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
        if playwright is not None:
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

            # Use Stealth mode instead of persistent context to bypass Cloudflare
            from utils_stealth import apply_playwright_stealth

            self.browser = playwright.chromium.launch(
                headless=self.config.indeed_headless,
                ignore_default_args=ignored_default_args,
                args=launch_args,
            )
            self.context, self.page = apply_playwright_stealth(self.browser)

    def _count_result_nodes(self) -> int:
        if self.page is None:
            return 0
        try:
            return int(
                self.page.evaluate(
                    """() => {
                        const cards = document.querySelectorAll("div.job_seen_beacon, div.slider_item").length;
                        const links = document.querySelectorAll("a[href*='/viewjob'], a[href*='/rc/clk'], a[href*='jk=']").length;
                        return Math.max(cards, links);
                    }"""
                )
            )
        except Exception:
            return 0

    def _wait_stable_results(
        self, max_wait_ms: int = 8000, step_ms: int = 600, stable_rounds: int = 3
    ) -> int:
        if self.page is None:
            return 0
        elapsed = 0
        last = -1
        stable = 0
        best = 0
        while elapsed < max_wait_ms:
            current = self._count_result_nodes()
            best = max(best, current)
            if current == last:
                stable += 1
            else:
                stable = 0
            if stable >= stable_rounds:
                break
            self.page.wait_for_timeout(step_ms)
            elapsed += step_ms
            last = current
        return best

    def _adaptive_scroll_results(
        self, max_steps: int = 12, stagnation_limit: int = 3
    ) -> None:
        if self.page is None:
            return
        best = self._count_result_nodes()
        stagnation = 0
        for _ in range(max_steps):
            self.page.mouse.wheel(0, 900)
            self.page.wait_for_timeout(350)
            current = self._count_result_nodes()
            if current > best:
                best = current
                stagnation = 0
            else:
                stagnation += 1
            if stagnation >= stagnation_limit:
                break

    def _extract_id(self, url: str) -> str:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if qs.get("jk"):
            return qs["jk"][0]
        path = parsed.path.rstrip("/")
        return path.split("/")[-1] if path else ""

    @staticmethod
    def _soup_text(root, selectors: list[str]) -> str:
        for sel in selectors:
            node = root.select_one(sel)
            if not node:
                continue
            txt = " ".join(node.get_text(" ", strip=True).split())
            if txt:
                return txt
        return ""

    @staticmethod
    def _is_missing_value(value: str, fallback: str) -> bool:
        return (value or "").strip() in {"", fallback}

    @staticmethod
    def _extract_detail_fields_from_soup(soup: BeautifulSoup) -> tuple[str, str, str]:
        def pick(selectors: list[str]) -> str:
            for sel in selectors:
                node = soup.select_one(sel)
                if not node:
                    continue
                txt = " ".join(node.get_text(" ", strip=True).split())
                if txt:
                    return txt
            return ""

        title = pick(
            [
                "h1[data-testid='jobsearch-JobInfoHeader-title'] span",
                "h1[data-testid='jobsearch-JobInfoHeader-title']",
                "h1.jobsearch-JobInfoHeader-title",
                "h1",
            ]
        )
        company = pick(
            [
                "h2.jobsearch-CompanyReview--heading",
                "[data-testid='inlineHeader-companyName']",
                "div[data-company-name='true']",
                "a[data-testid='inlineHeader-companyName']",
            ]
        )
        location = pick(
            [
                "[data-testid='jobsearch-JobInfoHeader-subtitle'] div",
                "[data-testid='inlineHeader-companyLocation']",
                "div[data-testid='job-location']",
                "div.jobsearch-JobInfoHeader-subtitle div",
            ]
        )
        return title, company, location

    def _enrich_missing_fields_from_detail(
        self, jobs: list[JobItem], max_checks: int = 12
    ) -> list[JobItem]:
        if not jobs:
            return jobs

        pending = [
            job
            for job in jobs
            if self._is_missing_value(job.title, "Oferta")
            or self._is_missing_value(job.company, "Empresa no indicada")
            or self._is_missing_value(job.location, "Ubicacion no indicada")
        ]
        if not pending:
            return jobs

        checked = 0
        improved = 0
        for job in pending:
            if checked >= max_checks:
                break
            checked += 1

            detail_title, detail_company, detail_location = self._detail_cache.get(
                job.url, ("", "", "")
            )
            if not any([detail_title, detail_company, detail_location]):
                html = ""
                try:
                    resp = requests.get(
                        job.url,
                        headers=self.headers,
                        timeout=min(15, self.config.timeout_seconds),
                        allow_redirects=True,
                    )
                    if resp.ok:
                        html = resp.text
                except Exception:
                    html = ""

                if not html and self.page is not None:
                    try:
                        self.page.goto(
                            job.url, wait_until="domcontentloaded", timeout=45_000
                        )
                        self.page.wait_for_timeout(1000)
                        html = self.page.content()
                    except Exception:
                        html = ""

                if html:
                    soup = BeautifulSoup(html, "html.parser")
                    detail_title, detail_company, detail_location = (
                        self._extract_detail_fields_from_soup(soup)
                    )
                self._detail_cache[job.url] = (
                    detail_title,
                    detail_company,
                    detail_location,
                )

            before = (job.title, job.company, job.location)
            if self._is_missing_value(job.title, "Oferta") and detail_title:
                job.title = detail_title
            if (
                self._is_missing_value(job.company, "Empresa no indicada")
                and detail_company
            ):
                job.company = detail_company
            if (
                self._is_missing_value(job.location, "Ubicacion no indicada")
                and detail_location
            ):
                job.location = detail_location
            after = (job.title, job.company, job.location)
            if after != before:
                improved += 1

        if checked:
            self.logger.info(
                "Indeed detail enrich | checked=%s improved=%s pending_initial=%s",
                checked,
                improved,
                len(pending),
            )
        return jobs

    def _from_requests(self) -> list[JobItem]:
        jobs: dict[str, JobItem] = {}
        base_url = self.config.indeed_url
        sep = "&" if "?" in base_url else "?"
        if "sort=" not in base_url:
            base_url = f"{base_url}{sep}sort=date"
            sep = "&"

        for page in range(3):
            target_url = f"{base_url}{sep}start={page * 10}"
            try:
                import random
                import time

                time.sleep(random.uniform(1.2, 3.5))
                response = requests.get(
                    target_url,
                    headers=self.headers,
                    timeout=self.config.timeout_seconds,
                    impersonate="chrome",
                )
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")

                cards = soup.select(
                    "div.job_seen_beacon, div.slider_item, li div.job_seen_beacon, article, li.result"
                )
                if not cards:
                    break

                for card in cards:
                    a = card.select_one(
                        "a[href*='/viewjob'], a[href*='/rc/clk'], a[href*='jk=']"
                    )
                    if not a:
                        continue
                    href = (a.get("href") or "").strip()
                    if not href:
                        continue
                    full_url = urljoin("https://es.indeed.com", href)
                    job_id = self._extract_id(full_url)
                    if not job_id:
                        continue

                    title = self._soup_text(
                        card, ["h2.jobTitle", "[data-testid='job-title']", "h2", "a h2"]
                    )
                    if not title:
                        title = (
                            " ".join(a.get_text(" ", strip=True).split()) or "Oferta"
                        )
                    company = self._soup_text(
                        card,
                        [
                            "[data-testid='company-name']",
                            "span.companyName",
                            ".companyName",
                            "[class*='company']",
                        ],
                    )
                    location = self._soup_text(
                        card,
                        [
                            "[data-testid='text-location']",
                            "div.companyLocation",
                            ".companyLocation",
                            "[class*='location']",
                        ],
                    )

                    jobs[job_id] = JobItem(
                        id=job_id,
                        title=title,
                        company=company,
                        location=location,
                        url=f"https://es.indeed.com/viewjob?jk={job_id}",
                        source=self.source,
                    )
                    if len(jobs) >= self.config.indeed_max_results:
                        break

            except Exception as exc:
                self.logger.warning(f"Error paginando Indeed {target_url}: {exc}")
                break

        return list(jobs.values())

    def _from_playwright(self) -> list[JobItem]:
        if self.page is None:
            return []

        def collect_from_dom() -> list[JobItem]:
            raw = self.page.evaluate(
                """() => {
                const clean = (v) => (v || "").replace(/\\s+/g, " ").trim();
                const pickText = (root, selectors) => {
                    if (!root) return "";
                    for (const sel of selectors) {
                        const n = root.querySelector(sel);
                        if (!n) continue;
                        const t = clean(n.innerText || n.textContent || "");
                        if (t) return t;
                    }
                    return "";
                };
                const cards = Array.from(document.querySelectorAll(
                  "div.job_seen_beacon, div.slider_item, article, li"
                ));
                const out = [];
                for (const card of cards) {
                  const link = card.querySelector("a[href*='/viewjob'], a[href*='/rc/clk'], a[href*='jk=']");
                  if (!link) continue;
                  const href = link.getAttribute("href") || "";
                  if (!href) continue;
                  const title =
                    pickText(card, ["h2.jobTitle", "[data-testid='job-title']", "h2"]) ||
                    clean(link.innerText || link.textContent || "");
                  const company = pickText(card, [
                    "[data-testid='company-name']",
                    ".companyName",
                    "[class*='company']",
                  ]);
                  const location = pickText(card, [
                    "[data-testid='text-location']",
                    ".companyLocation",
                    "[class*='location']",
                  ]);
                  out.push({ href, title, company, location });
                }
                return out;
            }""",
            )
            jobs: dict[str, JobItem] = {}
            for item in raw:
                href = (item.get("href") or "").strip()
                if not href:
                    continue
                full_url = urljoin("https://es.indeed.com", href)
                job_id = self._extract_id(full_url)
                if not job_id:
                    continue
                jobs[job_id] = JobItem(
                    id=job_id,
                    title=((item.get("title") or "").strip() or "Oferta"),
                    company=(
                        (item.get("company") or "").strip() or "Empresa no indicada"
                    ),
                    location=(
                        (item.get("location") or "").strip() or "Ubicacion no indicada"
                    ),
                    url=f"https://es.indeed.com/viewjob?jk={job_id}",
                    source=self.source,
                )
                if len(jobs) >= self.config.indeed_max_results:
                    break
            return list(jobs.values())

        attempt_urls = [self.config.indeed_url]
        if "sort=" not in self.config.indeed_url:
            sep = "&" if "?" in self.config.indeed_url else "?"
            attempt_urls.append(f"{self.config.indeed_url}{sep}sort=date")

        best: list[JobItem] = []
        for attempt, url in enumerate(attempt_urls, start=1):
            self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            try:
                self.page.wait_for_selector(
                    "a[href*='/viewjob'], a[href*='/rc/clk'], a[href*='jk=']",
                    timeout=15_000,
                )
            except Exception:
                pass
            self.page.wait_for_timeout(2000)
            self._wait_stable_results()
            self._adaptive_scroll_results()
            self._wait_stable_results(max_wait_ms=5000)

            current = collect_from_dom()
            if len(current) > len(best):
                best = current
            if len(best) >= max(10, self.config.indeed_max_results // 2):
                break
            self.logger.warning(
                "Indeed playwright attempt %s/%s low-yield (%s jobs).",
                attempt,
                len(attempt_urls),
                len(current),
            )

        if not best:
            html = self.page.content()
            recovered: dict[str, JobItem] = {}
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.select(
                "a[href*='jk='], a[href*='/viewjob'], a[href*='/rc/clk']"
            ):
                href = (a.get("href") or "").strip()
                if not href:
                    continue
                full_url = urljoin("https://es.indeed.com", href)
                job_id = self._extract_id(full_url)
                if not job_id:
                    continue
                recovered[job_id] = JobItem(
                    id=job_id,
                    title=(a.get_text(" ", strip=True) or "Oferta"),
                    company="Empresa no indicada",
                    location="Ubicacion no indicada",
                    url=f"https://es.indeed.com/viewjob?jk={job_id}",
                    source=self.source,
                )
                if len(recovered) >= self.config.indeed_max_results:
                    break
            best = list(recovered.values())
        return best

    def fetch_jobs(self) -> list[JobItem]:
        self.last_blocked_reason = ""
        if not self.config.indeed_url:
            self.logger.warning("Indeed URL is empty. Skipping provider.")
            return []
        try:
            jobs = self._from_requests()
            if jobs:
                return self._enrich_missing_fields_from_detail(jobs)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            self.logger.warning(
                "Indeed requests blocked with HTTP %s. Trying playwright fallback.",
                status,
            )
            if str(status) == "403":
                self.last_blocked_reason = "requests_403"
        except Exception as exc:
            self.logger.warning(
                "Indeed requests failed (%s). Trying playwright fallback.", exc
            )

        jobs_pw = self._from_playwright()
        if not jobs_pw:
            self.logger.warning("Indeed playwright fallback returned 0 jobs.")
            if not self.last_blocked_reason:
                self.last_blocked_reason = "playwright_zero_jobs"
        return self._enrich_missing_fields_from_detail(jobs_pw)
