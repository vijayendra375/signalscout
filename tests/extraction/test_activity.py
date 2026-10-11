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
    # A verified page with no jobs/news is "checked, zero found" -> available.
    page = _page("<html><body><h1>Welcome</h1><p>Ordinary content.</p></body></html>", "https://example.no/")
    claims = extract_hiring_and_activity([(page, "ev-1")])
    by = {c.field: c for c in claims}
    assert by["hiring_active"].value is False
    assert by["job_postings"].value == []
    # "Checked, zero found" is available (with the checked page as evidence),
    # which the contract distinguishes from a source that was not checked.
    assert by["job_postings"].availability == AvailabilityState.AVAILABLE
    assert by["job_postings"].evidence_ids == ["ev-1"]


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
