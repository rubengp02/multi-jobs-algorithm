import time

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    print("Navigating...")
    page.goto(
        "https://www.infojobs.net/jobsearch/search-results/list.xhtml?keyword=python"
    )
    print("Wait...")
    time.sleep(5)
    print("Title:", page.title())
    print("Links with /of- :", len(page.locator("a[href*='/of-']").all()))
    print("Links with /oferta/ :", len(page.locator("a[href*='/oferta/']").all()))
    html = page.content()
    if "__INITIAL_PROPS__" in html:
        print("__INITIAL_PROPS__ found!")
    else:
        print("__INITIAL_PROPS__ NOT found!")

    if "__NEXT_DATA__" in html:
        print("__NEXT_DATA__ found!")

    browser.close()
