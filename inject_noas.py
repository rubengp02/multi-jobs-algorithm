import re

FILE = "rpi_consultancies.py"
with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

noas_logic = """        if getattr(self.definition, "strategy", "") == "noas_html":
            self.last_fetch_pages = 0
            jobs = []
            
            for page_num in range(1, page_limit + 1):
                url = self.definition.index_url if page_num == 1 else f"{self.definition.index_url}page/{page_num}/"
                try:
                    r = self.session.get(url, timeout=getattr(self.config, "timeout_seconds", 15))
                    if r.status_code != 200:
                        self.last_blocked_reason = f"{self.source}_http_{r.status_code}"
                        break
                        
                    body_l = r.text[:100_000].lower()
                    if any(marker in body_l for marker in CHALLENGE_MARKERS) and not "captcha" in body_l:
                        self.last_blocked_reason = f"{self.source}_challenge"
                        break
                        
                    soup = BeautifulSoup(r.text, 'html.parser')
                    a_tags = [a for a in soup.find_all('a', href=True) if '/oferta/' in a['href']]
                    if not a_tags:
                        break
                        
                    self.last_fetch_pages += 1
                    
                    for a in a_tags:
                        href = a['href']
                        job_id = href.rstrip('/').split('/')[-1]
                        
                        title_el = a.find(class_='titulo')
                        title = title_el.get_text(' ', strip=True) if title_el else ""
                        if not title: continue
                        
                        loc_el = a.find(class_='localidad')
                        loc = loc_el.get_text(' ', strip=True) if loc_el else ""
                        
                        desc_el = a.find(class_='resumen')
                        desc = desc_el.get_text(' ', strip=True) if desc_el else ""
                        
                        full_url = urllib.parse.urljoin(url, href)
                        
                        job = JobItem(
                            id=job_id,
                            title=title,
                            company=self.definition.company,
                            location=loc,
                            url=full_url,
                            source=self.source,
                            description=desc
                        )
                        jobs.append(job)
                        
                        if len(jobs) >= result_limit:
                            break
                    if len(jobs) >= result_limit:
                        break
                except Exception as e:
                    self.last_blocked_reason = f"{self.source}_err_{e}"
                    break
                    
            self.last_fetch_count = len(jobs)
            return jobs
"""

# insert before infojobs block
target = '        if getattr(self.definition, "strategy", "") == "infojobs":'
content = content.replace(target, noas_logic + "\n" + target)

# modify grupo_noas strategy back to noas_html
content = re.sub(
    r'ConsultancySource\("grupo_noas", "Grupo Noa\'s", "https://www\.gruponoas\.es/ofertas-de-trabajo/", "Grupo Noa\'s", \(r"/oferta/\[\^\?#\]\+",\), \("a\[href\*\=\'/oferta/\'\]",\), \("\.location", "\.localidad"\)\),',
    'ConsultancySource("grupo_noas", "Grupo Noa\'s", "https://www.gruponoas.es/ofertas-de-trabajo/", "Grupo Noa\'s", (r"/oferta/[^?#]+",), ("a[href*=\'/oferta/\']",), (".location", ".localidad"), strategy="noas_html"),',
    content,
)

with open(FILE, "w", encoding="utf-8") as f:
    f.write(content)
