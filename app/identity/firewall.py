"""Identity Firewall — strict multi-signal containment against wrong-company publication."""

from __future__ import annotations

import re
import unicodedata
from enum import Enum
from typing import Any, List, Optional
from pydantic import BaseModel, Field

from .validator import normalize_org_number


class IdentityDecision(str, Enum):
    TRUSTED = "trusted"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"


class IdentitySignal(BaseModel):
    signal_type: str
    is_positive: bool
    description: str
    weight: float = 1.0


class IdentityAssessment(BaseModel):
    decision: IdentityDecision
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    matched_org_number: bool = False
    matched_legal_name: bool = False
    matched_domain: bool = False
    rejection_reason: Optional[str] = None
    signals: List[IdentitySignal] = Field(default_factory=list)


def normalize_text_for_comparison(text: str | None) -> str:
    """Normalize diacritics, punctuation, corporate suffixes, and whitespace for fuzzy comparison."""
    if not text:
        return ""
    # Normalize unicode (NFC/NFKD)
    normalized = unicodedata.normalize("NFKD", str(text))
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    normalized = normalized.lower()
    
    # Strip common Norwegian and global corporate entity suffixes
    suffixes = [
        r"\bas\b", r"\basa\b", r"\bda\b", r"\bans\b", r"\benk\b", r"\bholding\b",
        r"\bgroup\b", r"\bgruppe\b", r"\bnorge\b", r"\bnorway\b", r"\bab\b", r"\boy\b",
        r"\bltd\b", r"\bcorp\b", r"\binc\b", r"\bgmbh\b"
    ]
    for suf in suffixes:
        normalized = re.sub(suf, " ", normalized)
        
    # Replace non-alphanumeric with single space
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return " ".join(normalized.split())


class IdentityFirewall:
    """Central firewall enforcing zero wrong-company publication."""
    
    @classmethod
    def evaluate_website_evidence(
        cls,
        target_org: str,
        target_legal_name: str,
        official_domain: Optional[str],
        page_url: str,
        page_text: str,
        extracted_orgs: Optional[List[str]] = None,
    ) -> IdentityAssessment:
        signals: List[IdentitySignal] = []
        clean_target_org = normalize_org_number(target_org)
        
        # 1. Check for explicit organisation numbers in page content
        found_orgs = extracted_orgs or re.findall(r"\b\d{9}\b", page_text)
        found_orgs_clean = {normalize_org_number(o) for o in found_orgs}
        
        matched_org = clean_target_org in found_orgs_clean
        if matched_org:
            signals.append(IdentitySignal(
                signal_type="exact_org_number",
                is_positive=True,
                description=f"Exact target organisation number {clean_target_org} found in page text",
                weight=3.0,
            ))
        elif found_orgs_clean and len(found_orgs_clean) == 1:
            # Found exactly one organisation number, but it's DIFFERENT from target
            other_org = next(iter(found_orgs_clean))
            return IdentityAssessment(
                decision=IdentityDecision.REJECTED,
                confidence=0.0,
                matched_org_number=False,
                rejection_reason=f"Page contains conflicting organisation number {other_org} instead of target {clean_target_org}",
                signals=[IdentitySignal(
                    signal_type="conflicting_org_number",
                    is_positive=False,
                    description=f"Contradictory organisation number {other_org} detected",
                    weight=5.0,
                )],
            )
            
        # 2. Check for domain match with registry-registered website
        matched_domain = False
        if official_domain:
            norm_official = official_domain.lower().replace("https://", "").replace("http://", "").strip("/")
            norm_page = page_url.lower().replace("https://", "").replace("http://", "").strip("/")
            if norm_official in norm_page or norm_page in norm_official:
                matched_domain = True
                signals.append(IdentitySignal(
                    signal_type="official_domain_match",
                    is_positive=True,
                    description=f"Page URL matches registry official domain {official_domain}",
                    weight=2.5,
                ))

        # 3. Check for legal name match
        norm_target_name = normalize_text_for_comparison(target_legal_name)
        norm_page_text = normalize_text_for_comparison(page_text)
        
        matched_name = False
        if norm_target_name and norm_target_name in norm_page_text:
            matched_name = True
            signals.append(IdentitySignal(
                signal_type="exact_legal_name_match",
                is_positive=True,
                description=f"Normalized legal name '{norm_target_name}' found in text",
                weight=2.0,
            ))
            
        # 4. Decision logic
        if matched_org:
            decision = IdentityDecision.TRUSTED
            confidence = 0.99
        elif matched_domain and matched_name:
            decision = IdentityDecision.TRUSTED
            confidence = 0.95
        elif matched_domain:
            # Registry-linked site but company name/orgnr not found on page
            decision = IdentityDecision.QUARANTINED
            confidence = 0.60
        elif matched_name and len(norm_target_name.split()) >= 2:
            # Unique multi-word name match without domain or orgnr confirmation
            decision = IdentityDecision.QUARANTINED
            confidence = 0.50
        else:
            decision = IdentityDecision.REJECTED
            confidence = 0.10
            return IdentityAssessment(
                decision=decision,
                confidence=confidence,
                rejection_reason="No verifiable organisation number, official domain match, or specific legal name match found",
                signals=signals,
            )

        return IdentityAssessment(
            decision=decision,
            confidence=confidence,
            matched_org_number=matched_org,
            matched_legal_name=matched_name,
            matched_domain=matched_domain,
            signals=signals,
        )

    @classmethod
    def evaluate_role_identity(cls, candidate_role_name: str, official_role_names: List[str]) -> bool:
        """Verify that a named leader or board member belongs to official registry roles."""
        norm_cand = normalize_text_for_comparison(candidate_role_name)
        if not norm_cand:
            return False
        cand_words = set(norm_cand.split())
        for official in official_role_names:
            norm_off = normalize_text_for_comparison(official)
            if not norm_off:
                continue
            off_words = set(norm_off.split())
            if norm_cand == norm_off or norm_cand in norm_off or norm_off in norm_cand:
                return True
            if cand_words and off_words and (cand_words == off_words or cand_words.issubset(off_words) or off_words.issubset(cand_words)):
                return True
        return False
