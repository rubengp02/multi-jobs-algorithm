from __future__ import annotations

import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LinkedInExtensionContractTests(unittest.TestCase):
    def test_challenge_requires_visible_verification_without_visible_jobs(self) -> None:
        source = (PROJECT_ROOT / "extension" / "content.js").read_text(encoding="utf-8")

        self.assertIn("function challengeAssessment()", source)
        self.assertIn("const visibleJobCards = cards.filter(isVisible).length", source)
        self.assertIn("challengeDetected: challengeVisible", source)
        self.assertIn("finalChallenge.challengeDetected", source)
        self.assertNotIn("function blockingReason()", source)

    def test_card_discovery_has_stable_identifier_fallback(self) -> None:
        source = (PROJECT_ROOT / "extension" / "content.js").read_text(encoding="utf-8")

        self.assertIn('"li.job-card-container"', source)
        self.assertIn('"[data-job-id]"', source)
        self.assertIn('selector: "job-link-fallback"', source)
        self.assertIn("const canonicalJobUrl", source)

    def test_stable_empty_list_is_not_misclassified_as_partial(self) -> None:
        source = (PROJECT_ROOT / "extension" / "content.js").read_text(encoding="utf-8")

        self.assertIn("const emptyResult = complete && found.size === 0", source)
        self.assertIn(
            'emptyResult ? "empty" : (complete ? "complete" : "partial")', source
        )

    def test_each_url_waits_for_its_own_navigation_before_extraction(self) -> None:
        source = (PROJECT_ROOT / "extension" / "background.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("async function waitForSearchNavigation", source)
        self.assertIn(
            "await waitForSearchNavigation(tab.id, url, navigationDiagnostics)", source
        )
        self.assertIn("const navigation = await waitForSearchNavigation", source)
        self.assertIn("tabUrl: loadedTab.url", source)
        self.assertIn(
            'const SEARCH_RUNTIME_PARAMS = new Set(["position", "pageNum"])', source
        )
        self.assertIn("return comparableUrl(left) === comparableUrl(right)", source)

    def test_navigation_confirmation_polls_when_update_events_are_lost(self) -> None:
        source = (PROJECT_ROOT / "extension" / "background.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("diagnostics.pollChecks += 1", source)
        self.assertIn("const tab = await chrome.tabs.get(tabId)", source)
        self.assertIn("pollTimer = setTimeout(poll, 500)", source)
        self.assertIn("diagnostics.updateEvents += 1", source)
        self.assertIn("error.navigationDiagnostics = diagnostics", source)

    def test_searches_are_serial_with_a_configured_inter_search_delay(self) -> None:
        source = (PROJECT_ROOT / "extension" / "background.js").read_text(
            encoding="utf-8"
        )

        self.assertIn("function interSearchDelayMilliseconds(settings)", source)
        self.assertIn('await reportStatus("inter_search_delay"', source)
        self.assertIn("await sleep(delayMs)", source)

    def test_delivery_and_reference_share_the_first_page_cap(self) -> None:
        source = (PROJECT_ROOT / "extension" / "content.js").read_text(encoding="utf-8")
        self.assertIn("const firstPageLimit = Math.min(25", source)
        self.assertIn("(?:empleos?|ofertas?|puestos?", source)
        self.assertIn(
            "referenceJobs: [...referenceFound.values()].slice(0, firstPageLimit)",
            source,
        )
        self.assertIn("jobs: [...found.values()].slice(0, firstPageLimit)", source)
        self.assertIn("for (const card of cards.slice(0, limit))", source)

    def test_stops_when_the_newest_first_page_target_is_reached(self) -> None:
        source = (PROJECT_ROOT / "extension" / "content.js").read_text(encoding="utf-8")

        self.assertIn("if (found.size >= requiredCards)", source)
        self.assertIn("firstPageTargetReached = true;", source)
        self.assertIn(
            "const complete = (firstPageTargetReached || scrollStabilised)", source
        )


if __name__ == "__main__":
    unittest.main()
