import logging
import sys

logging.basicConfig(level=logging.DEBUG)
sys.path.append("/home/rubengaona/bots/bot_multi_jobs")

from providers.consultancies import PublicConsultancyProvider, get_consultancy_source


class DummyConfig:
    timeout_seconds = 15
    consultancy_max_results = 5


source = get_consultancy_source("talent_search_people")
p = PublicConsultancyProvider(source, DummyConfig(), logging.getLogger("tsp"))

jobs, next_url = p._parse_page(
    type(
        "Dummy",
        (),
        {
            "text": p.session.get(
                "https://www.talentsearchpeople.com/es/trabajos/"
            ).text,
            "url": "https://www.talentsearchpeople.com/es/trabajos/",
        },
    )
)

print(f"Jobs returned by _parse_page: {len(jobs)}")
for j in jobs:
    print(j.title, j.url)
