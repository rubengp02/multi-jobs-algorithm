from bs4 import BeautifulSoup
from curl_cffi import requests

resp = requests.get(
    "https://jobs.eurofirms.com/es/es/", impersonate="chrome", timeout=10
)
soup = BeautifulSoup(resp.text, "html.parser")

scripts = soup.find_all("script")
found_json = False
for s in scripts:
    if s.string and (
        "window.__INITIAL_STATE__" in s.string
        or "__NEXT_DATA__" in s.string
        or "ofertas" in s.string.lower()
        or "jobs" in s.string.lower()
    ):
        print(f"Found potential state JSON: {s.string[:500]}...")
        found_json = True
if not found_json:
    print("No state JSON found.")
    print("Snippet of HTML:")
    print(resp.text[:1000])
