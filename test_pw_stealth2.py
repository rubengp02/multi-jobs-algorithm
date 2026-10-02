import sys

sys.path.append("/home/rubengaona/bots/bot_multi_jobs")
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    stealth(page)

    print("Testing Indeed...")
    r = page.goto(
        "https://es.indeed.com/jobs?q=python&l=valencia&sort=date",
        wait_until="domcontentloaded",
    )
    print("Indeed Status:", r.status if r else "None")
    page.wait_for_timeout(3000)
    print("Indeed Title:", page.title())

    print("Testing InfoJobs...")
    r = page.goto(
        "https://www.infojobs.net/ofertas-trabajo/valencia/python",
        wait_until="domcontentloaded",
    )
    print("InfoJobs Status:", r.status if r else "None")
    page.wait_for_timeout(3000)
    print("InfoJobs Title:", page.title())

    browser.close()
