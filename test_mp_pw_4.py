from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://www.manpower.es/es/candidatos", wait_until="networkidle")
    link = page.locator('a:has-text("Encontrar empleo")').first
    href = link.get_attribute("href")
    print("Encontrar empleo href:", href)

    all_links = page.locator("a[href]").all()
    for l in all_links:
        h = l.get_attribute("href")
        if h and ("empleo" in h.lower() or "oferta" in h.lower() or "job" in h.lower()):
            print("Found potential job link:", h)

    browser.close()
