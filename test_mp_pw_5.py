from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://www.manpower.es/es/buscar-trabajo", wait_until="networkidle")
    print("URL:", page.url)

    # Wait for job links to appear
    page.wait_for_selector('a[href*="/job-details/"]', timeout=5000)

    all_links = page.locator("a[href]").all()
    job_links = []
    for l in all_links:
        h = l.get_attribute("href")
        if h and "/job-details/" in h:
            job_links.append(h)
    print("Found job links:", len(set(job_links)))
    if len(job_links) > 0:
        print(list(set(job_links))[:5])
    browser.close()
