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

from app.extraction.website import WebsiteExtractor, registry_email_website_candidate

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

        

        # 1. Validate before creating any company profile, evidence, change or
        #    submission output. Invalid identifiers are rejected by the caller
        #    (batch filters them into diagnostics) rather than being coerced
        #    into a placeholder company identity.
        org = validate_org_number(org_input)

        requests_count = 0



        # 2. Official Foundation (Brreg) ΓÇö mark the per-company budget scope and

        #    reset the measured request counter first.

        if self.request_budget is not None:

            self.request_budget.start_company(org)

        try:

            # Reset the measured request counter after the budget scope is
            # marked, so every operation between start_company() and
            # complete_company() is inside the completion try/finally.
            self.http_client.start_request_count()




            # Priority order protects identity + financials first, then people, then

            # optional sources (group structure, website) that the budget may skip.

            # Track whether each source was actually fetched (budget permitting)

            can_fetch_entity = self.request_budget is None or self.request_budget.can_spend(1)

            if can_fetch_entity:

                raw_entity, entity_ev_id = self.brreg.fetch_entity(org, evidence_store)

                if self.brreg.last_fetch_blocked_by_budget():

                    can_fetch_entity = False

            else:

                raw_entity, entity_ev_id = None, None

            can_fetch_financials = self.request_budget is None or self.request_budget.can_spend(1)

            if can_fetch_financials:

                raw_financials, financials_ev_id = self.brreg.fetch_financials(org, evidence_store)

                if self.brreg.last_fetch_blocked_by_budget():

                    can_fetch_financials = False

            else:

                raw_financials, financials_ev_id = None, None

            can_fetch_roles = self.request_budget is None or self.request_budget.can_spend(1)

            if can_fetch_roles:

                raw_roles, roles_ev_id = self.brreg.fetch_roles(org, evidence_store)

                if self.brreg.last_fetch_blocked_by_budget():

                    can_fetch_roles = False

            else:

                raw_roles, roles_ev_id = None, None

            can_fetch_subunits = self.request_budget is None or self.request_budget.can_spend(1)

            if can_fetch_subunits:

                raw_subunits, subunits_ev_id = self.brreg.fetch_subunits(org, evidence_store)

                if self.brreg.last_fetch_blocked_by_budget():

                    can_fetch_subunits = False

            else:

                raw_subunits, subunits_ev_id = None, None

            # Group structure is optional and only meaningful for group members.

            raw_group, group_ev_id = None, None

            has_group = bool((raw_entity or {}).get("erIKonsern"))

            group_denied = False

            if has_group:

                if self.request_budget is None or self.request_budget.can_spend(1):

                    raw_group, group_ev_id = self.brreg.fetch_group_structure(org, evidence_store)

                    if self.brreg.last_fetch_blocked_by_budget():

                        group_denied = True

                else:

                    group_denied = True



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

            entity_forced = AvailabilityState.BLOCKED if not can_fetch_entity else None

            company_claims = extract_company_record(

                raw_entity, entity_ev_id, forced_availability=entity_forced

            )

            fin_forced = AvailabilityState.BLOCKED if not can_fetch_financials else None

            fin_claims = extract_financials(

                raw_financials, financials_ev_id, forced_availability=fin_forced

            )

            roles_forced = (

                AvailabilityState.BLOCKED if not can_fetch_roles else None

            )

            subunits_forced = (

                AvailabilityState.BLOCKED if not can_fetch_subunits else None

            )

            group_forced = (

                AvailabilityState.BLOCKED

                if (not can_fetch_entity) or group_denied

                else None

            )

            people_claims = extract_people_and_locations(

                raw_roles, roles_ev_id, raw_subunits, subunits_ev_id, raw_group, group_ev_id,

                roles_forced_availability=roles_forced,

                subunits_forced_availability=subunits_forced,

                group_forced_availability=group_forced,

            )



            legal_name = (raw_entity or {}).get("navn") or "Unknown"

            legal_form = ((raw_entity or {}).get("organisasjonsform") or {}).get("kode")

            # Accounting obligation assessment. Evidence must be a record that
            # was actually retrieved: the annual-account filing for a
            # filing-observed claim. A legal-form rule is a local inference and
            # is never cited as if the Brreg entity record proved the obligation;
            # missing rule evidence is not fabricated or replaced with the entity
            # record.
            has_filed_evidence = bool(raw_financials) and bool(financials_ev_id)

            if not can_fetch_entity:

                acct_claim = Claim(

                    field="accounting_obligation",

                    value=None,

                    availability=AvailabilityState.BLOCKED,

                    confidence=0.0,

                    evidence_ids=[],

                )

            elif has_filed_evidence:

                acct_result = self.brreg.evaluate_accounting_obligation(

                    legal_form, True

                )

                acct_claim = Claim(

                    field="accounting_obligation",

                    value=acct_result,

                    availability=AvailabilityState.AVAILABLE,

                    confidence=1.0,  # direct evidence: a retrieved filing

                    evidence_ids=[financials_ev_id],

                )

            elif not legal_form:

                acct_claim = Claim(

                    field="accounting_obligation",

                    value=None,

                    availability=AvailabilityState.NOT_AVAILABLE,

                    confidence=0.0,

                    evidence_ids=[],

                )

            elif entity_ev_id:

                acct_result = self.brreg.evaluate_accounting_obligation(

                    legal_form, False

                )

                acct_claim = Claim(

                    field="accounting_obligation",

                    value=acct_result,

                    availability=AvailabilityState.NOT_AVAILABLE,

                    confidence=0.0,  # rule-based inference not confirmed from evidence

                    evidence_ids=[],  # entity record does not prove the rule

                )

            else:

                # A rule-based classification without a retrieved source record
                # cannot be published as available.
                acct_claim = Claim(

                    field="accounting_obligation",

                    value=None,

                    availability=AvailabilityState.NOT_AVAILABLE,

                    confidence=0.0,

                    evidence_ids=[],

                )



            # 4. Website, Digital Footprint, Hiring and Public Activity

            website_candidate = (raw_entity or {}).get("hjemmeside")
            website_candidate_from_email = False
            if not website_candidate and entity_ev_id:
                website_candidate = registry_email_website_candidate(
                    (raw_entity or {}).get("epostadresse")
                )
                website_candidate_from_email = bool(website_candidate)

            can_fetch_website = self.request_budget is None or self.request_budget.can_spend(1)

            if can_fetch_website:

                website_research = self.website_extractor.research_website(

                    target_org=org,

                    target_legal_name=legal_name,

                    candidate_url=website_candidate,

                    evidence_store=evidence_store,
                    candidate_source_evidence_id=entity_ev_id if website_candidate_from_email else None,
                    require_trusted_identity=website_candidate_from_email,

                )

            else:

                website_research = self.website_extractor._blocked()



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

        finally:

            if self.request_budget is not None:

                self.request_budget.complete_company(org)
