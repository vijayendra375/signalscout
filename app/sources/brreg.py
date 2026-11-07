"""Official Brønnøysundregistrene (Brreg) source adapter."""

from __future__ import annotations

import json
import threading
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

ALWAYS_ACCOUNTING_OBLIGED_FORMS = {"AS", "ASA", "BRL", "BBL", "STI", "SF", "VPFO"}
THRESHOLD_OR_ACTIVITY_FORMS = {"ENK", "ANS", "DA", "SA", "FLI", "ESEK", "NUF", "UTLA", "ORGL", "SAM", "SPA", "KS", "BO"}

# The Norwegian accounting obligation is defined by the Bokføringsloven and the
# annual-accounts regulation. SignalScout has no live, versioned feed of that
# rule set, so rule-based classifications below are LOCAL INFERENCES from the
# retrieved Brreg legal form -- not citations to a retrieved rule source.
# ``inference_confidence`` values are conservative priors, not measured certainty.
# Only ``filing_observed`` (a directly retrieved filing) carries full confidence.

ACCOUNTING_RULE_NOTE = (
    "Legal-form accounting rule is a local inference; no authoritative, "
    "versioned rule source was retrieved. Not a directly observed filing fact."
)

INFERENCE_CONFIDENCE = {
    "required_by_legal_form": 0.5,
    "threshold_or_activity_dependent": 0.5,
    "special_rule_or_review_required": 0.4,
}


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
        # Per-thread flag so a redirect hop denied by the request budget can be
        # distinguished from an ordinary 404/network failure by the orchestrator.
        self._local = threading.local()

    def _fetch_json(self, url: str) -> Tuple[Optional[Any], Optional[FetchResult]]:
        res = self.client.fetch(url, headers=BRREG_ACCEPT_JSON)
        self._local.blocked_by_budget = bool(res.blocked_by_budget)
        if res.status_code != 200:
            return None, res
        payload = parse_brreg_payload(res)
        return payload, res

    def last_fetch_blocked_by_budget(self) -> bool:
        """True when the most recent fetch on this thread was stopped by the budget."""
        return bool(getattr(self._local, "blocked_by_budget", False))

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
    ) -> dict[str, Any]:
        """Classify statutory accounting obligations without fabricating evidence.

        The returned ``basis`` distinguishes a claim observed in a retrieved
        filing from a local rule applied to the retrieved legal form. Rule-based
        results are labeled as inferences and carry no rule-source evidence; the
        caller must not present them as directly observed filing facts.
        """
        form = (legal_form or "").upper()
        if has_filed_accounts:
            classification = "filing_observed"
            basis = "retrieved_filing"
            reason = "The official registry reports an annual-account filing."
            rule_source = None
            effective_date = None
            applicability = "Directly observed annual-account filing in Regnskapsregisteret."
            inference_confidence = 1.0
        elif form in ALWAYS_ACCOUNTING_OBLIGED_FORMS:
            classification = "required_by_legal_form"
            basis = "legal_form_rule_inference"
            reason = f"Organisation form {form} is categorically subject to accounting obligation (local inference)."
            rule_source = None
            effective_date = None
            applicability = (
                f"Legal form {form}: always accounting-obliged under Norwegian "
                "rules (inference; no rule source retrieved)."
            )
            inference_confidence = INFERENCE_CONFIDENCE[classification]
        elif form in THRESHOLD_OR_ACTIVITY_FORMS:
            classification = "threshold_or_activity_dependent"
            basis = "legal_form_rule_inference"
            reason = "Accounting obligation depends on statutory size, turnover, partner, or supervision thresholds (local inference)."
            rule_source = None
            effective_date = None
            applicability = (
                f"Legal form {form}: threshold-dependent accounting obligation "
                "(inference; no rule source retrieved)."
            )
            inference_confidence = INFERENCE_CONFIDENCE[classification]
        else:
            classification = "special_rule_or_review_required"
            basis = "legal_form_rule_inference"
            reason = "Entity form is subject to special legal provisions (local inference)."
            rule_source = None
            effective_date = None
            applicability = (
                f"Legal form {form}: special provisions apply "
                "(inference; no rule source retrieved)."
            )
            inference_confidence = INFERENCE_CONFIDENCE[classification]

        return {
            "classification": classification,
            "legal_form": form or "UNKNOWN",
            "reason": reason,
            "basis": basis,
            "rule_source": rule_source,
            "effective_date": effective_date,
            "applicability": applicability,
            "inference_confidence": inference_confidence,
            "note": ACCOUNTING_RULE_NOTE if basis == "legal_form_rule_inference" else None,
        }
