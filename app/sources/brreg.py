"""Official Brønnøysundregistrene (Brreg) source adapter."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from app.fetching.http_client import SafeHttpClient, FetchResult
from app.output.models import SourceClass
from app.evidence.store import EvidenceStore

BRREG_BASE = "https://data.brreg.no"
BRREG_ENTITY = BRREG_BASE + "/enhetsregisteret/api/enheter/{org}"
BRREG_ROLES = BRREG_BASE + "/enhetsregisteret/api/enheter/{org}/roller"
BRREG_GROUP = BRREG_BASE + "/enhetsregisteret/api/konsernstruktur/{org}"
BRREG_SUBUNITS = BRREG_BASE + "/enhetsregisteret/api/underenheter?overordnetEnhet={org}&size=1000"
BRREG_ACCOUNTS = BRREG_BASE + "/regnskapsregisteret/regnskap/{org}"
BRREG_ACCOUNT_YEARS = BRREG_BASE + "/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org}/aar"

# The Regnskapsregisteret endpoint defaults to an XML (Jackson) representation when
# the client advertises a preference for application/xml, which silently broke
# financial extraction. Always request JSON explicitly for Brreg API calls.
BRREG_ACCEPT_JSON = {"Accept": "application/json"}

ACCOUNTING_OBLIGATION_SOURCE = (
    "https://www.brreg.no/en/submission-of-annual-accounts/reporting-obligations-to-the-register-of-company-accounts/"
    "who-has-an-accounting-obligation/"
)
ALWAYS_ACCOUNTING_OBLIGED_FORMS = {"AS", "ASA", "BRL", "BBL", "STI", "SF", "VPFO"}
THRESHOLD_OR_ACTIVITY_FORMS = {"ENK", "ANS", "DA", "SA", "FLI", "ESEK", "NUF", "UTLA", "ORGL", "SAM", "SPA", "KS", "BO"}


def _xml_to_python(element: ET.Element) -> Any:
    """Convert a Jackson-style XML document (``<ArrayList><item>...``) into Python data."""
    tag = element.tag
    children = list(element)

    if tag in {"ArrayList", "list", "items"}:
        values = [_xml_to_python(child) for child in children if child.tag in {"item", "entry"}]
        return values

    if not children and not (element.text or "").strip():
        return None

    if not children:
        return (element.text or "").strip()

    # Nested object: collapse repeated <item> children into lists.
    result: Dict[str, Any] = {}
    for child in children:
        key = child.tag
        value = _xml_to_python(child)
        if key in result:
            if not isinstance(result[key], list):
                result[key] = [result[key]]
            result[key].append(value)
        else:
            result[key] = value
    return result


def parse_brreg_payload(res: FetchResult) -> Any:
    """Parse a Brreg response as JSON, falling back to XML when the server returns it."""
    text = (res.text or "").strip()
    if not text:
        return None
    if text[0] in "[{":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
    try:
        root = ET.fromstring(text)
        return _xml_to_python(root)
    except ET.ParseError:
        return None


class BrregAdapter:
    """Interface to official Norwegian registers."""

    def __init__(self, http_client: Optional[SafeHttpClient] = None) -> None:
        self.client = http_client or SafeHttpClient()

    def _fetch_json(self, url: str) -> Tuple[Optional[Any], Optional[FetchResult]]:
        res = self.client.fetch(url, headers=BRREG_ACCEPT_JSON)
        if res.status_code != 200:
            return None, res
        payload = parse_brreg_payload(res)
        return payload, res

    def fetch_entity(self, org: str, evidence_store: EvidenceStore) -> Tuple[Optional[dict[str, Any]], Optional[str]]:
        """Fetch primary entity record from Enhetsregisteret."""
        url = BRREG_ENTITY.format(org=org)
        data, res = self._fetch_json(url)
        if isinstance(data, dict):
            ev = evidence_store.add(
                source_url=url,
                source_class=SourceClass.OFFICIAL_REGISTRY,
                content=res.content if res else json.dumps(data).encode(),
                claim_span=f"Brønnøysundregistrene Enhetsregisteret: {data.get('navn')} ({org})",
            )
            return data, ev.id
        return None, None

    def fetch_roles(self, org: str, evidence_store: EvidenceStore) -> Tuple[Optional[list[dict[str, Any]]], Optional[str]]:
        """Fetch leadership roles and board of directors."""
        url = BRREG_ROLES.format(org=org)
        data, res = self._fetch_json(url)
        if data is not None:
            roles = data.get("rollegrupper", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            ev = evidence_store.add(
                source_url=url,
                source_class=SourceClass.OFFICIAL_REGISTRY,
                content=res.content if res else json.dumps(data).encode(),
                claim_span=f"Brønnøysundregistrene Roller: {len(roles)} rollegrupper for org {org}",
            )
            return roles, ev.id
        return None, None

    def fetch_financials(self, org: str, evidence_store: EvidenceStore) -> Tuple[Optional[list[dict[str, Any]]], Optional[str]]:
        """Fetch annual accounts from Regnskapsregisteret (JSON, XML fallback)."""
        url = BRREG_ACCOUNTS.format(org=org)
        data, res = self._fetch_json(url)
        if data is not None:
            records = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
            if records:
                ev = evidence_store.add(
                    source_url=url,
                    source_class=SourceClass.OFFICIAL_REGISTRY,
                    content=res.content if res else json.dumps(data).encode(),
                    claim_span=f"Regnskapsregisteret: {len(records)} årsregnskap funnet for org {org}",
                )
                return records, ev.id
        return None, None

    def fetch_subunits(self, org: str, evidence_store: EvidenceStore) -> Tuple[Optional[list[dict[str, Any]]], Optional[str]]:
        """Fetch operating workplaces / subunits."""
        url = BRREG_SUBUNITS.format(org=org)
        data, res = self._fetch_json(url)
        if data is not None:
            subunits = data.get("_embedded", {}).get("underenheter", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            ev = evidence_store.add(
                source_url=url,
                source_class=SourceClass.OFFICIAL_REGISTRY,
                content=res.content if res else json.dumps(data).encode(),
                claim_span=f"Underenheter: {len(subunits)} registrerte virksomheter for org {org}",
            )
            return subunits, ev.id
        return None, None

    def fetch_group_structure(self, org: str, evidence_store: EvidenceStore) -> Tuple[Optional[dict[str, Any]], Optional[str]]:
        """Fetch parent and group structure."""
        url = BRREG_GROUP.format(org=org)
        data, res = self._fetch_json(url)
        if isinstance(data, dict):
            ev = evidence_store.add(
                source_url=url,
                source_class=SourceClass.OFFICIAL_REGISTRY,
                content=res.content if res else json.dumps(data).encode(),
                claim_span=f"Konsernstruktur funnet for org {org}",
            )
            return data, ev.id
        return None, None

    @classmethod
    def evaluate_accounting_obligation(
        cls,
        legal_form: Optional[str],
        has_filed_accounts: bool,
        evidence_store: EvidenceStore,
    ) -> Tuple[dict[str, str], str]:
        """Classify statutory accounting obligations without guessing."""
        form = (legal_form or "").upper()
        if has_filed_accounts:
            classification = "filing_observed"
            reason = "The official registry reports an annual-account filing."
        elif form in ALWAYS_ACCOUNTING_OBLIGED_FORMS:
            classification = "required_by_legal_form"
            reason = f"Brreg lists organisation form {form} as always subject to accounting obligation."
        elif form in THRESHOLD_OR_ACTIVITY_FORMS:
            classification = "threshold_or_activity_dependent"
            reason = "Accounting obligation depends on statutory size, turnover, partner, or supervision thresholds."
        else:
            classification = "special_rule_or_review_required"
            reason = "Entity form is subject to special legal provisions."

        result = {
            "classification": classification,
            "legal_form": form or "UNKNOWN",
            "reason": reason,
        }
        ev = evidence_store.add(
            source_url=ACCOUNTING_OBLIGATION_SOURCE,
            source_class=SourceClass.OFFICIAL_REGISTRY,
            content=json.dumps(result).encode(),
            claim_span=f"Accounting obligation: {classification} ({reason})",
        )
        return result, ev.id
