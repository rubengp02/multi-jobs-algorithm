import logging
import sys

logging.basicConfig(level=logging.DEBUG)
sys.path.append("/home/rubengaona/bots/bot_multi_jobs")
from bs4 import BeautifulSoup

from providers.consultancies import PublicConsultancyProvider, get_consultancy_source


class DummyConfig:
    timeout_seconds = 15
    consultancy_max_results = 5


source = get_consultancy_source("talent_search_people")
p = PublicConsultancyProvider(source, DummyConfig(), logging.getLogger("tsp"))
r = p.session.get("https://www.talentsearchpeople.com/es/trabajos/")
print("Status:", r.status_code)
print("HTML len:", len(r.text))
soup = BeautifulSoup(r.text, "html.parser")
links = soup.select('a[href*="/trabajos/"]')
print("Links found:", len(links))
for c, u in p._find_cards(soup, "https://www.talentsearchpeople.com/es/trabajos/"):
    print("Card matched URL:", u)
