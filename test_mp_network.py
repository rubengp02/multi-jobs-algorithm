from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    def handle_request(request):
        if "graphql" in request.url or "api" in request.url or "job" in request.url:
            print(f"> {request.method} {request.url}")

    def handle_response(response):
        if (
            "graphql" in response.url or "api" in response.url
        ) and response.request.resource_type in ["fetch", "xhr"]:
            print(f"< {response.status} {response.url}")
            try:
                print("Response snippet:", str(response.body())[:100])
            except:
                pass

    page.on("request", handle_request)
    page.on("response", handle_response)

    page.goto(
        "https://www.manpower.es/es/buscar-trabajo", wait_until="domcontentloaded"
    )

    try:
        page.locator('button:has-text("SEARCH JOBS")').click(timeout=5000)
    except:
        print("Could not click search jobs")

    page.wait_for_timeout(3000)
    browser.close()
