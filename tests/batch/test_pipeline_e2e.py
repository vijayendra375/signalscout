"""Offline end-to-end pipeline test: Brreg + website + activity + validation."""

import json

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
    def __init__(self):
        self.count = 0

    def start_request_count(self):
        self.count = 0

    def request_count(self):
        return self.count

    def _make(self, url, status, text):
        return FetchResult(url=url, status_code=status, content=text.encode(),
                           text=text, content_type="text/html" if "<html" in text else "application/json",
                           elapsed_ms=1.0, bytes_received=len(text))

    def fetch(self, url, **kwargs):
        self.count += 1
        if "/enheter/" in url and url.endswith("/roller"):
            return self._make(url, 200, json.dumps(ROLES))
        if "/enheter/" in url and "/underenheter" not in url:
            return self._make(url, 200, json.dumps(ENTITY))
        if "/underenheter" in url:
            return self._make(url, 200, json.dumps(SUBUNITS))
        if "/regnskap/" in url:
            # Serve JSON (fallback path is covered separately).
            return self._make(url, 200, json.dumps(ACCOUNTS))
        if "/konsernstruktur/" in url:
            return self._make(url, 404, "")
        if url.endswith("/robots.txt"):
            return self._make(url, 200, "User-agent: *\nAllow: /")
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
