import json

from app.output.models import (
    AvailabilityState,
    Claim,
    Evidence,
    Operations,
    RunMetadata,
    TerminalEnvelope,
)
from scripts.audit_submission import audit_manifest, audit_output, audit_run_report, _valid_timestamp


ORG = "989061593"


def _envelope(org: str = ORG) -> TerminalEnvelope:
    evidence = Evidence(
        id="ev-1",
        source_url="https://data.brreg.no/enhetsregisteret/api/enheter/" + org,
        source_class="official_registry",
        retrieved_at="2026-11-07T10:00:00Z",
        content_sha256="a" * 64,
        claim_span="organisasjonsnummer: " + org,
    )
    return TerminalEnvelope(
        organisation_number=org,
        run=RunMetadata(
            run_id="test",
            started_at="2026-11-07T10:00:00Z",
            completed_at="2026-11-07T10:00:01Z",
            terminal_status="completed",
        ),
        claims=[
            Claim(
                field="legal_name",
                value="Example AS",
                availability=AvailabilityState.AVAILABLE,
                confidence=1.0,
                evidence_ids=["ev-1"],
            )
        ],
        evidence=[evidence],
        operations=Operations(requests=2, runtime_ms=1000, third_party_cost_usd=0.0),
    )


def test_manifest_accepts_valid_unique_ids(tmp_path):
    path = tmp_path / "input.jsonl"
    path.write_text(json.dumps({"organisation_number": ORG}) + "\n", encoding="utf-8")

    ids, errors = audit_manifest(path, expected_count=1)

    assert ids == [ORG]
    assert errors == []


def test_manifest_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "input.jsonl"
    row = json.dumps({"organisation_number": ORG})
    path.write_text(row + "\n" + row + "\n", encoding="utf-8")

    ids, errors = audit_manifest(path)

    assert ids == [ORG, ORG]
    assert any("duplicate" in error.lower() for error in errors)


def test_output_audit_accepts_matching_envelope(tmp_path):
    path = tmp_path / "output.jsonl"
    path.write_text(_envelope().model_dump_json() + "\n", encoding="utf-8")

    summary, errors = audit_output([ORG], path)

    assert summary["batch_contract"]["passed"] is True
    assert summary["evidence_integrity_issues"] == 0
    assert errors == []


def test_output_audit_rejects_wrong_company_order(tmp_path):
    path = tmp_path / "output.jsonl"
    path.write_text(_envelope().model_dump_json() + "\n", encoding="utf-8")

    _, errors = audit_output(["123456789"], path)

    assert any("do not exactly match" in error for error in errors)


def test_run_report_enforces_limits_and_validation(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(
        json.dumps(
            {
                "input_count": 1,
                "emitted_envelopes": 1,
                "elapsed_ms": 1000,
                "validation": {"passed": True},
                "budget": {"requests": 2, "third_party_cost_usd": 0.0},
            }
        ),
        encoding="utf-8",
    )

    summary, errors = audit_run_report(path, 10, 10, 0.0)

    assert summary["requests"] == 2
    assert errors == []


def test_run_report_rejects_over_budget(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(
        json.dumps(
            {
                "input_count": 1,
                "emitted_envelopes": 1,
                "elapsed_ms": 11000,
                "validation": {"passed": True},
                "budget": {"requests": 11, "third_party_cost_usd": 0.01},
            }
        ),
        encoding="utf-8",
    )

    _, errors = audit_run_report(path, 10, 10, 0.0)

    assert len(errors) == 3


def test_evidence_timestamps_must_be_utc_and_timezone_aware():
    assert _valid_timestamp("2026-11-07T10:00:00Z")
    assert _valid_timestamp("2026-11-07T10:00:00+00:00")
    assert not _valid_timestamp("2026-11-07T10:00:00")
    assert not _valid_timestamp("2026-11-07T10:00:00+05:30")
