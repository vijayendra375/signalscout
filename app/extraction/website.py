"""Company-controlled website and digital footprint extractor.

Performs a bounded, robots-compliant crawl of the registry-registered domain:
the homepage plus a small set of conventional company sections (about, contact,
leadership, careers, news) discovered from on-page links and the sitemap. Every
fetched page becomes its own evidence record so downstream claims can cite the
exact page that proved them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

from app.config.settings import settings
from app.documents.html_parser import parse_html_document, ParsedHtml
from app.evidence.store import EvidenceStore
from app.fetching.http_client import SafeHttpClient, FetchResult
from app.fetching.robots import RobotsGate
from app.identity.firewall import IdentityFirewall, IdentityDecision
from app.extraction.activity import extract_hiring_and_activity
from app.output.models import Claim, SourceClass
from app.verification.validator import create_claim_record


SECTION_PATHS = [
    "/om-oss", "/about", "/about-us", "/kontakt", "/contact",
    "/ledelse", "/leadership", "/team", "/karriere", "/careers",
    "/jobs", "/ledige-stillinger", "/nyheter", "/news", "/press", "/presse", "/aktuelt",
]
SECTION_KEYWORDS = re.compile(
    r"(om[-_ ]?oss|about|kontakt|contact|ledelse|leadership|team|karriere|career|job|stilling|nyhet|news|press|presse|aktuelt)",
    re.I,
)


@dataclass
class WebsiteResearch:
    """Result of researching a company's website."""
    claims: List[Claim] = field(default_factory=list)
    activity_claims: List[Claim] = field(default_factory=list)
    pages: List[Tuple[ParsedHtml, Optional[str]]] = field(default_factory=list)
    pages_crawled: int = 0


class WebsiteExtractor:
    """Discovers, validates, and extracts company website intelligence."""

    def __init__(self, http_client: Optional[SafeHttpClient] = None) -> None:
        self.client = http_client or SafeHttpClient()
        self.robots = RobotsGate(self.client, settings.user_agent)

    def _unavailable(self, with_activity: bool = True) -> WebsiteResearch:
        claims = [create_claim_record(f, None, []) for f in
                  ["official_website", "website_title", "website_description", "social_profiles", "contact_email", "contact_phone"]]
        activity = extract_hiring_and_activity(None) if with_activity else []
        return WebsiteResearch(claims=claims, activity_claims=activity)

    def _same_site(self, official_url: str, candidate_url: str) -> bool:
        a = urlparse(official_url).netloc.lower().lstrip("www.")
        b = urlparse(candidate_url).netloc.lower().lstrip("www.")
        return bool(b) and (b == a or b.endswith("." + a))

    def _sitemap_candidates(self, base_url: str) -> List[str]:
        found: List[str] = []
        for sm_path in ("/sitemap.xml", "/sitemap_index.xml"):
            sm_url = urljoin(base_url, sm_path)
            try:
                if not self.robots.allowed(sm_url):
                    continue
                res = self.client.fetch(sm_url)
            except Exception:
                continue
            if res.status_code != 200 or not res.text:
                continue
            for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", res.text, re.I):
                if self._same_site(base_url, loc) and SECTION_KEYWORDS.search(loc):
                    found.append(loc)
            if found:
                break
        return found

    def _candidate_subpages(self, base_url: str, homepage: ParsedHtml) -> List[str]:
        candidates: List[str] = []
        seen = set()

        def add(url: str) -> None:
            norm = url.split("#")[0].rstrip("/")
            if norm and norm != base_url.rstrip("/") and norm not in seen and self._same_site(base_url, url):
                seen.add(norm)
                candidates.append(url)

        for path in SECTION_PATHS:
            add(urljoin(base_url, path))

        for link in homepage.internal_links:
            if SECTION_KEYWORDS.search(link):
                add(link)

        for link in self._sitemap_candidates(base_url):
            add(link)

        return candidates

    def research_website(
        self,
        target_org: str,
        target_legal_name: str,
        candidate_url: Optional[str],
        evidence_store: EvidenceStore,
    ) -> WebsiteResearch:
        if not candidate_url:
            return self._unavailable()

        if not candidate_url.startswith("http://") and not candidate_url.startswith("https://"):
            candidate_url = "https://" + candidate_url

        fetch_res = self.client.fetch(candidate_url)
        if fetch_res.status_code != 200 or not fetch_res.text:
            return self._unavailable()

        parsed_html = parse_html_document(fetch_res.url, fetch_res.text)
        homepage_url = fetch_res.url

        assessment = IdentityFirewall.evaluate_website_evidence(
            target_org=target_org,
            target_legal_name=target_legal_name,
            official_domain=candidate_url,
            page_url=homepage_url,
            page_text=parsed_html.clean_text,
        )

        homepage_ev = evidence_store.add(
            source_url=homepage_url,
            source_class=SourceClass.COMPANY_OWNED,
            content=fetch_res.content,
            claim_span=f"Company website title: {parsed_html.title}. Identity decision: {assessment.decision.value}",
        )

        if assessment.decision == IdentityDecision.REJECTED:
            # Do not publish any company-owned claim for a non-matching domain.
            return self._unavailable()

        confidence = assessment.confidence
        pages: List[Tuple[ParsedHtml, Optional[str]]] = [(parsed_html, homepage_ev.id)]

        # Bounded, robots-compliant subpage crawl on the verified domain.
        pages_crawled = 1
        max_pages = max(1, settings.max_pages_per_website)
        if assessment.decision in {IdentityDecision.TRUSTED, IdentityDecision.QUARANTINED}:
            for sub_url in self._candidate_subpages(homepage_url, parsed_html):
                if pages_crawled >= max_pages:
                    break
                try:
                    if not self.robots.allowed(sub_url):
                        continue
                    sub_res = self.client.fetch(sub_url)
                except Exception:
                    continue
                if sub_res.status_code != 200 or not sub_res.text:
                    continue
                try:
                    sub_parsed = parse_html_document(sub_res.url, sub_res.text)
                except Exception:
                    continue
                sub_ev = evidence_store.add(
                    source_url=sub_res.url,
                    source_class=SourceClass.COMPANY_OWNED,
                    content=sub_res.content,
                    claim_span=f"Company subpage: {sub_parsed.title or sub_res.url}",
                )
                pages.append((sub_parsed, sub_ev.id))
                pages_crawled += 1

        # Website identity claims
        claims: List[Claim] = [
            create_claim_record("official_website", homepage_url, [homepage_ev.id], confidence=confidence),
            create_claim_record("website_title", parsed_html.title or None, [homepage_ev.id], confidence=confidence),
            create_claim_record("website_description", parsed_html.description or None, [homepage_ev.id], confidence=confidence),
            create_claim_record("social_profiles", parsed_html.social_links, [homepage_ev.id], confidence=confidence, observed=True),
        ]

        # Contact details aggregated across page evidence.
        email_ids: List[str] = []
        phone_ids: List[str] = []
        first_email: Optional[str] = None
        first_phone: Optional[str] = None
        for page, ev_id in pages:
            for email in page.emails:
                if first_email is None:
                    first_email = email
                if ev_id and ev_id not in email_ids:
                    email_ids.append(ev_id)
            for phone in page.phones:
                if first_phone is None:
                    first_phone = phone
                if ev_id and ev_id not in phone_ids:
                    phone_ids.append(ev_id)

        claims.append(create_claim_record("contact_email", first_email, email_ids, confidence=confidence))
        claims.append(create_claim_record("contact_phone", first_phone, phone_ids, confidence=confidence))
        claims.append(create_claim_record(
            "website_pages_crawled", pages_crawled,
            [homepage_ev.id] if pages_crawled else [],
            confidence=confidence,
        ))

        activity_claims = extract_hiring_and_activity(pages)

        return WebsiteResearch(claims=claims, activity_claims=activity_claims, pages=pages, pages_crawled=pages_crawled)
