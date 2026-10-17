"""Single-company intelligence research pipeline."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.budget.request_budget import RequestBudget
from app.budget.tracker import BudgetTracker
from app.evidence.store import EvidenceStore, utc_now
from app.extraction.company_record import extract_company_record
from app.extraction.financials import extract_financials
from app.extraction.people_locations import extract_people_and_locations
from app.extraction.website import WebsiteExtractor
from app.fetching.http_client import SafeHttpClient
from app.identity.validator import validate_org_number
from app.llm.provider import get_provider
from app.output.models import (
    AvailabilityState,
    Claim,
    ErrorRecord,
    Operations,
    RunMetadata,
    TerminalEnvelope,
)
from app.sources.brreg import BrregAdapter
from app.storage.db import StorageDB
from app.synthesis.synthesizer import Synthesizer
from app.temporal.change_detector import ChangeDetector


class CompanyPipeline:
    """Executes the full evidence-backed research pipeline for a single company."""

    def __init__(
        self,
        http_client: Optional[SafeHttpClient] = None,
        db: Optional[StorageDB] = None,
        budget_tracker: Optional[BudgetTracker] = None,
        request_budget: Optional[RequestBudget] = None,
    ) -> None:
        self.http_client = http_client or SafeHttpClient()
        self.brreg = BrregAdapter(self.http_client)
        self.website_extractor = WebsiteExtractor(self.http_client)
        self.db = db
        self.budget = budget_tracker
        self.request_budget = request_budget
        self.provider = get_provider()

    def research_company(self, org_input: str, run_id: str = "run-1") -> TerminalEnvelope:
        start_time = time.time()
        started_at = utc_now()
        errors: List[ErrorRecord] = []
        evidence_store = EvidenceStore()
        
        # 1. Validate organisation number
        try:
            org = validate_org_number(org_input)
        except Exception as e:
            completed_at = utc_now()
            return TerminalEnvelope(
                organisation_number=str(org_input).strip(),
                run=RunMetadata(run_id=run_id, started_at=started_at, completed_at=completed_at, terminal_status="failed"),
                claims=[],
                evidence=[],
                changes=[],
                errors=[ErrorRecord(code="INVALID_ORG_NUMBER", message=str(e), timestamp=completed_at)],
                operations=Operations(requests=0, runtime_ms=int((time.time() - start_time) * 1000)),
            )

        requests_count = 0

        # 2. Official Foundation (Brreg) — mark the per-company budget scope and
        #    reset the measured request counter first.
        if self.request_budget is not None:
            self.request_budget.start_company(org)
        self.http_client.start_request_count()

        # Priority order protects identity + financials first, then people, then
        # optional sources (group structure, website) that the budget may skip.
        raw_entity, entity_ev_id = self.brreg.fetch_entity(org, evidence_store)
        raw_financials, financials_ev_id = self.brreg.fetch_financials(org, evidence_store)
        raw_roles, roles_ev_id = self.brreg.fetch_roles(org, evidence_store)
        raw_subunits, subunits_ev_id = self.brreg.fetch_subunits(org, evidence_store)

        # Group structure is optional and only meaningful for group members.
        raw_group, group_ev_id = None, None
        if bool((raw_entity or {}).get("erIKonsern")):
            raw_group, group_ev_id = self.brreg.fetch_group_structure(org, evidence_store)

        if raw_entity is None:
            # Valid organisation number, but the primary registry record could not
            # be retrieved. Identity could not be anchored, so the research is
            # partial rather than completed. All company facts are not_available.
            errors.append(ErrorRecord(
                code="REGISTRY_ENTITY_UNAVAILABLE",
                message="Enhetsregisteret entity record was not retrieved; company facts marked not_available.",
                timestamp=utc_now(),
            ))
            entity_unavailable = True
        else:
            entity_unavailable = False

        # 3. Extract claims from official foundation
        company_claims = extract_company_record(raw_entity, entity_ev_id)
        fin_claims = extract_financials(raw_financials, financials_ev_id)
        people_claims = extract_people_and_locations(
            raw_roles, roles_ev_id, raw_subunits, subunits_ev_id, raw_group, group_ev_id
        )

        legal_name = (raw_entity or {}).get("navn") or "Unknown"
        legal_form = ((raw_entity or {}).get("organisasjonsform") or {}).get("kode")
        has_accounts = bool(raw_financials)
        
        # Accounting obligation assessment
        acct_result, acct_ev_id = self.brreg.evaluate_accounting_obligation(legal_form, has_accounts, evidence_store)
        acct_claim = Claim(
            field="accounting_obligation",
            value=acct_result,
            availability=AvailabilityState.AVAILABLE,
            confidence=1.0,
            evidence_ids=[acct_ev_id],
        )

        # 4. Website, Digital Footprint, Hiring and Public Activity
        website_candidate = (raw_entity or {}).get("hjemmeside")
        website_research = self.website_extractor.research_website(
            target_org=org,
            target_legal_name=legal_name,
            candidate_url=website_candidate,
            evidence_store=evidence_store,
        )

        all_claims = (
            company_claims
            + fin_claims
            + people_claims
            + [acct_claim]
            + website_research.claims
            + website_research.activity_claims
        )

        requests_count = self.http_client.request_count()

        denied = getattr(self.http_client, "budget_denied_count", lambda: 0)()
        if denied > 0:
            errors.append(ErrorRecord(
                code="REQUEST_BUDGET_EXHAUSTED",
                message="One or more optional sources were skipped because the request/time budget was exhausted.",
                timestamp=utc_now(),
            ))

        # 6. Temporal change detection
        prior_claims = {}
        if self.db:
            prior_claims = self.db.get_prior_claims(org)
            
        changes = ChangeDetector.detect_changes(prior_claims, all_claims)
        
        if self.db:
            claims_dict = {c.field: c.value for c in all_claims if c.availability == AvailabilityState.AVAILABLE}
            self.db.update_claims(org, claims_dict, utc_now())

        # 7. Synthesis
        synthesis = Synthesizer.synthesize_overview(all_claims, changes, provider=self.provider)

        # 8. Envelope assembly
        completed_at = utc_now()
        runtime_ms = int((time.time() - start_time) * 1000)
        
        envelope = TerminalEnvelope(
            organisation_number=org,
            run=RunMetadata(
                run_id=run_id,
                started_at=started_at,
                completed_at=completed_at,
                terminal_status="partial" if entity_unavailable else "completed",
            ),
            claims=all_claims,
            evidence=evidence_store.all(),
            changes=changes,
            errors=errors,
            operations=Operations(
                requests=requests_count,
                runtime_ms=runtime_ms,
                third_party_cost_usd=0.0,
            ),
            profile={
                "organisation_number": org,
                "legal_name": legal_name,
                "synthesis": synthesis,
                "claims": {c.field: c.value for c in all_claims},
            },
        )
        return envelope
