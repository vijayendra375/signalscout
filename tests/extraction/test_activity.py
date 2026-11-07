"""Hiring and public-activity extraction across crawled pages."""

import json

from app.documents.html_parser import parse_html_document
from app.extraction.activity import extract_hiring_and_activity
from app.output.models import AvailabilityState


def _page(html: str, url: str = "https://example.no/karriere"):
    return parse_html_document(url, html)


def test_no_pages_returns_not_available():
    claims = extract_hiring_and_activity(None)
    for c in claims:
        assert c.availability == AvailabilityState.NOT_AVAILABLE
        assert c.value is None


def test_checked_site_without_signals_is_available_empty():
    page = _page("<html><body><h1>Welcome</h1><p>Ordinary content.</p></body></html>", "https://example.no/")
    claims = extract_hiring_and_activity([(page, "ev-1")])
    by = {c.field: c for c in claims}
    assert by["hiring_active"].value is False
    assert by["job_postings"].value == []
    assert by["job_postings"].availability == AvailabilityState.AVAILABLE
    assert by["job_postings"].evidence_ids == ["ev-1"]


def test_career_navigation_link_alone_does_not_mean_actively_hiring():
    page = _page(
        '<html><body><a href="/karriere">Karriere</a><p>Learn about our company.</p></body></html>',
        "https://example.no/",
    )
    claims = extract_hiring_and_activity([(page, "ev-careers")])
    by = {c.field: c for c in claims}
    assert by["hiring_active"].value is False
    assert by["hiring_active"].availability == AvailabilityState.AVAILABLE


def test_career_page_url_alone_does_not_mean_actively_hiring():
    page = _page("<html><body><h1>Our team</h1></body></html>")
    claims = extract_hiring_and_activity([(page, "ev-career-page")])
    by = {c.field: c for c in claims}
    assert by["hiring_active"].value is False


def test_explicit_hiring_text_is_a_positive_signal():
    page = _page(
        "<html><body><h1>We are hiring</h1><p>Join our team.</p></body></html>",
        "https://example.no/",
    )
    claims = extract_hiring_and_activity([(page, "ev-hiring-text")])
    by = {c.field: c for c in claims}
    assert by["hiring_active"].value is True
    assert by["hiring_active"].evidence_ids == ["ev-hiring-text"]


def test_jsonld_job_posting_extracted_with_evidence():
    ld = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Senior Engineer",
        "datePosted": "2026-01-01",
        "employmentType": "FULL_TIME",
        "jobLocation": {"address": {"addressLocality": "Oslo"}},
    }
    html = f'<html><head><script type="application/ld+json">{json.dumps(ld)}</script></head><body>Careers</body></html>'
    claims = extract_hiring_and_activity([(_page(html), "ev-9")])
    by = {c.field: c for c in claims}
    assert by["hiring_active"].value is True
    assert by["job_postings"].evidence_ids == ["ev-9"]
    assert by["job_postings"].value[0]["title"] == "Senior Engineer"
    assert by["job_postings"].value[0]["location"] == "Oslo"


def test_jsonld_news_article_extracted():
    ld = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": "Company wins award",
        "datePublished": "2026-02-02",
    }
    html = f'<html><head><script type="application/ld+json">{json.dumps(ld)}</script></head><body>News</body></html>'
    claims = extract_hiring_and_activity([(_page(html, "https://example.no/nyheter"), "ev-3")])
    by = {c.field: c for c in claims}
    assert by["public_activities"].value[0]["title"] == "Company wins award"
    assert by["public_activities"].evidence_ids == ["ev-3"]


def test_duplicate_jobs_deduplicated_across_pages():
    ld = {"@type": "JobPosting", "title": "Same Job"}
    html = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    p1 = _page(html, "https://example.no/karriere")
    claims = extract_hiring_and_activity([(p1, "ev-1"), (p1, "ev-1")])
    by = {c.field: c for c in claims}
    assert len(by["job_postings"].value) == 1
