import json
import time

from playwright.sync_api import sync_playwright

results = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    page = context.new_page()

    def handle_request(route, request):
        if "ef-api-frontoffice" in request.url:
            results.append(
                {
                    "url": request.url,
                    "method": request.method,
                    "post_data": request.post_data,
                }
            )
        route.continue_()

    page.route("**/*", handle_request)

    try:
        page.goto(
            "https://jobs.eurofirms.com/es/es/buscador-Ofertas-Empleo",
            wait_until="networkidle",
        )
        time.sleep(5)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        context.close()
    browser.close()

with open("/home/rubengaona/bots/bot_multi_jobs/euro_api.json", "w") as f:
    json.dump(results, f, indent=2)
