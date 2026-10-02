import re

from bs4 import BeautifulSoup
from curl_cffi import requests

targets = {
    "Montaner": "https://montaner.com/candidatos/",
    "Prosolbia": "https://prosolbia.com/ofertas/",
    "Nortempo": "https://empleo.nortempo.com/search_offers/0/",
    "Melt Group": "https://meltgroup.com/ofertas-de-empleo/",
    "Grupo Noas": "https://www.gruponoas.es/ofertas-de-trabajo/",
}

for name, url in targets.items():
    print(f"--- Investigating {name} ---")
    try:
        resp = requests.get(url, impersonate="chrome", timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        # Check generator meta tags
        meta = soup.find("meta", {"name": "generator"})
        if meta:
            print(f"Generator: {meta.get('content')}")

        # Check for iframe (embedded ATS)
        iframes = soup.find_all("iframe")
        for iframe in iframes:
            src = iframe.get("src")
            if src and ("job" in src or "career" in src or "offer" in src):
                print(f"Found ATS Iframe: {src}")

        # Search for obvious API/ATS markers in scripts
        scripts = soup.find_all("script")
        for s in scripts:
            if s.string:
                if (
                    "Teamtailor" in s.string
                    or "jobs.json" in s.string
                    or "api" in s.string.lower()
                ):
                    # print first 100 chars to avoid noise
                    matches = re.findall(
                        r"(https?://[^\s\"\']+api[^\s\"\']+)", s.string
                    )
                    if matches:
                        print(f"Found potential API URLs in script: {set(matches)}")
            if s.get("src"):
                if (
                    "teamtailor" in s.get("src").lower()
                    or "epreselec" in s.get("src").lower()
                ):
                    print(f"Found ATS script src: {s.get('src')}")

        # Check for XHR / API endpoints in the HTML
        html = resp.text
        if "wp-json" in html:
            print("Detected WordPress REST API (/wp-json/)")
        if "admin-ajax.php" in html:
            print("Detected WordPress AJAX (admin-ajax.php)")

    except Exception as e:
        print(f"Error: {e}")
    print()
