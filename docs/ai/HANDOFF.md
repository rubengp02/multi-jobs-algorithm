# Handoff Context

## Current State
Phase 5 has been executed. **Grupo Noas** and **Michael Page** were successfully reverse engineered, patched in the core engine (`bot_multi_jobs/providers/consultancies.py`), and are now actively parsing jobs on the Raspberry Pi without relying on heavy Playwright rendering. **Melt Group** and **Eurofirms** have been strategically paused and quarantined due to extreme Cloudflare blocking and broken external APIs, respectively.

## Key Discoveries & Implementation Details
- **Grupo Noas:** The jobs container layout made the universal card extractor duplicate titles. A smart title extractor was injected directly into `_parse_page` and `_find_cards` to safely read nested elements. The Cloudflare HTTP check logic was modified to ignore false-positive `captcha` texts in the HTML body of Grupo Noas.
- **Michael Page:** Avoided Playwright dependencies by updating `index_url` to `https://www.michaelpage.es/jobs` and shifting strategy to `public_static`.
- **Melt Group:** Fails with a `403 Forbidden` Cloudflare challenge ("Just a moment..."). Playwright `domcontentloaded` wait strategies are ineffective because Cloudflare's Turnstile algorithm detects the headless environment.
- **Eurofirms:** Their main `www.eurofirms.es` domain currently suffers from an expired SSL Certificate. Their React SPA portal (`jobs.eurofirms.com`) consumes a private API (`ef-api-frontoffice.eurofirms.es`) that rejects unauthorized POST requests with a 404/403.

## Outstanding Issues / Warnings
- **Melt Group / Eurofirms:** Left in a `quarantine` (skipped) state. Attempting to scrape them will require advanced external tools (e.g. FlareSolverr, undetected-chromedriver, or valid API session tokens).

## Next Steps
- Await the user's next directive. The foundational consultancies are now deeply integrated and optimized for low-latency scanning.
