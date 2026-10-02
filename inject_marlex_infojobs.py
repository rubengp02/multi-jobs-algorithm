import re

FILE = "/home/rubengaona/bots/bot_multi_jobs/providers/consultancies.py"
with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

fetch_jobs_mod = """    def fetch_jobs(self, *, max_pages: int | None = None, max_results: int | None = None) -> list[JobItem]:
        self.last_blocked_reason = ""
        self.rate_limit_429_cycle = 0
        self.last_fetch_pages = 0
        self.last_fetch_count = 0
        self.last_ordering = "portal_order_unverified"
        page_limit = max(1, max_pages if max_pages is not None else getattr(self.config, "consultancy_max_pages", 2))
        result_limit = max(1, max_results if max_results is not None else getattr(self.config, "consultancy_max_results", 50))

        if getattr(self.definition, "strategy", "") == "infojobs":
            class DummyConfig:
                infojobs_url = self.definition.index_url
                infojobs_max_results = result_limit
                timeout_seconds = getattr(self.config, "timeout_seconds", 15)
            
            from providers.infojobs import InfoJobsProvider
            ij = InfoJobsProvider(DummyConfig(), self.logger, self.playwright)
            ij.EXCLUDE_ROLE_STEMS = getattr(self.config, 'infojobs_exclude_roles', [])
            ij.session = self.session
            jobs = ij.fetch_jobs(startup_deep_scan=False)
            self.last_fetch_count = len(jobs)
            self.last_fetch_pages = 1
            return jobs
"""

content = re.sub(
    r'    def fetch_jobs\(self, \*, max_pages: int \| None = None, max_results: int \| None = None\) -> list\[JobItem\]:.*?result_limit = max\(1, max_results if max_results is not None else getattr\(self\.config, "consultancy_max_results", 50\)\)',
    fetch_jobs_mod,
    content,
    flags=re.DOTALL,
)

with open(FILE, "w", encoding="utf-8") as f:
    f.write(content)
