from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(
        "https://www.manpower.es/es/buscar-trabajo", wait_until="domcontentloaded"
    )

    # Click SEARCH JOBS
    page.locator('button:has-text("SEARCH JOBS")').click()
    page.wait_for_timeout(5000)

    page.screenshot(path="/tmp/mp3.png")

    all_links = page.locator("a[href]").all()
    job_links = []
    for l in all_links:
        h = l.get_attribute("href")
        if h and ("job" in h.lower() or "oferta" in h.lower()):
            job_links.append(h)
    print("Found job links:", list(set(job_links))[:10])

    browser.close()
