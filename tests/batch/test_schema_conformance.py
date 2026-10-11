"""Output-contract schema conformance and batch invariants."""

from app.output.models import (
    AvailabilityState,
    Claim,
    Evidence,
    Operations,
    RunMetadata,
    SourceClass,
    TerminalEnvelope,
)
from app.output.serializer import validate_batch_envelopes

REQUIRED_ENVELOPE_KEYS = {
    "organisation_number", "run", "claims", "evidence", "changes", "errors", "operations",
}
REQUIRED_RUN_KEYS = {"run_id", "started_at", "completed_at", "terminal_status"}
REQUIRED_CLAIM_KEYS = {"field", "value", "availability", "confidence", "evidence_ids"}
REQUIRED_EVIDENCE_KEYS = {"id", "source_url", "source_class", "retrieved_at", "content_sha256", "claim_span"}
REQUIRED_OPERATIONS_KEYS = {"requests", "runtime_ms", "third_party_cost_usd"}


def _envelope(org="923609016"):
    ev = Evidence(
        id="ev-1",
        source_url="https://data.brreg.no/sample",
        source_class=SourceClass.OFFICIAL_REGISTRY,
        retrieved_at="2026-10-11T12:00:00Z",
        content_sha256="a" * 64,
        claim_span="sample",
    )
    claim = Claim(field="legal_name", value="X AS", availability=AvailabilityState.AVAILABLE, evidence_ids=["ev-1"])
    return TerminalEnvelope(
        organisation_number=org,
        run=RunMetadata(run_id="r", started_at="2026-10-11T12:00:00Z", completed_at="2026-10-11T12:00:01Z", terminal_status="completed"),
        claims=[claim],
        evidence=[ev],
        operations=Operations(requests=3, runtime_ms=100, third_party_cost_usd=0.0),
    )


def test_contract_dict_has_required_keys():
    d = _envelope().to_contract_dict()
    assert REQUIRED_ENVELOPE_KEYS.issubset(d.keys())
    assert "profile" not in d  # internal field must not leak into the contract
    assert REQUIRED_RUN_KEYS.issubset(d["run"].keys())
    assert REQUIRED_CLAIM_KEYS.issubset(d["claims"][0].keys())
    assert REQUIRED_EVIDENCE_KEYS.issubset(d["evidence"][0].keys())
    assert REQUIRED_OPERATIONS_KEYS.issubset(d["operations"].keys())


def test_enums_serialize_as_plain_strings():
    d = _envelope().to_contract_dict()
    assert d["evidence"][0]["source_class"] == "official_registry"
    assert d["claims"][0]["availability"] == "available"


def test_zero_cost_and_counts_present():
    d = _envelope().to_contract_dict()
    assert d["operations"]["third_party_cost_usd"] == 0.0
    assert d["operations"]["requests"] == 3


def test_validation_rejects_unknown_availability_and_unlinked_claim():
    env = _envelope()
    # Corrupt: an available claim with no evidence id.
    env.claims[0].evidence_ids = []
    result = validate_batch_envelopes([env], expected_count=1)
    assert result["passed"] is False
    assert result["checks"]["zero_unlinked_available_claims"] is False


def test_validation_passes_for_clean_batch():
    result = validate_batch_envelopes([_envelope("923609016"), _envelope("984851006")], expected_count=2)
    assert result["passed"] is True
