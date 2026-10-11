"""Unit tests for batch processing, envelopes, and invariants."""

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


def create_dummy_envelope(org: str) -> TerminalEnvelope:
    ev = Evidence(
        id="ev-1",
        source_url="https://data.brreg.no/sample",
        source_class=SourceClass.OFFICIAL_REGISTRY,
        retrieved_at="2026-10-11T12:00:00Z",
        content_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        claim_span="Sample text",
    )
    cl = Claim(
        field="legal_name",
        value="Company AS",
        availability=AvailabilityState.AVAILABLE,
        confidence=1.0,
        evidence_ids=["ev-1"],
    )
    return TerminalEnvelope(
        organisation_number=org,
        run=RunMetadata(run_id="test-run", started_at="2026-10-11T12:00:00Z", completed_at="2026-10-11T12:00:01Z", terminal_status="completed"),
        claims=[cl],
        evidence=[ev],
        changes=[],
        errors=[],
        operations=Operations(requests=1, runtime_ms=100),
    )


def test_batch_validation_success():
    envelopes = [create_dummy_envelope("923609016"), create_dummy_envelope("984851006")]
    res = validate_batch_envelopes(envelopes, expected_count=2)
    assert res["passed"] is True
    assert res["checks"]["exact_expected_count"] is True
    assert res["checks"]["zero_silent_drops"] is True


def test_batch_validation_fails_on_silent_drop():
    # Only 1 envelope returned when 2 expected
    envelopes = [create_dummy_envelope("923609016")]
    res = validate_batch_envelopes(envelopes, expected_count=2)
    assert res["passed"] is False
    assert res["checks"]["exact_expected_count"] is False
    assert res["checks"]["zero_silent_drops"] is False


def test_batch_validation_fails_on_duplicate_org():
    envelopes = [create_dummy_envelope("923609016"), create_dummy_envelope("923609016")]
    res = validate_batch_envelopes(envelopes, expected_count=2)
    assert res["passed"] is False
    assert res["checks"]["unique_organisation_numbers"] is False
