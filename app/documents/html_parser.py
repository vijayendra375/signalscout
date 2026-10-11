"""HTML text, metadata, tables, and JSON-LD structured data parser."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import trafilatura


class ParsedHtml(BaseModel if False else object):
    def __init__(
        self,
        url: str,
        title: str,
        description: str,
        clean_text: str,
        structured_data: List[dict[str, Any]],
        social_links: List[dict[str, str]],
        internal_links: List[str],
        tables: List[List[List[str]]],
        emails: Optional[List[str]] = None,
        phones: Optional[List[str]] = None,
    ) -> None:
        self.url = url
        self.title = title
        self.description = description
        self.clean_text = clean_text
        self.structured_data = structured_data
        self.social_links = social_links
        self.internal_links = internal_links
        self.tables = tables
        self.emails = emails or []
        self.phones = phones or []


KNOWN_SOCIAL_DOMAINS = {
    "linkedin.com": "linkedin",
    "facebook.com": "facebook",
    "instagram.com": "instagram",
    "twitter.com": "twitter",
    "x.com": "x",
    "youtube.com": "youtube",
    "github.com": "github",
}


def parse_html_document(url: str, html_content: str) -> ParsedHtml:
    """Parse raw HTML content into structured components."""
    # 1. Clean readable text via trafilatura
    clean_text = trafilatura.extract(html_content) or ""
    
    # 2. BeautifulSoup DOM inspection
    soup = BeautifulSoup(html_content, "html.parser")
    
    # Title
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    elif soup.find("meta", property="og:title"):
        title = soup.find("meta", property="og:title").get("content", "").strip()
        
    # Meta description
    description = ""
    desc_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
    if desc_tag and desc_tag.get("content"):
        description = desc_tag.get("content", "").strip()

    # Fallback clean text from body if trafilatura returned empty
    if not clean_text and soup.body:
        # Strip script and style
        for s in soup.body(["script", "style", "noscript", "svg"]):
            s.decompose()
        clean_text = " ".join(soup.body.get_text(separator=" ").split())

    # 3. JSON-LD structured data
    structured_data: List[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        if script.string:
            try:
                data = json.loads(script.string.strip())
                if isinstance(data, list):
                    structured_data.extend(data)
                elif isinstance(data, dict):
                    structured_data.append(data)
            except Exception:
                pass

    # 4. Links and social profile detection
    social_links: List[dict[str, str]] = []
    internal_links: List[str] = []
    emails: List[str] = []
    phones: List[str] = []
    base_domain = urlparse(url).netloc.lower()
    
    seen_social = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        low_href = href.lower()
        if low_href.startswith("mailto:"):
            addr = href[7:].split("?")[0].strip()
            if addr and "@" in addr and addr.lower() not in {e.lower() for e in emails}:
                emails.append(addr)
            continue
        if low_href.startswith("tel:"):
            num = href[4:].strip()
            digits = re.sub(r"[^\d+]", "", num)
            if len(digits) >= 6 and num not in phones:
                phones.append(num)
            continue

        full_url = urljoin(url, href)
        parsed_href = urlparse(full_url)
        href_domain = parsed_href.netloc.lower()
        
        # Check for social platform
        matched_platform = None
        for domain, plat in KNOWN_SOCIAL_DOMAINS.items():
            if domain in href_domain:
                matched_platform = plat
                break
                
        if matched_platform and full_url not in seen_social:
            seen_social.add(full_url)
            social_links.append({"platform": matched_platform, "url": full_url})
        elif href_domain == base_domain and full_url not in internal_links:
            internal_links.append(full_url)

    # Structured Organization contact points (telephone / email)
    for item in structured_data:
        candidate_items = item if isinstance(item, list) else [item]
        for entry in candidate_items:
            if not isinstance(entry, dict):
                continue
            email = entry.get("email")
            if isinstance(email, str) and "@" in email and email not in emails:
                emails.append(email)
            phone = entry.get("telephone") or entry.get("phone")
            if isinstance(phone, str) and phone not in phones:
                phones.append(phone)

    # 5. Tables
    tables: List[List[List[str]]] = []
    for table in soup.find_all("table"):
        table_rows: List[List[str]] = []
        for tr in table.find_all("tr"):
            row_cells = [td.get_text(strip=True) for td in tr.find_all(["th", "td"])]
            if any(row_cells):
                table_rows.append(row_cells)
        if table_rows:
            tables.append(table_rows)

    return ParsedHtml(
        url=url,
        title=title,
        description=description,
        clean_text=clean_text,
        structured_data=structured_data,
        social_links=social_links,
        internal_links=internal_links[:50],
        tables=tables,
        emails=emails,
        phones=phones,
    )
