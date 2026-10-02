import re
import urllib.parse

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page()
    page.goto(
        "https://www.accenture.com/es-es/careers/jobsearch?jk=&sb=1",
        wait_until="networkidle",
    )
    html = page.content()
    links = set(re.findall(r'href=["\']([^"\']*jobdetails\?[^"\']+)["\']', html))
    for link in links:
        match = re.search(r"title=([^&]+)", link)
        title = urllib.parse.unquote(match.group(1).replace("+", " ")) if match else "?"
        print(title)
    b.close()
