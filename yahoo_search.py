import time
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup


def get_yahoo_result(query):
    try:
        url = "https://es.search.yahoo.com/search?p=" + urllib.parse.quote(query)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode("utf-8")
            soup = BeautifulSoup(html, "html.parser")
            title_tag = soup.select_one("div.compTitle h3.title a")
            if title_tag:
                link = title_tag.get("href", "")
                title = title_tag.text.strip()
                return title, link
    except Exception:
        pass
    return "Not found", None


targets = [
    "site:es.linkedin.com/in CTO Zeleros Valencia",
    'site:es.linkedin.com/in CTO "Sesame HR" Valencia',
    "site:es.linkedin.com/in CTO Quibim Valencia",
    "site:es.linkedin.com/in CTO Voicemod Valencia",
    'site:es.linkedin.com/in "Director de Operaciones" "Vicky Foods" Gandia',
    "site:es.linkedin.com/in CIO Balearia Denia",
]

for t in targets:
    title, link = get_yahoo_result(t)
    print(f"RES: {title}")
    time.sleep(1)
