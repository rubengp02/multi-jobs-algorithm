import re

FILE = "rpi_consultancies.py"
with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

prosolbia_logic = """        if getattr(self.definition, "strategy", "") == "prosolbia_html":
            self.last_fetch_pages = 1
            jobs = []
            try:
                r = self.session.get(self.definition.index_url, timeout=getattr(self.config, "timeout_seconds", 15))
                if r.status_code == 200:
                    soup = BeautifulSoup(r.text, 'html.parser')
                    for div in soup.find_all(class_='elementskit-infobox'):
                        a_tag = div.find('a', href=True)
                        if not a_tag or '.pdf' not in a_tag['href'].lower():
                            continue
                            
                        title_el = div.find('h3')
                        title = title_el.get_text(' ', strip=True) if title_el else ""
                        if not title: continue
                        
                        p_tag = div.find('p')
                        desc = p_tag.get_text(' ', strip=True) if p_tag else ""
                        
                        job_id = a_tag['href'].rstrip('/').split('/')[-1].replace('.pdf', '')
                        
                        job = JobItem(
                            id=job_id,
                            title=title,
                            company=self.definition.company,
                            location="",
                            url=a_tag['href'],
                            source=self.source,
                            description=desc
                        )
                        jobs.append(job)
                else:
                    self.last_blocked_reason = f"{self.source}_http_{r.status_code}"
            except Exception as e:
                self.last_blocked_reason = f"{self.source}_err_{e}"
            self.last_fetch_count = len(jobs)
            return jobs
"""

# insert before infojobs block
target = '        if getattr(self.definition, "strategy", "") == "infojobs":'
content = content.replace(target, prosolbia_logic + "\n" + target)

# modify prosolbia strategy to prosolbia_html
content = re.sub(
    r'ConsultancySource\("prosolbia", "Prosolbia", "https://prosolbia\.com/ofertas/", "Prosolbia", \(r"/wp-content/uploads/.*\\.pdf",\), \("\.elementskit-infobox",\), \(\)\),',
    r'ConsultancySource("prosolbia", "Prosolbia", "https://prosolbia.com/ofertas/", "Prosolbia", (r"/wp-content/uploads/.*\.pdf",), (".elementskit-infobox",), (), strategy="prosolbia_html"),',
    content,
)

with open(FILE, "w", encoding="utf-8") as f:
    f.write(content)
