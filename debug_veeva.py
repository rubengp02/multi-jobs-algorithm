import json

import requests
from bs4 import BeautifulSoup

url = "https://www.linkedin.com/jobs/view/4402377519"
r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
soup = BeautifulSoup(r.text, "html.parser")
for s in soup.select('script[type="application/ld+json"]'):
    try:
        print(json.loads(s.string).get("jobLocation", ""))
    except:
        pass
