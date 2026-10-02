from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    response = page.goto(
        "https://www.manpower.es/es/all-jobs", wait_until="networkidle"
    )
    print("URL:", page.url)
    print("Title:", page.title())

    links = page.locator("a[href]").all()
    job_links = []
    for link in links:
        href = link.get_attribute("href")
        if href and ("/job/" in href or "/oferta/" in href):
            job_links.append(href)
    print("Found job links:", len(set(job_links)))
    if len(job_links) > 0:
        print(list(set(job_links))[:5])
    browser.close()
