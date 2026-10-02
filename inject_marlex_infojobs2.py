FILE = "/home/rubengaona/bots/bot_multi_jobs/providers/consultancies.py"
with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

target = """        result_limit = max(1, max_results if max_results is not None else getattr(self.config, "consultancy_max_results", 50))

        # These portals render the public listing client-side. Use one bounded"""

replacement = """        result_limit = max(1, max_results if max_results is not None else getattr(self.config, "consultancy_max_results", 50))

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

        # These portals render the public listing client-side. Use one bounded"""

if target in content:
    content = content.replace(target, replacement)
    with open(FILE, "w", encoding="utf-8") as f:
        f.write(content)
    print("Injection successful")
else:
    print("Target not found")
