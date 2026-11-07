"""Company-controlled website and digital footprint extractor.

Performs a bounded, robots-compliant crawl of the registry-registered domain:
the homepage plus a small set of conventional company sections (about, contact,
leadership, careers, news) discovered from on-page links and the sitemap. Every
fetched page becomes its own evidence record so downstream claims can cite the
exact page that proved them.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

from app.config.settings import settings
from app.documents.html_parser import parse_html_document, ParsedHtml
from app.evidence.store import EvidenceStore
from app.fetching.http_client import SafeHttpClient, FetchResult
from app.fetching.robots import RobotsGate
from app.identity.firewall import IdentityFirewall, IdentityDecision, normalize_text_for_comparison
from app.identity.validator import normalize_org_number
from app.extraction.activity import extract_hiring_and_activity
from app.output.models import AvailabilityState, Claim, SourceClass
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

# High-value page paths, in priority order. Used to rank sitemap-discovered URLs
# so the most informative pages are crawled first when the page budget is tight.
_PRIORITY_PATHS = (
    "/kontakt", "/contact", "/om-oss", "/about", "/about-us",
    "/karriere", "/careers", "/jobs", "/ledige-stillinger",
    "/nyheter", "/news", "/presse", "/press", "/aktuelt",
    "/services", "/tjenester", "/produkter", "/products",
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

    def _unavailable(self, with_activity: bool = True, forced_availability: Optional[AvailabilityState] = None) -> WebsiteResearch:
        claims = [create_claim_record(f, None, [], forced_availability=forced_availability) for f in
                  ["official_website", "website_title", "website_description", "social_profiles", "contact_email", "contact_phone"]]
        activity = extract_hiring_and_activity(None) if with_activity else []
        return WebsiteResearch(claims=claims, activity_claims=activity)

    def _blocked(self) -> WebsiteResearch:
        """Website work was prevented by the request/time budget, not by the source."""
        website_fields = [
            "official_website", "website_title", "website_description",
            "social_profiles", "contact_email", "contact_phone", "website_pages_crawled",
        ]
        claims = [create_claim_record(f, None, [], forced_availability=AvailabilityState.BLOCKED) for f in website_fields]
        activity = [
            create_claim_record(f, None, [], forced_availability=AvailabilityState.BLOCKED)
            for f in ["hiring_active", "job_postings", "public_activities"]
        ]
        return WebsiteResearch(claims=claims, activity_claims=activity)

    def _same_site(self, official_url: str, candidate_url: str) -> bool:
        a = urlparse(official_url).netloc.lower().lstrip("www.")
        b = urlparse(candidate_url).netloc.lower().lstrip("www.")
        return bool(b) and (b == a or b.endswith("." + a))

    def _parse_sitemap_xml(self, text: str) -> List[str]:
        """Parse a sitemap XML document, returning <loc> URLs.

        Uses ElementTree with external entity processing disabled (the default
        in Python 3.9+) to prevent XXE attacks. Handles both <urlset> (regular
        sitemap) and <sitemapindex> (sitemap index) root elements.
        """
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return []

        # Detect namespace (sitemaps may use a default namespace).
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}", 1)[0] + "}"

        urls: List[str] = []
        # Both <url><loc> (urlset) and <sitemap><loc> (sitemap index).
        for child in root:
            loc = child.find(ns + "loc")
            if loc is not None and loc.text:
                urls.append(loc.text.strip())
        return urls

    def _sitemap_index_refs(self, text: str, base_url: str) -> List[str]:
        """Extract <sitemap><loc> URLs from a sitemap index document.

        Only returns same-site references so an index cannot point the crawler
        off-domain.
        """
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return []

        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}", 1)[0] + "}"

        refs: List[str] = []
        for child in root:
            # Only <sitemap> children (not <url>) indicate an index document.
            if child.tag != ns + "sitemap" and child.tag != "sitemap":
                continue
            loc = child.find(ns + "loc")
            if loc is not None and loc.text:
                ref_url = loc.text.strip()
                if self._same_site(base_url, ref_url):
                    refs.append(ref_url)
        return refs

    def _priority_score(self, url: str) -> int:
        """Score a URL by how likely it contains useful company info.

        Higher = more useful. Based on path keywords and depth (closer to
        root = higher score).
        """
        path = urlparse(url).path.lower()
        for i, p in enumerate(_PRIORITY_PATHS):
            if p in path:
                return len(_PRIORITY_PATHS) - i  # Earlier = higher priority
        # Prefer shallower URLs (closer to root).
        return max(0, 10 - path.count("/"))

    def _extract_organization_from_jsonld(self, parsed_html: ParsedHtml) -> Optional[dict]:
        """Extract Organization data from JSON-LD structured data.

        Supports Organization, LocalBusiness, Corporation, LLC, Startup and
        related subtypes. Handles arrays, @graph, and multiple script tags.
        Returns the first matching Organization object or None.
        """
        for item in parsed_html.structured_data:
            if not isinstance(item, dict):
                continue

            types = item.get("@type")
            type_set: set = set()
            if isinstance(types, str):
                type_set.add(str(types).lower())
            elif isinstance(types, list):
                type_set = {str(t).lower() for t in types if isinstance(t, str)}

            org_types = {
                "organization", "localbusiness", "corporation", "llc",
                "startup", "store", "conveniencestore", "grocerystore",
                "pharmacy", "automotivebusiness", "professionalservice",
            }
            if type_set & org_types:
                return item

            # Also check @graph for nested Organization objects
            graph = item.get("@graph")
            if isinstance(graph, list):
                for g in graph:
                    if not isinstance(g, dict):
                        continue
                    gtypes = g.get("@type")
                    if isinstance(gtypes, str):
                        gtypes = [gtypes]
                    if not isinstance(gtypes, list):
                        continue
                    gtype_set = {str(t).lower() for t in gtypes if isinstance(t, str)}
                    if gtype_set & org_types:
                        return g
        return None

    def _extract_organization_fields(self, org_data: dict) -> dict:
        """Extract relevant fields from an Organization JSON-LD object.

        Returns a dict with keys: name, legal_name, url, description,
        address, telephone, email, same_as. Only includes fields that are
        present and non-empty.
        """
        result: dict = {}

        name = org_data.get("name")
        if isinstance(name, str) and name.strip():
            result["name"] = name.strip()

        legal_name = org_data.get("legalName")
        if isinstance(legal_name, str) and legal_name.strip():
            result["legal_name"] = legal_name.strip()

        url = org_data.get("url")
        if isinstance(url, str) and url.strip():
            result["url"] = url.strip()

        description = org_data.get("description")
        if isinstance(description, str) and description.strip():
            result["description"] = description.strip()

        address = org_data.get("address")
        if isinstance(address, str) and address.strip():
            result["address"] = address.strip()
        elif isinstance(address, dict):
            addr_parts = []
            for key in ("streetAddress", "addressLocality", "addressRegion",
                        "postalCode", "addressCountry"):
                val = address.get(key)
                if isinstance(val, str) and val.strip():
                    addr_parts.append(val.strip())
            if addr_parts:
                result["address"] = ", ".join(addr_parts)

        telephone = org_data.get("telephone")
        if isinstance(telephone, str) and telephone.strip():
            result["telephone"] = telephone.strip()

        email = org_data.get("email")
        if isinstance(email, str) and email.strip():
            result["email"] = email.strip()

        same_as = org_data.get("sameAs")
        if isinstance(same_as, str) and same_as.strip():
            result["same_as"] = same_as.strip()
        elif isinstance(same_as, list):
            same_as_list = [s.strip() for s in same_as if isinstance(s, str) and s.strip()]
            if same_as_list:
                result["same_as"] = same_as_list

        return result

    def _verify_organization_identity(
        self,
        org_data: dict,
        target_org: str,
        target_legal_name: str,
    ) -> bool:
        """Verify Organization JSON-LD against verified Brreg identity.

        Returns True if the organization data is consistent with the target
        company. Never allows JSON-LD to override the verified organization
        number. Treats mismatches as untrusted evidence.
        """
        # Check organization number if present
        identifier = org_data.get("identifier")
        if identifier is not None:
            if isinstance(identifier, dict):
                org_id = identifier.get("value", "")
            elif isinstance(identifier, str):
                org_id = identifier
            else:
                org_id = str(identifier)

            if org_id and org_id.strip():
                clean_id = normalize_org_number(org_id)
                clean_target = normalize_org_number(target_org)
                if clean_id and clean_target and clean_id != clean_target:
                    return False  # Mismatched organization number

        # Check name if present - allow substring match either way
        org_name = org_data.get("name")
        if org_name and isinstance(org_name, str) and org_name.strip():
            org_name_clean = normalize_text_for_comparison(org_name)
            target_name_clean = normalize_text_for_comparison(target_legal_name)
            if org_name_clean and target_name_clean:
                if org_name_clean not in target_name_clean and target_name_clean not in org_name_clean:
                    return False  # Name mismatch

        return True

    def _sitemap_candidates(self, base_url: str) -> List[str]:
        """Discover candidate subpage URLs from sitemap.xml / sitemap_index.xml.

        Respects robots.txt, same-domain constraint, and strict limits on the
        number of sitemaps and URLs processed so a sitemap cannot burn the
        request or URL budget.
        """
        found: List[str] = []
        seen: set[str] = set()

        for sm_path in ("/sitemap_index.xml", "/sitemap.xml"):
            sm_url = urljoin(base_url, sm_path)
            try:
                if not self.robots.allowed(sm_url):
                    continue
                res = self.client.fetch(sm_url)
            except Exception:
                continue
            if res.status_code != 200 or not res.text:
                continue

            urls = self._parse_sitemap_xml(res.text)

            # If this is a sitemap index, fetch referenced sitemaps (up to limit).
            sitemap_refs = self._sitemap_index_refs(res.text, base_url)
            for ref_url in sitemap_refs[: settings.max_sitemaps_per_website]:
                if not self._same_site(base_url, ref_url):
                    continue
                try:
                    if not self.robots.allowed(ref_url):
                        continue
                    ref_res = self.client.fetch(ref_url)
                except Exception:
                    continue
                if ref_res.status_code != 200 or not ref_res.text:
                    continue
                urls.extend(self._parse_sitemap_xml(ref_res.text))

            # Filter: same site + section keywords, dedupe, limit per sitemap.
            for url in urls:
                if not self._same_site(base_url, url):
                    continue
                if not SECTION_KEYWORDS.search(url):
                    continue
                if url in seen:
                    continue
                seen.add(url)
                found.append(url)
                if len(found) >= settings.max_urls_per_sitemap:
                    break

            if found:
                break  # Found usable URLs; don't try the other sitemap path.

        return found

    def _candidate_subpages(self, base_url: str, homepage: ParsedHtml) -> List[str]:
        homepage_links: List[str] = []
        sitemap_links: List[str] = []
        generic_links: List[str] = []
        seen: set[str] = set()

        def add(url_list: List[str], url: str) -> None:
            norm = url.split("#")[0].rstrip("/")
            if norm and norm != base_url.rstrip("/") and norm not in seen and self._same_site(base_url, url):
                seen.add(norm)
                url_list.append(norm)

        # Discovered links (from the homepage and sitemap) are tried first because
        # they are evidence-based and far more likely to exist than generic section
        # paths. Generic SECTION_PATHS are a last-resort fallback so a site full of
        # 404s cannot burn the attempt budget before reaching real pages.
        for link in homepage.internal_links:
            if SECTION_KEYWORDS.search(link):
                add(homepage_links, link)

        for link in self._sitemap_candidates(base_url):
            add(sitemap_links, link)

        for path in SECTION_PATHS:
            add(generic_links, urljoin(base_url, path))

        # Sort each group by priority score so the most useful pages are crawled
        # first within each group when the page/attempt budget is tight.
        homepage_links.sort(key=self._priority_score, reverse=True)
        sitemap_links.sort(key=self._priority_score, reverse=True)
        generic_links.sort(key=self._priority_score, reverse=True)

        return homepage_links + sitemap_links + generic_links

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
        if fetch_res.blocked_by_budget:
            # The budget stopped us before we could check the source.
            return self._blocked()
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

        # Extract Organization data from JSON-LD on the homepage and verify
        # against the verified Brreg identity. JSON-LD is corroborating
        # evidence only; it never overrides the verified organisation number.
        org_data = self._extract_organization_from_jsonld(parsed_html)
        org_verified = False
        org_fields: dict = {}
        if org_data:
            org_verified = self._verify_organization_identity(
                org_data, target_org, target_legal_name
            )
            if org_verified:
                org_fields = self._extract_organization_fields(org_data)

        confidence = assessment.confidence
        pages: List[Tuple[ParsedHtml, Optional[str]]] = [(parsed_html, homepage_ev.id)]

        # Bounded, robots-compliant subpage crawl on the verified domain.
        # Cap *attempts* (not only successes) so a site full of 404s cannot burn
        # the request budget, and stop immediately if the budget blocks us.
        pages_crawled = 1
        max_pages = max(1, settings.max_pages_per_website)
        max_attempts = max(1, settings.max_website_attempts)
        attempts = 1  # homepage already fetched
        if assessment.decision in {IdentityDecision.TRUSTED, IdentityDecision.QUARANTINED}:
            for sub_url in self._candidate_subpages(homepage_url, parsed_html):
                if pages_crawled >= max_pages or attempts >= max_attempts:
                    break
                try:
                    if not self.robots.allowed(sub_url):
                        continue
                    attempts += 1
                    sub_res = self.client.fetch(sub_url)
                except Exception:
                    continue
                if sub_res.blocked_by_budget:
                    break
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

        # Organization claims from verified JSON-LD data. These corroborate
        # Brreg registry data but never override it.
        if org_verified and org_fields:
            if "legal_name" in org_fields:
                claims.append(create_claim_record(
                    "organization_legal_name", org_fields["legal_name"],
                    [homepage_ev.id], confidence=confidence,
                ))
            if "url" in org_fields:
                claims.append(create_claim_record(
                    "official_website_url", org_fields["url"],
                    [homepage_ev.id], confidence=confidence,
                ))
            if "telephone" in org_fields:
                claims.append(create_claim_record(
                    "contact_telephone", org_fields["telephone"],
                    [homepage_ev.id], confidence=confidence,
                ))
            if "email" in org_fields:
                claims.append(create_claim_record(
                    "contact_email_jsonld", org_fields["email"],
                    [homepage_ev.id], confidence=confidence,
                ))
            if "description" in org_fields:
                claims.append(create_claim_record(
                    "organization_description", org_fields["description"],
                    [homepage_ev.id], confidence=confidence,
                ))

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
