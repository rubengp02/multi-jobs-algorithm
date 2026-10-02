from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    r = page.goto(
        "https://www.infojobs.net/jobsearch/search-results/list.xhtml?keyword=python"
    )
    print("Playwright Status:", r.status if r else "None")
    page.wait_for_timeout(2000)
    print("Playwright Title:", page.title())
    browser.close()
