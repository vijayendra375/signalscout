"""Offline end-to-end pipeline test: Brreg + website + activity + validation."""

import json
import threading

import pytest

from app.fetching.http_client import FetchResult
from app.orchestrator.pipeline import CompanyPipeline
from app.output.serializer import validate_batch_envelopes

ORG = "989061593"

ENTITY = {
    "organisasjonsnummer": ORG,
    "navn": "Testfirma AS",
    "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
    "forretningsadresse": {"adresse": ["Testveien 1"], "postnummer": "0001", "kommune": "OSLO"},
    "naeringskode1": {"kode": "62.010", "beskrivelse": "Programmeringstjenester"},
    "antallAnsatte": 12,
    "registreringsdatoEnhetsregisteret": "2015-01-01",
    "hjemmeside": "https://testfirma.no/",
}

ROLES = {"rollegrupper": [
    {"type": {"kode": "DAGL", "beskrivelse": "Daglig leder"},
     "roller": [{"type": {"kode": "DAGL", "beskrivelse": "Daglig leder"},
                 "person": {"navn": {"fornavn": "Kari", "etternavn": "Nordmann"}}}]},
]}

ACCOUNTS = [{
    "id": 1, "aar": 2024, "valuta": "NOK",
    "regnskapsperiode": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"},
    "resultatregnskapResultat": {
        "driftsresultat": {"driftsinntekter": {"sumDriftsinntekter": 5000000},
                           "driftsresultat": 800000},
        "aarsresultat": 600000,
    },
    "eiendeler": {"sumEiendeler": 9000000},
    "egenkapitalGjeld": {"egenkapital": {"sumEgenkapital": 4000000},
                         "gjeldOversikt": {"sumGjeld": 5000000}},
}]

SUBUNITS = {"_embedded": {"underenheter": [
    {"organisasjonsnummer": "911111111", "navn": "Testfirma AS AVD BERGEN",
     "forretningsadresse": {"kommune": "BERGEN", "poststed": "BERGEN"}, "antallAnsatte": 4},
]}}

HOMEPAGE = (
    "<html><head><title>Testfirma AS</title>"
    "<script type='application/ld+json'>"
    + json.dumps({"@type": "JobPosting", "title": "Utvikler", "datePosted": "2026-03-01"})
    + "</script></head><body>Testfirma AS org.nr 989 061 593. "
    "<a href='/karriere'>Karriere</a><a href='mailto:post@testfirma.no'>post@testfirma.no</a></body></html>"
)
CAREERS = "<html><body><h1>Ledige stillinger</h1></body></html>"


class FakeClient:
    """Minimal offline stand-in for SafeHttpClient keyed by URL.

    Optionally accepts a RequestBudget to simulate budget enforcement.
    """

    def __init__(self, pages=None, robots="User-agent: *\nAllow: /", budget=None, entity=None, blocked_urls=None, accounts=ACCOUNTS):
        self.pages = pages or {}
        self.robots = robots
        self.requested = []
        self.budget = budget
        self.count = 0
        self.entity = entity or ENTITY
        self.blocked_urls = set(blocked_urls or ())
        self.accounts = accounts

    def start_request_count(self):
        self.count = 0

    def request_count(self):
        return self.count

    def _make(self, url, status, text):
        return FetchResult(url=url, status_code=status, content=text.encode(),
                           text=text, content_type="text/html" if "<html" in text else "application/json",
                           elapsed_ms=1.0, bytes_received=len(text))

    def fetch(self, url, **kwargs):
        self.requested.append(url)
        self.count += 1
        if self.budget is not None and not self.budget.try_acquire(1):
            return FetchResult(
                url=url,
                status_code=429,
                content=b"",
                text="",
                content_type="text/plain",
                elapsed_ms=1.0,
                bytes_received=0,
                error="REQUEST_BUDGET_EXHAUSTED",
                blocked_by_budget=True,
            )
        if url in self.blocked_urls:
            # Simulates a redirect hop denied by the budget mid-fetch.
            return FetchResult(
                url=url,
                status_code=302,
                content=b"",
                text="",
                content_type="text/plain",
                elapsed_ms=1.0,
                bytes_received=0,
                error="REQUEST_BUDGET_EXHAUSTED",
                blocked_by_budget=True,
            )
        if "/enheter/" in url and url.endswith("/roller"):
            return self._make(url, 200, json.dumps(ROLES))
        if "/enheter/" in url and "/underenheter" not in url:
            return self._make(url, 200, json.dumps(self.entity))
        if "/underenheter" in url:
            return self._make(url, 200, json.dumps(SUBUNITS))
        if "/regnskap/" in url:
            if self.accounts is None:
                return self._make(url, 404, "")
            # Serve JSON (fallback path is covered separately).
            return self._make(url, 200, json.dumps(self.accounts))
        if "/konsernstruktur/" in url:
            return self._make(url, 404, "")
        if url.endswith("/robots.txt"):
            return self._make(url, 200, self.robots)
        if url.rstrip("/") == "https://testfirma.no":
            return self._make("https://testfirma.no/", 200, HOMEPAGE)
        if "testfirma.no/karriere" in url:
            return self._make(url, 200, CAREERS)
        return self._make(url, 404, "")


def test_pipeline_end_to_end_offline():
    client = FakeClient()
    pipeline = CompanyPipeline(http_client=client, db=None)
    env = pipeline.research_company(ORG, run_id="e2e")

    assert env.run.terminal_status == "completed"
    by = {c.field: c for c in env.claims}

    # Financials now populate and are evidence-linked.
    assert by["latest_revenue"].value == 5000000.0
    assert by["latest_revenue"].availability.value == "available"
    assert by["latest_revenue"].evidence_ids

    # People (real 'etternavn' field) and workplaces.
    assert by["managing_director"].value == "Kari Nordmann"
    assert by["workplaces_count"].value == 1

    # Website + activity.
    assert by["official_website"].value == "https://testfirma.no/"
    assert by["hiring_active"].value is True
    assert by["job_postings"].value and by["job_postings"].value[0]["title"] == "Utvikler"

    # Measured request accounting and contract invariants.
    assert env.operations.requests == client.count
    assert env.operations.third_party_cost_usd == 0.0
    result = validate_batch_envelopes([env], expected_count=1)
    assert result["passed"] is True, result["checks"]


def test_budget_exhaustion_skips_optional_sources():
    """When per-company budget is exhausted, optional sources are skipped gracefully."""
    from app.budget.request_budget import RequestBudget
    budget = RequestBudget(
        global_limit=2, per_company_limit=2, deadline_seconds=None
    )
    budget.set_total_companies(1)
    client = FakeClient(budget=budget)
    pipeline = CompanyPipeline(
        http_client=client, budget_tracker=None, request_budget=budget
    )
    env = pipeline.research_company(ORG, run_id="budget-test")

    # Identity and financials should be fetched (2 requests)
    by = {c.field: c for c in env.claims}
    assert env.operations.requests <= 2
    assert by["legal_name"].availability.value == "available"
    assert by["latest_revenue"].availability.value == "available"

    # Optional sources should be skipped due to budget
    assert by["managing_director"].availability.value == "blocked"
    assert by["official_website"].availability.value == "blocked"

    # Terminal status should be completed (not failed) - we still have identity
    assert env.run.terminal_status == "completed"


def test_budget_exhaustion_preserves_completed_envelope():
    """When budget runs out, completed envelope is still returned with available data."""
    from app.budget.request_budget import RequestBudget
    budget = RequestBudget(
        global_limit=1, per_company_limit=1, deadline_seconds=None
    )
    budget.set_total_companies(1)
    client = FakeClient(budget=budget)
    pipeline = CompanyPipeline(
        http_client=client, budget_tracker=None, request_budget=budget
    )
    env = pipeline.research_company(ORG, run_id="budget-test")

    # Only entity fetch should succeed (1 request)
    by = {c.field: c for c in env.claims}
    assert env.operations.requests <= 1
    assert by["legal_name"].availability.value == "available"
    # Everything else should be blocked (budget exhausted)
    assert by["latest_revenue"].availability.value == "blocked"
    assert env.run.terminal_status == "completed"


def test_concurrent_budget_fairness():
    """Multiple companies sharing a budget each get a fair share."""
    from app.budget.request_budget import RequestBudget

    budget = RequestBudget(
        global_limit=10, per_company_limit=10, deadline_seconds=None
    )
    budget.set_total_companies(5)

    orgs = [f"98906159{i}" for i in range(5)]  # 5 companies

    results = []
    lock = threading.Lock()

    def worker(org):
        budget.start_company(org)
        acquired = 0
        while budget.can_spend(1):
            if budget.try_acquire(1):
                acquired += 1
        with lock:
            results.append((org, acquired))
        budget.complete_company(org)

    threads = [threading.Thread(target=worker, args=(org,)) for org in orgs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total_granted = sum(a for _, a in results)
    assert total_granted <= 10, f"Granted {total_granted} over global limit 10"
    # Each company should get at least 1 request (fair share = 10/5 = 2)
    for org, acquired in results:
        assert acquired >= 1, f"Org {org} got only {acquired} requests"


def test_budget_exhaustion_during_website_crawl():
    """Website crawl is skipped when budget runs out during website phase."""
    from app.budget.request_budget import RequestBudget
    # Entity + financials = 2 requests, leaving 0 for website
    budget = RequestBudget(
        global_limit=2, per_company_limit=2, deadline_seconds=None
    )
    budget.set_total_companies(1)
    client = FakeClient(budget=budget)
    pipeline = CompanyPipeline(
        http_client=client, budget_tracker=None, request_budget=budget
    )
    env = pipeline.research_company(ORG, run_id="budget-test")

    by = {c.field: c for c in env.claims}
    assert env.operations.requests <= 2
    # Website should be blocked due to budget
    assert by["official_website"].availability.value == "blocked"
    # But identity should be available
    assert by["legal_name"].availability.value == "available"


def test_group_budget_denial_marks_group_blocked_only():
    """F3: group fetch denied by budget -> parent_entity BLOCKED, people remain available."""
    from app.budget.request_budget import RequestBudget

    entity = dict(ENTITY)
    entity["erIKonsern"] = True
    # entity + financials + roles + subunits = 4 requests; group is the 5th.
    budget = RequestBudget(global_limit=4, per_company_limit=4, deadline_seconds=None)
    budget.set_total_companies(1)
    client = FakeClient(budget=budget, entity=entity)
    pipeline = CompanyPipeline(
        http_client=client, budget_tracker=None, request_budget=budget
    )
    env = pipeline.research_company(ORG, run_id="group-budget")

    by = {c.field: c for c in env.claims}
    assert by["parent_entity"].availability.value == "blocked"
    assert by["managing_director"].availability.value == "available"
    assert by["workplaces_count"].availability.value == "available"


def test_roles_denial_does_not_block_subunits():
    """F5: a blocked roles fetch must not block workplace claims."""
    roles_url = f"https://data.brreg.no/enhetsregisteret/api/enheter/{ORG}/roller"
    client = FakeClient(blocked_urls=[roles_url])
    env = CompanyPipeline(http_client=client, db=None).research_company(
        ORG, run_id="roles-blocked"
    )
    by = {c.field: c for c in env.claims}

    assert by["managing_director"].availability.value == "blocked"
    assert by["all_roles"].availability.value == "blocked"
    assert by["workplaces_count"].availability.value == "available"
    assert by["operating_workplaces"].availability.value == "available"


def test_subunits_denial_does_not_block_roles():
    """F5: a blocked subunits fetch must not block role claims."""
    subunits_url = (
        "https://data.brreg.no/enhetsregisteret/api/underenheter"
        f"?overordnetEnhet={ORG}&size=1000"
    )
    client = FakeClient(blocked_urls=[subunits_url])
    env = CompanyPipeline(http_client=client, db=None).research_company(
        ORG, run_id="subunits-blocked"
    )
    by = {c.field: c for c in env.claims}

    assert by["workplaces_count"].availability.value == "blocked"
    assert by["operating_workplaces"].availability.value == "blocked"
    assert by["managing_director"].availability.value == "available"
    assert by["all_roles"].availability.value == "available"


def test_accounting_obligation_with_verified_filing():
    """F4: a filed annual account links to the actual filing evidence."""
    pipeline = CompanyPipeline(http_client=FakeClient(), db=None)
    env = pipeline.research_company(ORG, run_id="acct-verified")
    by = {c.field: c for c in env.claims}

    acct = by["accounting_obligation"]
    assert acct.availability.value == "available"
    assert acct.confidence == 1.0
    assert acct.evidence_ids
    assert acct.value["classification"] == "filing_observed"
    assert acct.value["basis"] == "retrieved_filing"

    evidence_by_id = {e.id: e for e in env.evidence}
    source_urls = [evidence_by_id[eid].source_url for eid in acct.evidence_ids]
    assert all("/regnskapsregisteret/regnskap/" in url for url in source_urls)
    assert not any("accounting-obligation" in url or "who-has-an-accounting" in url for url in source_urls)


def test_accounting_obligation_missing_legal_form_and_filing_is_not_available():
    """F4/F5: no legal form and no retrieved filing -> not_available."""
    entity = dict(ENTITY)
    entity.pop("organisasjonsform", None)
    pipeline = CompanyPipeline(
        http_client=FakeClient(entity=entity, accounts=None), db=None
    )
    env = pipeline.research_company(ORG, run_id="acct-missing")
    by = {c.field: c for c in env.claims}

    acct = by["accounting_obligation"]
    assert acct.availability.value == "not_available"
    assert acct.value is None
    assert acct.confidence == 0.0
    assert acct.evidence_ids == []


def test_accounting_obligation_blocked_entity_is_blocked():
    """F5: budget-blocked identity source -> accounting obligation BLOCKED."""
    from app.budget.request_budget import RequestBudget

    budget = RequestBudget(global_limit=1, per_company_limit=1, deadline_seconds=None)
    budget.set_total_companies(1)
    budget.start_company(ORG)
    # Consume the only request slot after the batch scope is established.
    assert budget.try_acquire(1) is True
    pipeline = CompanyPipeline(
        http_client=FakeClient(budget=budget),
        budget_tracker=None,
        request_budget=budget,
    )
    env = pipeline.research_company(ORG, run_id="acct-blocked")
    by = {c.field: c for c in env.claims}

    acct = by["accounting_obligation"]
    assert acct.availability.value == "blocked"
    assert acct.value is None
    assert acct.confidence == 0.0
    assert by["legal_name"].availability.value == "blocked"


def test_accounting_obligation_blocked_financials_is_rule_based_inference():
    """F3: blocked financials -> legal-form inference, no entity evidence cited,
    not presented as measured certainty."""
    from app.budget.request_budget import RequestBudget

    budget = RequestBudget(global_limit=1, per_company_limit=1, deadline_seconds=None)
    budget.set_total_companies(1)
    pipeline = CompanyPipeline(
        http_client=FakeClient(budget=budget),
        budget_tracker=None,
        request_budget=budget,
    )
    env = pipeline.research_company(ORG, run_id="acct-rule")
    by = {c.field: c for c in env.claims}

    acct = by["accounting_obligation"]
    assert by["latest_revenue"].availability.value == "blocked"
    # Rule-based inference is not confirmed from retrieved evidence.
    assert acct.availability.value == "not_available"
    assert acct.confidence == 0.0
    assert acct.evidence_ids == []
    # The entity record is NOT cited as proof of the accounting rule.
    assert acct.value["classification"] == "required_by_legal_form"
    assert acct.value["basis"] == "legal_form_rule_inference"
    assert acct.value["rule_source"] is None
    assert acct.value["effective_date"] is None
    assert "AS" in acct.value["applicability"]
    assert "no authoritative" in acct.value["note"]
    assert acct.value["inference_confidence"] == 0.5  # documented prior, not measured


def test_accounting_obligation_threshold_form_is_inference():
    """F3: threshold-dependent forms are labeled inference with rule-source fields."""
    entity = dict(ENTITY)
    entity["organisasjonsform"] = {"kode": "ENK", "beskrivelse": "Enkeltpersonforetak"}
    pipeline = CompanyPipeline(
        http_client=FakeClient(entity=entity, accounts=None), db=None
    )
    env = pipeline.research_company(ORG, run_id="acct-threshold")
    by = {c.field: c for c in env.claims}

    acct = by["accounting_obligation"]
    assert acct.availability.value == "not_available"
    assert acct.confidence == 0.0
    assert acct.evidence_ids == []
    assert acct.value["classification"] == "threshold_or_activity_dependent"
    assert acct.value["basis"] == "legal_form_rule_inference"
    assert acct.value["rule_source"] is None
    assert acct.value["effective_date"] is None
    assert acct.value["inference_confidence"] == 0.5


def test_accounting_obligation_unknown_form_is_inference():
    """F3: forms without a known rule are special-rule inferences."""
    entity = dict(ENTITY)
    entity["organisasjonsform"] = {"kode": "XXX", "beskrivelse": "Unknown form"}
    pipeline = CompanyPipeline(
        http_client=FakeClient(entity=entity, accounts=None), db=None
    )
    env = pipeline.research_company(ORG, run_id="acct-unknown")
    by = {c.field: c for c in env.claims}

    acct = by["accounting_obligation"]
    assert acct.availability.value == "not_available"
    assert acct.confidence == 0.0
    assert acct.evidence_ids == []
    assert acct.value["classification"] == "special_rule_or_review_required"
    assert acct.value["basis"] == "legal_form_rule_inference"
    assert acct.value["inference_confidence"] == 0.4


def test_entity_redirect_budget_block_marks_claims_blocked():
    """F4: a budget-denied redirect on the entity source -> BLOCKED, not NOT_AVAILABLE."""
    entity_url = f"https://data.brreg.no/enhetsregisteret/api/enheter/{ORG}"
    client = FakeClient(blocked_urls=[entity_url])
    pipeline = CompanyPipeline(http_client=client, db=None)
    env = pipeline.research_company(ORG, run_id="redirect-blocked")
    by = {c.field: c for c in env.claims}

    assert by["legal_name"].availability.value == "blocked"
    assert by["accounting_obligation"].availability.value == "blocked"
    assert by["parent_entity"].availability.value == "blocked"
    # Other sources are independent and must remain available.
    assert by["latest_revenue"].availability.value == "available"
    assert by["managing_director"].availability.value == "available"


def test_pipeline_completes_started_company_exactly_once():
    """F6: standalone path completes exactly one company."""
    from app.budget.request_budget import RequestBudget

    budget = RequestBudget(global_limit=50, per_company_limit=12, deadline_seconds=None)
    budget.set_total_companies(1)
    pipeline = CompanyPipeline(
        http_client=FakeClient(budget=budget),
        budget_tracker=None,
        request_budget=budget,
    )
    env = pipeline.research_company(ORG, run_id="complete-once")

    assert env.run.terminal_status == "completed"
    assert budget.completed_companies == 1


def test_pipeline_invalid_input_does_not_complete():
    """F6: invalid input is rejected before a company profile is created."""
    from app.budget.request_budget import RequestBudget

    budget = RequestBudget(global_limit=50, per_company_limit=12, deadline_seconds=None)
    budget.set_total_companies(1)
    pipeline = CompanyPipeline(
        http_client=FakeClient(budget=budget),
        budget_tracker=None,
        request_budget=budget,
    )
    with pytest.raises(ValueError):
        pipeline.research_company("123456789", run_id="invalid")

    assert budget.completed_companies == 0


def test_pipeline_unrepresentable_input_is_rejected_before_output():
    """F6: malformed input never produces a colliding placeholder envelope."""
    pipeline = CompanyPipeline(http_client=FakeClient(), db=None)

    with pytest.raises(ValueError):
        pipeline.research_company("not-an-org", run_id="junk")

    with pytest.raises(ValueError):
        pipeline.research_company("000000000", run_id="placeholder")


def test_pipeline_exception_completes_exactly_once():
    """F6: an exception after start_company still completes exactly once."""
    from app.budget.request_budget import RequestBudget

    class RaisingClient:
        def start_request_count(self):
            pass

        def request_count(self):
            return 0

        def budget_denied_count(self):
            return 0

        def fetch(self, url, **kwargs):
            raise RuntimeError("boom")

    budget = RequestBudget(global_limit=50, per_company_limit=12, deadline_seconds=None)
    budget.set_total_companies(1)
    pipeline = CompanyPipeline(
        http_client=RaisingClient(),
        budget_tracker=None,
        request_budget=budget,
    )

    try:
        pipeline.research_company(ORG, run_id="exception")
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError to propagate")

    assert budget.completed_companies == 1
