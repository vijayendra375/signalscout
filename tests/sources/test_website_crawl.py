"""Bounded website crawl, robots compliance and contact extraction (offline)."""

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
