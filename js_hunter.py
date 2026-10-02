import re

from bs4 import BeautifulSoup
from curl_cffi import requests

resp = requests.get("https://jobs.eurofirms.com/es/es/", impersonate="chrome")
soup = BeautifulSoup(resp.text, "html.parser")
scripts = [s["src"] for s in soup.find_all("script") if s.get("src")]

for src in scripts:
    if src.startswith("/"):
        url = "https://jobs.eurofirms.com" + src
    else:
        url = src
    try:
        js = requests.get(url, impersonate="chrome").text
        if "FrontOffice" in js or "ef-api" in js or "Offers" in js:
            print(f"Found API in: {url}")
            endpoints = re.findall(r"\"(/[a-zA-Z0-9_/-]+)\"", js)
            for ep in set(endpoints):
                if "Offer" in ep or "offer" in ep or "Search" in ep or "api" in ep:
                    print("  ->", ep)

            # also look for raw fetch calls
            fetches = re.findall(r"fetch\((.*?)\)", js)
            for f in fetches:
                print("  fetch ->", f[:100])
    except:
        pass
