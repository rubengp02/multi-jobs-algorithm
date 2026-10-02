import json
import re

from bs4 import BeautifulSoup
from curl_cffi import requests

r = requests.get(
    "https://www.infojobs.net/jobsearch/search-results/list.xhtml?keyword=python",
    impersonate="chrome",
)
print("Status:", r.status_code)
soup = BeautifulSoup(r.text, "html.parser")
print("Title:", soup.title.string if soup.title else "No title")

text = ""
for s in soup.find_all("script"):
    if s.string and "__INITIAL_PROPS__" in s.string:
        text = s.string
        break

if not text:
    print("Could not find __INITIAL_PROPS__ in any script tag!")
else:
    pattern = re.compile(
        r'window\.__INITIAL_PROPS__\s*=\s*JSON\.parse\(\s*("(?:\\.|[^"\\])*")\s*\)\s*;?',
        re.DOTALL,
    )
    m = pattern.search(text)
    if m:
        encoded_payload = json.loads(m.group(1))
        payload = json.loads(encoded_payload)
        print("Keys in payload:", list(payload.keys()))

        def find_offers(d, path=""):
            if isinstance(d, dict):
                for k, v in d.items():
                    if k in ("offers", "items", "results", "jobOffers", "list"):
                        print(f"Found '{k}' at path: {path}.{k}")
                        if isinstance(v, list) and len(v) > 0:
                            print(
                                "  Sample item keys:",
                                list(v[0].keys())
                                if isinstance(v[0], dict)
                                else "Not dict",
                            )
                    find_offers(v, path + "." + str(k))
            elif isinstance(d, list):
                for i, item in enumerate(d):
                    find_offers(item, path + f"[{i}]")

        find_offers(payload)
    else:
        print("Match failed!")
