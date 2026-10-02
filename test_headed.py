import sys

from playwright.sync_api import sync_playwright

sys.path.append("/home/rubengaona/bots/bot_multi_jobs")
from utils_stealth import apply_playwright_stealth

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context, page = apply_playwright_stealth(browser)
    r = page.goto("https://es.indeed.com/jobs?q=python&l=valencia&sort=date")
    print("Indeed Status:", r.status if r else "None")
    page.wait_for_timeout(3000)
    print("Indeed Title:", page.title())

    r2 = page.goto("https://www.infojobs.net/ofertas-trabajo/valencia/python")
    print("InfoJobs Status:", r2.status if r2 else "None")
    page.wait_for_timeout(3000)
    print("InfoJobs Title:", page.title())

    browser.close()
