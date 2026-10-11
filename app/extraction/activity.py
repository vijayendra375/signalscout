"""Hiring signals and dated public activity extractor (multi-page aware)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.documents.html_parser import ParsedHtml
from app.output.models import Claim
from app.verification.validator import create_claim_record


CAREER_PATTERN = re.compile(r"\b(karriere|careers|jobs|jobbe hos|ledige[-_ ]stillinger|stilling|vacanc)\b", re.I)
HIRING_TEXT_PATTERN = re.compile(
    r"\b(vi sok(er|jer)|vi ser etter|bli en del av|ledige stillinger|we are hiring|join our team|apply now|soknadsfrist)\b",
    re.I,
)
NEWS_PATTERN = re.compile(r"\b(nyheter|news|press|presse|aktuelt|announcement)\b", re.I)


def _iter_structured(parsed: ParsedHtml) -> List[dict[str, Any]]:
    items: List[dict[str, Any]] = []
    for entry in parsed.structured_data:
        if isinstance(entry, list):
            items.extend([e for e in entry if isinstance(e, dict)])
        elif isinstance(entry, dict):
            items.append(entry)
            graph = entry.get("@graph")
            if isinstance(graph, list):
                items.extend([g for g in graph if isinstance(g, dict)])
    return items


def extract_hiring_and_activity(
    pages: Optional[List[Tuple[ParsedHtml, Optional[str]]]],
) -> List[Claim]:
    """Extract Hiring and Public Activity claims across one or more verified pages.

    Every published claim is linked to the evidence record(s) of the page(s) that
    actually contained the signal. When a site was fetched but contained no hiring
    or activity signals this returns ``available`` with an empty list (a checked
    source with zero postings), never a fabricated value.
    """
    if not pages:
        return [
            create_claim_record("hiring_active", None, []),
            create_claim_record("job_postings", None, []),
            create_claim_record("public_activities", None, []),
        ]

    job_postings: List[dict[str, Any]] = []
    activities: List[dict[str, Any]] = []
    hiring_evidence_ids: List[str] = []
    activity_evidence_ids: List[str] = []

    seen_jobs = set()
    seen_news = set()

    for parsed, evidence_id in pages:
        eids = [evidence_id] if evidence_id else []

        # 1. Structured JobPosting in JSON-LD
        for item in _iter_structured(parsed):
            schema_type = item.get("@type")
            types = schema_type if isinstance(schema_type, list) else [schema_type]
            if "JobPosting" in types:
                title = item.get("title") or item.get("name") or "Untitled Role"
                key = (title, parsed.url)
                if key not in seen_jobs:
                    seen_jobs.add(key)
                    location = None
                    job_loc = item.get("jobLocation")
                    if isinstance(job_loc, dict):
                        addr = job_loc.get("address")
                        if isinstance(addr, dict):
                            location = addr.get("addressLocality") or addr.get("addressRegion")
                    job_postings.append({
                        "title": title,
                        "date_posted": item.get("datePosted"),
                        "valid_through": item.get("validThrough"),
                        "employment_type": item.get("employmentType"),
                        "location": location,
                        "source": parsed.url,
                        "evidence_id": evidence_id,
                    })
                    if evidence_id and evidence_id not in hiring_evidence_ids:
                        hiring_evidence_ids.append(evidence_id)

            if any(t in types for t in ("NewsArticle", "Article", "PressRelease", "BlogPosting")):
                headline = item.get("headline") or item.get("name")
                if headline:
                    key = (headline, parsed.url)
                    if key not in seen_news:
                        seen_news.add(key)
                        activities.append({
                            "category": "news_announcement",
                            "title": headline,
                            "date": item.get("datePublished") or item.get("dateModified"),
                            "source": parsed.url,
                            "evidence_id": evidence_id,
                        })
                        if evidence_id and evidence_id not in activity_evidence_ids:
                            activity_evidence_ids.append(evidence_id)

        # 2. Text / link heuristics for careers
        has_career_link = any(CAREER_PATTERN.search(link) for link in parsed.internal_links)
        has_career_text = bool(HIRING_TEXT_PATTERN.search(parsed.clean_text))
        has_career_url = bool(CAREER_PATTERN.search(parsed.url))
        if has_career_link or has_career_text or has_career_url:
            if evidence_id and evidence_id not in hiring_evidence_ids:
                hiring_evidence_ids.append(evidence_id)

    is_hiring = bool(job_postings) or bool(hiring_evidence_ids)

    # Evidence ids for every page actually checked, so that an "available but
    # empty" observation still satisfies the claim-to-evidence contract.
    checked_evidence_ids: List[str] = []
    for _, ev_id in pages:
        if ev_id and ev_id not in checked_evidence_ids:
            checked_evidence_ids.append(ev_id)

    claims: List[Claim] = []
    claims.append(create_claim_record(
        "hiring_active", is_hiring,
        hiring_evidence_ids if is_hiring else checked_evidence_ids,
        observed=True,
    ))
    claims.append(create_claim_record(
        "job_postings", job_postings,
        hiring_evidence_ids if job_postings else checked_evidence_ids,
        observed=True,
    ))
    claims.append(create_claim_record(
        "public_activities", activities,
        activity_evidence_ids if activities else checked_evidence_ids,
        observed=True,
    ))
    return claims
