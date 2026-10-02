import sys

sys.path.append("/home/rubengaona/bots/bot_multi_jobs")
import logging

from config import BotConfig
from providers.infojobs import InfoJobsProvider

logging.basicConfig(level=logging.INFO)

config = BotConfig(
    telegram_token="fake",
    telegram_chat_id="fake",
    infojobs_url="https://www.infojobs.net/jobsearch/search-results/list.xhtml?keyword=python&provinceIds=46",
    infojobs_max_results=5,
    anthropic_api_key="fake",
)
provider = InfoJobsProvider(config)
jobs = provider.fetch_jobs()
print(f"Found {len(jobs)} jobs")
for j in jobs:
    print(j.title, j.company, j.location)
