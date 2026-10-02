import json
import re
import time

from curl_cffi import requests

for _ in range(5):
    r = requests.get(
        "https://www.infojobs.net/jobsearch/search-results/list.xhtml?keyword=python",
        impersonate="chrome",
    )
    print("Status code:", r.status_code)

    pattern = re.compile(
        r'window\.__INITIAL_PROPS__\s*=\s*JSON\.parse\(\s*("(?:\\.|[^"\\])*")\s*\)\s*;?',
        re.DOTALL,
    )
    m = pattern.search(r.text)
    if m:
        encoded_payload = json.loads(m.group(1))
        payload = json.loads(encoded_payload)
        print("Keys in payload:", list(payload.keys()))

        def find_offers(d, path=""):
            if isinstance(d, dict):
                for k, v in d.items():
                    if k in ("offers", "items", "results", "jobOffers"):
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
        break
    else:
        print("Match failed. Retrying...")
        time.sleep(2)
