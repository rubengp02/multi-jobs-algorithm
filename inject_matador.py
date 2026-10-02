FILE = "rpi_consultancies.py"
with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

matador_logic = """        if getattr(self.definition, "strategy", "") == "matador_json":
            self.last_fetch_pages = 1
            try:
                # We need to construct the API URL correctly. The definition.index_url might be the HTML page.
                api_url = "https://meltgroup.com/wp-json/wp/v2/matador-job-listings"
                r = self.session.get(f"{api_url}?per_page={result_limit}", timeout=getattr(self.config, "timeout_seconds", 15))
                if r.status_code == 200:
                    data = r.json()
                    jobs = []
                    for item in data:
                        job_id = str(item.get("id"))
                        title_str = item.get("title", {}).get("rendered", "")
                        link = item.get("link", "")
                        desc = item.get("content", {}).get("rendered", "")
                        
                        # Matador usually returns plain JSON, no location by default unless we parse meta
                        
                        if not title_str or not link: continue
                        
                        job = JobItem(
                            id=job_id,
                            title=title_str,
                            company=self.definition.company_name,
                            location="",
                            url=link,
                            source=self.source,
                            description=desc
                        )
                        jobs.append(job)
                    self.last_fetch_count = len(jobs)
                    return jobs
                else:
                    self.last_blocked_reason = f"{self.source}_http_{r.status_code}"
                    return []
            except Exception as e:
                self.last_blocked_reason = f"{self.source}_err_{e}"
                return []
"""

# insert before infojobs block
target = '        if getattr(self.definition, "strategy", "") == "infojobs":'
content = content.replace(target, matador_logic + "\n" + target)

# modify melt_group strategy
content = content.replace(
    'ConsultancySource("melt_group", "Melt Group", "https://meltgroup.com/ofertas-de-empleo/", "Melt Group", (r"/ofertas?-de-empleo/[^?#]+", r"/oferta/[^?#]+"), ("a[href*=\'oferta\']",), (".location", ".localidad"), strategy="public_dynamic"),',
    'ConsultancySource("melt_group", "Melt Group", "https://meltgroup.com/ofertas-de-empleo/", "Melt Group", (r"/ofertas?-de-empleo/[^?#]+", r"/oferta/[^?#]+"), ("a[href*=\'oferta\']",), (".location", ".localidad"), strategy="matador_json"),',
)

with open(FILE, "w", encoding="utf-8") as f:
    f.write(content)
