import sys

from playwright.sync_api import sync_playwright

sys.path.append("/home/rubengaona/bots/bot_multi_jobs")
from utils_stealth import apply_playwright_stealth

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context, page = apply_playwright_stealth(browser)
    r = page.goto("https://es.indeed.com/jobs?q=python&l=valencia&sort=date")
    print("Status:", r.status if r else "None")
    page.wait_for_timeout(3000)
    print("Title:", page.title())
    print("Length:", len(page.content()))
    browser.close()
