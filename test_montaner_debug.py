import sys

sys.path.append("/home/rubengaona/bots/bot_multi_jobs")
import logging

from bs4 import BeautifulSoup

from config import load_config
from providers.consultancies import build_consultancy_provider

config = load_config()
logger = logging.getLogger()
extractor = build_consultancy_provider("montaner", config, logger)

original_parse = extractor._parse_page


def debug_parse(response):
    soup = BeautifulSoup(response.text, "html.parser")
    for a in soup.find_all("a", href=True):
        if "/jobs/" in a["href"]:
            print("Found job href:", a["href"])
    for sel in extractor.definition.card_selectors:
        print(f"Selector {sel}: found {len(soup.select(sel))} matches")
    return original_parse(response)


extractor._parse_page = debug_parse

extractor.fetch_jobs(max_pages=1, max_results=20)
