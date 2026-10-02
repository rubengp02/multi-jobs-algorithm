filepath = (
    r"c:\Users\Ruben\Desktop\Python\bot_linkedin\bot_multi_jobs\consultancies_clean.py"
)
with open(filepath, "r", encoding="utf-8") as f:
    text = f.read()

injection = """        if getattr(self.definition, "strategy", "") == "ananda_api":
            self.last_fetch_pages = 1
            try:
                r = self.session.get("https://www.ananda.es/controller/dt2.php", timeout=getattr(self.config, "timeout_seconds", 15))
                if r.status_code == 200:
                    data = r.json()
                    jobs = []
                    for item in data.get("data", [])[:result_limit]:
                        link_html = item[0]
                        import re
                        m = re.search(r'href=["\']([^"\']+)["\']', link_html)
                        url = m.group(1) if m else ""
                        job_id = url.split("/")[-2] if "/" in url else url
                        title = item[1] if len(item) > 1 else "Oferta"
                        location = item[3] if len(item) > 3 else "España"
                        
                        jobs.append(JobItem(
                            id=str(job_id),
                            title=title.strip(),
                            company=self.definition.company,
                            location=location.strip(),
                            url=url,
                            source=self.source,
                            description=""
                        ))
                    self.last_fetch_count = len(jobs)
                    return jobs
            except Exception as e:
                self.logger.error("Ananda API error: %s", e)
            return []

        elif getattr(self.definition, "strategy", "") == "nortempo_api":
            self.last_fetch_pages = 1
            try:
                r = self.session.get("https://empleo.nortempo.com/candidatos/api/oferta/buscar", timeout=getattr(self.config, "timeout_seconds", 15))
                if r.status_code == 200:
                    data = r.json()
                    jobs = []
                    for item in data.get("ofertas", [])[:result_limit]:
                        job_id = str(item.get("id"))
                        title = item.get("puesto", "Oferta")
                        location = item.get("provincia", "España")
                        url = f"https://empleo.nortempo.com/candidatos/oferta/{job_id}"
                        jobs.append(JobItem(
                            id=job_id,
                            title=title.strip(),
                            company=self.definition.company,
                            location=location.strip(),
                            url=url,
                            source=self.source,
                            description=""
                        ))
                    self.last_fetch_count = len(jobs)
                    return jobs
            except Exception as e:
                self.logger.error("Nortempo API error: %s", e)
            return []

        elif getattr(self.definition, "strategy", "") == "randstad_html":
            self.last_fetch_pages = 1
            try:
                r = self.session.get("https://www.randstad.es/candidatos/ofertas-empleo/", timeout=getattr(self.config, "timeout_seconds", 15))
                if r.status_code == 200:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(r.text, "html.parser")
                    jobs = []
                    for a in soup.find_all("a", attrs={"data-offerid": True})[:result_limit]:
                        job_id = a.get("data-offerid")
                        title = a.get("data-title", "Oferta")
                        location = a.get("data-province", "España")
                        url = a.get("href", "")
                        jobs.append(JobItem(
                            id=job_id,
                            title=title.strip(),
                            company=self.definition.company,
                            location=location.strip(),
                            url=url,
                            source=self.source,
                            description=""
                        ))
                    self.last_fetch_count = len(jobs)
                    return jobs
            except Exception as e:
                self.logger.error("Randstad HTML error: %s", e)
            return []

        elif getattr(self.definition, "strategy", "") == "hays_html":
            self.last_fetch_pages = 1
            try:
                r = self.session.get("https://www.hays.es/busqueda-empleo", timeout=getattr(self.config, "timeout_seconds", 15))
                if r.status_code == 200:
                    import re
                    html = r.text
                    titles = re.findall(r'\\&q;title\\&q;:\\&q;(.*?)\\&q;', html)
                    urls = re.findall(r'\\&q;trackingUrl\\&q;:\\&q;(.*?)\\&q;', html)
                    locs = re.findall(r'\\&q;location\\&q;:\\&q;(.*?)\\&q;', html)
                    jobs = []
                    limit = min(len(titles), len(urls), len(locs), result_limit)
                    for i in range(limit):
                        job_id = urls[i].split("_")[-1] if "_" in urls[i] else urls[i]
                        jobs.append(JobItem(
                            id=job_id,
                            title=titles[i].strip(),
                            company=self.definition.company,
                            location=locs[i].strip(),
                            url=urls[i],
                            source=self.source,
                            description=""
                        ))
                    self.last_fetch_count = len(jobs)
                    return jobs
            except Exception as e:
                self.logger.error("Hays HTML error: %s", e)
            return []

        elif getattr(self.definition, "strategy", "") == "manpower_api":
            self.last_fetch_pages = 1
            try:
                r = self.session.post(
                    "https://www.manpower.es/api/services/Jobs/searchjobs",
                    json={"filter":{"offset":0,"totalCount":0,"limit":result_limit,"searchkeyword":None,"haslocation":False,"language":"es"}},
                    timeout=getattr(self.config, "timeout_seconds", 15)
                )
                if r.status_code == 200:
                    data = r.json()
                    jobs = []
                    for item in data.get("jobsItems", [])[:result_limit]:
                        job_id = str(item.get("jobID"))
                        title_str = item.get("jobTitle", "Oferta")
                        location = item.get("jobLocation") or "Ubicacion no indicada"
                        jobs.append(JobItem(
                            id=job_id,
                            title=title_str.strip(),
                            company=self.definition.company,
                            location=location.strip(),
                            url=f"https://www.manpower.es/es/job-details/{job_id}",
                            source=self.source,
                            description=""
                        ))
                    self.last_fetch_count = len(jobs)
                    return jobs
            except Exception as e:
                self.logger.error("Manpower API error: %s", e)
            return []
"""

start_idx = text.find('if getattr(self.definition, "strategy", "") == "manpower_api":')
end_idx = text.find(
    "def _fetch_playwright(self, result_limit: int, page_limit: int) -> list[JobItem]:"
)

if start_idx != -1 and end_idx != -1:
    # Need to keep the indenting right. end_idx points to 'def _fetch_playwright'
    # we just need to replace the content between them, minus any whitespace

    end_whitespace = text.rfind("\n", 0, end_idx) + 1

    # Actually, we know the exact text to replace.
    text = text[:start_idx] + injection.strip() + "\n\n    " + text[end_idx:]
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(text)
    print("Successfully patched consultancies_clean.py locally")
else:
    print(f"Could not find indices: start={start_idx}, end={end_idx}")
