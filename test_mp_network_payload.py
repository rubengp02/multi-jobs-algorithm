from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    def handle_request(request):
        if "searchjobs" in request.url:
            print(f"> {request.method} {request.url}")
            print("Post data:", request.post_data)

    page.on("request", handle_request)

    page.goto(
        "https://www.manpower.es/es/buscar-trabajo", wait_until="domcontentloaded"
    )

    try:
        page.locator('button:has-text("SEARCH JOBS")').click(timeout=5000)
    except:
        pass

    page.wait_for_timeout(3000)
    browser.close()
