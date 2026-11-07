"""Bounded website crawl, robots compliance and contact extraction (offline)."""

import json

from app.config.settings import settings
from app.fetching.http_client import FetchResult
from app.evidence.store import EvidenceStore
from app.extraction.website import WebsiteExtractor
from app.identity.firewall import IdentityDecision


class FakeClient:
    """Minimal offline stand-in for SafeHttpClient keyed by URL."""

    def __init__(self, pages, robots="User-agent: *\nAllow: /"):
        self.pages = pages
        self.robots = robots
        self.requested = []

    def fetch(self, url, **kwargs):
        self.requested.append(url)
        if url.endswith("/robots.txt"):
            text = self.robots if self.robots is not None else ""
            return self._make(url, 200 if self.robots is not None else 404, text)
        if url in self.pages:
            return self._make(url, 200, self.pages[url])
        return self._make(url, 404, "")

    def _make(self, url, status, text):
        return FetchResult(
            url=url,
            status_code=status,
            content=text.encode("utf-8"),
            text=text,
            content_type="text/html",
            elapsed_ms=1.0,
            bytes_received=len(text),
        )


HOME = (
    "<html><head><title>Acme Norge AS</title>"
    "<meta name='description' content='Acme industrial group'>"
    "</head><body>Acme Norge AS, org.nr 923 609 016. "
    "<a href='/karriere'>Karriere</a> "
    "<a href='mailto:post@acme.no'>post@acme.no</a> "
    "<a href='tel:+47 12 34 56 78'>call</a></body></html>"
)
CAREERS = (
    "<html><head><title>Karriere</title></head><body>"
    "<p>Ledige stillinger hos Acme Norge AS</p>"
    "<a href='mailto:jobb@acme.no'>jobb@acme.no</a></body></html>"
)

ORG_JSONLD_HOME = (
    "<html><head><title>Acme Norge AS</title>"
    "<script type='application/ld+json'>"
    + json.dumps({
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "Acme Norge AS",
        "legalName": "Acme Norge AS",
        "url": "https://acme.no/",
        "description": "Acme industrial group",
        "address": {
            "streetAddress": "Storgata 1",
            "addressLocality": "Oslo",
            "postalCode": "0001",
            "addressCountry": "NO"
        },
        "telephone": "+47 22 33 44 55",
        "email": "post@acme.no",
        "sameAs": ["https://linkedin.com/company/acme"],
        "identifier": {
            "@type": "PropertyValue",
            "name": "organisation number",
            "value": "923609016"
        }
    })
    + "</script></head><body>Acme Norge AS org.nr 923 609 016.</body></html>"
)

GRAPH_ORG_JSONLD_HOME = (
    "<html><head><title>Graph Org</title>"
    "<script type='application/ld+json'>"
    + json.dumps({
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "name": "Acme Norge AS",
                "legalName": "Acme Norge AS",
                "url": "https://acme.no/",
                "identifier": {
                    "@type": "PropertyValue",
                    "value": "923609016"
                }
            }
        ]
    })
    + "</script></head><body>Graph Org</body></html>"
)

ARRAY_JSONLD_HOME = (
    "<html><head><title>Array</title>"
    "<script type='application/ld+json'>"
    + json.dumps([
        {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": "Acme Norge AS",
            "legalName": "Acme Norge AS",
            "url": "https://acme.no/",
            "identifier": {
                "@type": "PropertyValue",
                "value": "923609016"
            }
        }
    ])
    + "</script></head><body>Array</body></html>"
)

MALFORMED_JSONLD_HOME = (
    "<html><head><title>Bad JSON</title>"
    "<script type='application/ld+json'>"
    + "{invalid json content here}"
    + "</script></head><body>Bad</body></html>"
)

WRONG_ORG_JSONLD_HOME = (
    "<html><head><title>Wrong Org</title>"
    "<script type='application/ld+json'>"
    + json.dumps({
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "Evil Corp",
        "identifier": {
            "@type": "PropertyValue",
            "name": "organisation number",
            "value": "999999999"
        }
    })
    + "</script></head><body>Evil Corp org.nr 999 999 999.</body></html>"
)

JOB_POSTING_HOME = (
    "<html><head><title>Jobs at Acme</title>"
    "<script type='application/ld+json'>"
    + json.dumps({
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Software Developer",
        "description": "We are hiring a developer",
        "datePosted": "2026-01-01",
        "validThrough": "2026-12-31",
        "employmentType": "FULL_TIME",
        "hiringOrganization": {
            "@type": "Organization",
            "name": "Acme Norge AS"
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "addressLocality": "Oslo",
                "addressCountry": "NO"
            }
        }
    })
    + "</script></head><body>Jobs</body></html>"
)

EXPIRED_JOB_POSTING_HOME = (
    "<html><head><title>Expired Job</title>"
    "<script type='application/ld+json'>"
    + json.dumps({
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Expired Role",
        "datePosted": "2020-01-01",
        "validThrough": "2020-12-31"
    })
    + "</script></head><body>Expired</body></html>"
)

MULTIPLE_JOB_POSTINGS_HOME = (
    "<html><head><title>Jobs</title>"
    "<script type='application/ld+json'>"
    + json.dumps([
        {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "Developer",
            "datePosted": "2026-01-01",
            "validThrough": "2026-12-31"
        },
        {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "Designer",
            "datePosted": "2026-02-01",
            "validThrough": "2026-12-31"
        }
    ])
    + "</script></head><body>Jobs</body></html>"
)

OVERSIZED_JSONLD_HOME = (
    "<html><head><title>Big JSON</title>"
    "<script type='application/ld+json'>"
    + json.dumps({"@type": "Organization", "name": "A" * 100000})
    + "</script></head><body>Big</body></html>"
)


def test_trusted_crawl_publishes_site_and_contacts():
    client = FakeClient({
        "https://acme.no/": HOME,
        "https://acme.no/karriere": CAREERS,
    })
    extractor = WebsiteExtractor(client)
    store = EvidenceStore()
    result = extractor.research_website("923609016", "Acme Norge AS", "https://acme.no/", store)
    by = {c.field: c for c in result.claims}

    assert by["official_website"].value == "https://acme.no/"
    assert by["contact_email"].value == "post@acme.no"
    assert by["contact_phone"].value is not None
    assert by["website_pages_crawled"].value >= 2
    # Careers page was crawled and produced a hiring signal.
    activity = {c.field: c for c in result.activity_claims}
    assert activity["hiring_active"].value is True


def test_rejected_domain_publishes_nothing():
    client = FakeClient({"https://evil.no/": "<html><body>Totally different firm AS 999999999</body></html>"})
    extractor = WebsiteExtractor(client)
    store = EvidenceStore()
    result = extractor.research_website("923609016", "Acme Norge AS", "https://evil.no/", store)
    by = {c.field: c for c in result.claims}
    assert by["official_website"].value is None


def test_robots_disallow_is_respected():
    client = FakeClient(
        {"https://acme.no/": HOME.replace("923 609 016", "923 609 016"), "https://acme.no/karriere": CAREERS},
        robots="User-agent: *\nDisallow: /karriere",
    )
    extractor = WebsiteExtractor(client)
    store = EvidenceStore()
    result = extractor.research_website("923609016", "Acme Norge AS", "https://acme.no/", store)
    # The careers path was disallowed, so it must never have been requested.
    assert "https://acme.no/karriere" not in client.requested


def test_missing_website_is_not_available():
    extractor = WebsiteExtractor(FakeClient({}))
    result = extractor.research_website("923609016", "Acme Norge AS", None, EvidenceStore())
    for c in result.claims:
        assert c.value is None or c.value == [] or c.availability.value == "not_available"


SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://acme.no/karriere</loc></url>
  <url><loc>https://acme.no/om-oss</loc></url>
  <url><loc>https://acme.no/kontakt</loc></url>
</urlset>"""

SITEMAP_INDEX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://acme.no/sitemap1.xml</loc></sitemap>
</sitemapindex>"""

SITEMAP1_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://acme.no/karriere</loc></url>
</urlset>"""

OFF_DOMAIN_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://evil.com/evil</loc></url>
</urlset>"""

XXE_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>&xxe;</loc></url>
</urlset>"""


def test_sitemap_xml_is_parsed_and_crawled():
    client = FakeClient({
        "https://acme.no/": HOME,
        "https://acme.no/sitemap.xml": SITEMAP_XML,
        "https://acme.no/karriere": CAREERS,
        "https://acme.no/om-oss": CAREERS,
        "https://acme.no/kontakt": CAREERS,
    })
    extractor = WebsiteExtractor(client)
    store = EvidenceStore()
    result = extractor.research_website("923609016", "Acme Norge AS", "https://acme.no/", store)
    assert "https://acme.no/sitemap.xml" in client.requested
    assert "https://acme.no/karriere" in client.requested
    assert "https://acme.no/om-oss" in client.requested
    assert "https://acme.no/kontakt" in client.requested


def test_sitemap_index_is_followed():
    client = FakeClient({
        "https://acme.no/": HOME,
        "https://acme.no/sitemap_index.xml": SITEMAP_INDEX_XML,
        "https://acme.no/sitemap1.xml": SITEMAP1_XML,
        "https://acme.no/karriere": CAREERS,
    })
    extractor = WebsiteExtractor(client)
    store = EvidenceStore()
    result = extractor.research_website("923609016", "Acme Norge AS", "https://acme.no/", store)
    assert "https://acme.no/sitemap_index.xml" in client.requested
    assert "https://acme.no/sitemap1.xml" in client.requested
    assert "https://acme.no/karriere" in client.requested


def test_off_domain_sitemap_urls_are_rejected():
    client = FakeClient({
        "https://acme.no/": HOME,
        "https://acme.no/sitemap.xml": OFF_DOMAIN_SITEMAP,
    })
    extractor = WebsiteExtractor(client)
    store = EvidenceStore()
    result = extractor.research_website("923609016", "Acme Norge AS", "https://acme.no/", store)
    assert "https://evil.com/evil" not in client.requested
    assert "https://acme.no/" in client.requested
    assert "https://acme.no/sitemap.xml" in client.requested


def test_xxe_attack_is_blocked():
    client = FakeClient({
        "https://acme.no/": HOME,
        "https://acme.no/sitemap.xml": XXE_SITEMAP,
    })
    extractor = WebsiteExtractor(client)
    store = EvidenceStore()
    result = extractor.research_website("923609016", "Acme Norge AS", "https://acme.no/", store)
    assert "file:///etc/passwd" not in client.requested


def test_url_deduplication():
    client = FakeClient({
        "https://acme.no/": HOME,
        "https://acme.no/sitemap.xml": SITEMAP_XML,
        "https://acme.no/karriere": CAREERS,
    })
    extractor = WebsiteExtractor(client)
    store = EvidenceStore()
    result = extractor.research_website("923609016", "Acme Norge AS", "https://acme.no/", store)
    assert client.requested.count("https://acme.no/karriere") == 1


def test_sitemap_url_limit_respected():
    urls = "\n".join(f"  <url><loc>https://acme.no/about{i}</loc></url>" for i in range(60))
    big_sitemap = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{urls}
</urlset>"""
    client = FakeClient({
        "https://acme.no/sitemap.xml": big_sitemap,
    })
    extractor = WebsiteExtractor(client)
    candidates = extractor._sitemap_candidates("https://acme.no/")
    assert len(candidates) <= settings.max_urls_per_sitemap


def test_organization_jsonld_extraction():
    """Organization JSON-LD is extracted and published as verified claims."""
    client = FakeClient({
        "https://acme.no/": ORG_JSONLD_HOME,
    })
    extractor = WebsiteExtractor(client)
    store = EvidenceStore()
    result = extractor.research_website("923609016", "Acme Norge AS", "https://acme.no/", store)
    by = {c.field: c for c in result.claims}

    assert by["organization_legal_name"].value == "Acme Norge AS"
    assert by["organization_legal_name"].availability.value == "available"
    assert by["official_website_url"].value == "https://acme.no/"
    assert by["contact_telephone"].value == "+47 22 33 44 55"
    assert by["contact_email_jsonld"].value == "post@acme.no"
    assert by["organization_description"].value == "Acme industrial group"


def test_organization_jsonld_with_graph():
    """Organization JSON-LD inside @graph is extracted."""
    client = FakeClient({
        "https://acme.no/": GRAPH_ORG_JSONLD_HOME,
    })
    extractor = WebsiteExtractor(client)
    store = EvidenceStore()
    result = extractor.research_website("923609016", "Acme Norge AS", "https://acme.no/", store)
    by = {c.field: c for c in result.claims}

    assert by["organization_legal_name"].value == "Acme Norge AS"
    assert by["organization_legal_name"].availability.value == "available"


def test_organization_jsonld_array():
    """Organization JSON-LD in a top-level array is extracted."""
    client = FakeClient({
        "https://acme.no/": ARRAY_JSONLD_HOME,
    })
    extractor = WebsiteExtractor(client)
    store = EvidenceStore()
    result = extractor.research_website("923609016", "Acme Norge AS", "https://acme.no/", store)
    by = {c.field: c for c in result.claims}

    assert by["organization_legal_name"].value == "Acme Norge AS"
    assert by["official_website_url"].value == "https://acme.no/"


def test_organization_jsonld_malformed():
    """Malformed JSON-LD is handled gracefully without crashing."""
    client = FakeClient({
        "https://acme.no/": MALFORMED_JSONLD_HOME,
    })
    extractor = WebsiteExtractor(client)
    store = EvidenceStore()
    result = extractor.research_website("923609016", "Acme Norge AS", "https://acme.no/", store)
    # Should not crash; no organization claims from malformed JSON
    org_claims = [c for c in result.claims if c.field == "organization_legal_name"]
    assert len(org_claims) == 0


def test_organization_identity_mismatch():
    """Organization JSON-LD with a different org number is rejected."""
    client = FakeClient({
        "https://acme.no/": WRONG_ORG_JSONLD_HOME,
    })
    extractor = WebsiteExtractor(client)
    store = EvidenceStore()
    result = extractor.research_website("923609016", "Acme Norge AS", "https://acme.no/", store)
    by = {c.field: c for c in result.claims}

    # Wrong org number -> no organization claims from JSON-LD
    org_claims = [c for c in result.claims if c.field.startswith("organization") or c.field == "contact_email_jsonld"]
    assert len(org_claims) == 0


def test_job_posting_extraction():
    """JobPosting JSON-LD is extracted with all fields."""
    client = FakeClient({
        "https://acme.no/": JOB_POSTING_HOME,
    })
    extractor = WebsiteExtractor(client)
    store = EvidenceStore()
    result = extractor.research_website("923609016", "Acme Norge AS", "https://acme.no/", store)
    activity = {c.field: c for c in result.activity_claims}

    assert activity["job_postings"].availability.value == "available"
    jobs = activity["job_postings"].value
    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Software Developer"
    assert job["description"] == "We are hiring a developer"
    assert job["date_posted"] == "2026-01-01"
    assert job["valid_through"] == "2026-12-31"
    assert job["employment_type"] == "FULL_TIME"
    assert job["hiring_organization"] == "Acme Norge AS"
    assert job["location"] == "Oslo, NO"
    assert job["source"] == "https://acme.no/"
    assert job["evidence_id"] is not None


def test_expired_job_posting_rejected():
    """Expired JobPosting (past validThrough) is not included."""
    client = FakeClient({
        "https://acme.no/": EXPIRED_JOB_POSTING_HOME,
    })
    extractor = WebsiteExtractor(client)
    store = EvidenceStore()
    result = extractor.research_website("923609016", "Acme Norge AS", "https://acme.no/", store)
    activity = {c.field: c for c in result.activity_claims}

    jobs = activity["job_postings"].value
    assert len(jobs) == 0


def test_multiple_job_postings():
    """Multiple JobPosting objects are all extracted."""
    client = FakeClient({
        "https://acme.no/": MULTIPLE_JOB_POSTINGS_HOME,
    })
    extractor = WebsiteExtractor(client)
    store = EvidenceStore()
    result = extractor.research_website("923609016", "Acme Norge AS", "https://acme.no/", store)
    activity = {c.field: c for c in result.activity_claims}

    jobs = activity["job_postings"].value
    assert len(jobs) == 2
    titles = {j["title"] for j in jobs}
    assert titles == {"Developer", "Designer"}


def test_evidence_source_url_and_timestamp():
    """Every claim carries source URL and evidence ID from EvidenceStore."""
    client = FakeClient({
        "https://acme.no/": ORG_JSONLD_HOME,
    })
    extractor = WebsiteExtractor(client)
    store = EvidenceStore()
    result = extractor.research_website("923609016", "Acme Norge AS", "https://acme.no/", store)

    # Check that evidence records exist with source URLs
    all_evidence = store.all()
    assert len(all_evidence) > 0
    for ev in all_evidence:
        assert ev.source_url is not None and ev.source_url != ""
        assert ev.retrieved_at is not None and ev.retrieved_at != ""
        assert ev.content_sha256 is not None and len(ev.content_sha256) == 64
        assert ev.claim_span is not None and ev.claim_span != ""

    # Check that claims reference evidence IDs
    for claim in result.claims:
        if claim.availability.value == "available":
            assert len(claim.evidence_ids) > 0
            for eid in claim.evidence_ids:
                assert store.get(eid) is not None


def test_cross_company_evidence_isolation():
    """Evidence from one company does not leak into another's envelope."""
    client = FakeClient({
        "https://acme.no/": ORG_JSONLD_HOME,
    })
    extractor = WebsiteExtractor(client)
    store = EvidenceStore()
    result_a = extractor.research_website("923609016", "Acme Norge AS", "https://acme.no/", store)

    # Extract evidence URLs from company A
    evidence_urls_a = {ev.source_url for ev in store.all()}

    # Now research a different company with a different client state
    client2 = FakeClient({
        "https://other.no/": "<html><body>Other Corp org.nr 111111111.</body></html>"
    })
    extractor2 = WebsiteExtractor(client2)
    store2 = EvidenceStore()
    result_b = extractor2.research_website("111111111", "Other Corp", "https://other.no/", store2)

    # Company B should not have any of company A's evidence URLs
    evidence_urls_b = {ev.source_url for ev in store2.all()}
    assert len(evidence_urls_a & evidence_urls_b) == 0


def test_oversized_jsonld_input():
    """Oversized JSON-LD is handled without crashing."""
    client = FakeClient({
        "https://acme.no/": OVERSIZED_JSONLD_HOME,
    })
    extractor = WebsiteExtractor(client)
    store = EvidenceStore()
    result = extractor.research_website("923609016", "Acme Norge AS", "https://acme.no/", store)
    # Should not crash; may or may not extract claims from oversized JSON
    assert result.pages_crawled >= 1
