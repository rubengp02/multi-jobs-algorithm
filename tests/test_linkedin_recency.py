from datetime import datetime, timezone

from models import JobItem
from providers.linkedin_common import merge_linkedin_jobs
from providers.linkedin_recency import evaluate_linkedin_recency

URL_20_MINUTES = "https://www.linkedin.com/jobs/search/?f_TPR=r1200&sortBy=DD"
URL_60_MINUTES = "https://www.linkedin.com/jobs/search/?f_TPR=r3600&sortBy=DD"


def _job(search_url: str, posted_text: str = "", published_at: str = "") -> JobItem:
    return JobItem(
        id="4459846749",
        title="Data Engineer",
        company="Example",
        location="Espana (En remoto)",
        url="https://www.linkedin.com/jobs/view/4459846749/",
        source="linkedin",
        features={
            "linkedin_search_urls": [search_url],
            "linkedin_recency_evidence": [
                {
                    "search_url": search_url,
                    "posted_text": posted_text,
                    "published_at": published_at,
                }
            ],
        },
    )


def test_accepts_age_proven_inside_configured_window() -> None:
    decision = evaluate_linkedin_recency(_job(URL_20_MINUTES, "Hace 14 minutos"))

    assert decision.state == "accepted"
    assert decision.age_seconds == 14 * 60
    assert decision.allowed_seconds == 20 * 60


def test_rejects_age_outside_configured_window() -> None:
    decision = evaluate_linkedin_recency(_job(URL_20_MINUTES, "Hace 41 minutos"))

    assert decision.state == "outside_window"
    assert decision.age_seconds == 41 * 60
    assert decision.allowed_seconds == 20 * 60


def test_duplicate_keeps_all_time_evidence_and_uses_narrowest_window() -> None:
    merged = merge_linkedin_jobs(
        _job(URL_20_MINUTES, "Hace 14 minutos"),
        _job(URL_60_MINUTES, "Hace 41 minutos"),
    )

    decision = evaluate_linkedin_recency(merged)

    assert decision.state == "outside_window"
    assert decision.allowed_seconds == 20 * 60
    assert decision.age_seconds == 41 * 60
    assert len(decision.source_urls) == 2


def test_rejects_card_without_a_parseable_time_instead_of_guessing() -> None:
    decision = evaluate_linkedin_recency(_job(URL_20_MINUTES, "Solicitud sencilla"))

    assert decision.state == "unverified"
    assert decision.reason == "card_has_no_parseable_age"


def test_accepts_iso_time_when_it_is_inside_window() -> None:
    now = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    decision = evaluate_linkedin_recency(
        _job(URL_20_MINUTES, published_at="2026-08-27T11:45:00Z"), now=now
    )

    assert decision.state == "accepted"
    assert decision.age_seconds == 15 * 60


def test_ignores_date_only_timestamp_when_visible_relative_age_is_available() -> None:
    decision = evaluate_linkedin_recency(
        _job(URL_20_MINUTES, "Hace 14 minutos", "2026-08-27")
    )

    assert decision.state == "accepted"
    assert decision.age_seconds == 14 * 60


def test_date_only_timestamp_does_not_claim_an_unverifiable_card_is_fresh() -> None:
    decision = evaluate_linkedin_recency(
        _job(URL_20_MINUTES, published_at="2026-08-27")
    )

    assert decision.state == "unverified"
