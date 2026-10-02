import re

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(
        "https://www.accenture.com/es-es/careers/jobsearch?jk=&sb=1",
        wait_until="networkidle",
    )
    html = page.content()

    # Try multiple regexes
    print("Pattern 1 (/es-es/careers/jobdetails[^'\"]+):")
    links1 = re.findall(r'href=["\'](/es-es/careers/jobdetails[^"\']+)["\']', html)
    print(len(links1), links1[:3])

    print("Pattern 2 (jobdetails):")
    links2 = re.findall(r'href=["\']([^"\']*jobdetails[^"\']*)["\']', html)
    print(len(links2), links2[:3])

    browser.close()
