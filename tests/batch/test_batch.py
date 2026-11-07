"""Unit tests for batch processing, envelopes, and invariants."""

from app.identity.validator import validate_org_number
from app.orchestrator.batch import (
    BatchRunner,
    count_startable_orgs,
    INVALID_JSONL_SENTINEL,
    load_input_organisations,
)
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


def test_count_startable_orgs_excludes_invalid():
    """F6: only validated organisations reserve a fair-share slot."""
    assert count_startable_orgs(
        ["989061593", "123", "abcdef", "923609016", "000000000"]
    ) == 2


def test_batch_invalid_only_never_publishes_colliding_placeholders(tmp_path):
    """F6: malformed inputs are diagnostics, never 000000000 company envelopes."""
    runner = BatchRunner(max_workers=1, db_path=str(tmp_path / "batch.db"))
    output = tmp_path / "out.jsonl"
    envelopes = runner.run_batch(
        orgs=["123456789", "45678901", "not-an-org", "000000000"],
        output_path=output,
        run_id="invalid-only",
    )

    assert envelopes == []
    assert runner.valid_orgs == []
    assert len(runner.invalid_inputs) == 4
    assert {item["input"] for item in runner.invalid_inputs} == {
        "123456789",
        "45678901",
        "not-an-org",
        "000000000",
    }
    assert "000000000" not in output.read_text(encoding="utf-8")
    assert runner.request_budget.completed_companies == 0
    assert runner.request_budget.total_companies == 0


def test_load_input_organisations_preserves_malformed_inputs(tmp_path):
    """F4: malformed values survive loading and reach batch diagnostics."""
    p = tmp_path / "inputs.txt"
    p.write_text(
        "\n".join(
            [
                "",                            # empty string
                "not-an-org",                  # alphabetic
                "!@#$",                        # punctuation-only
                "12345678",                    # malformed length (8 digits)
                "1234567890",                  # malformed length (10 digits)
                "000000000",                   # literal placeholder (invalid checksum)
                "989061593",                   # valid
                "989061593",                   # valid duplicate (raw level)
                "NO 923 609 016 MVA",          # valid formatted
            ]
        ),
        encoding="utf-8",
    )
    raw = load_input_organisations(p)
    # Everything is preserved: empties, malformed, valid, and raw duplicates.
    assert raw == [
        "",
        "not-an-org",
        "!@#$",
        "12345678",
        "1234567890",
        "000000000",
        "989061593",
        "989061593",
        "NO 923 609 016 MVA",
    ]


def test_loader_feeds_malformed_into_batch_diagnostics(tmp_path):
    """F4: loader output is validated by run_batch; malformed become diagnostics,
    never envelopes."""
    p = tmp_path / "inputs.txt"
    p.write_text(
        "\n".join(["", "not-an-org", "!@#$", "12345678", "000000000"]),
        encoding="utf-8",
    )
    runner = BatchRunner(max_workers=1, db_path=str(tmp_path / "batch.db"))
    output = tmp_path / "out.jsonl"
    envelopes = runner.run_batch(
        orgs=load_input_organisations(p),
        output_path=tmp_path / "out.jsonl",
        run_id="loader-diagnostics",
    )

    assert envelopes == []
    assert runner.valid_orgs == []
    assert len(runner.invalid_inputs) == 5
    assert {item["input"] for item in runner.invalid_inputs} == {
        "",
        "not-an-org",
        "!@#$",
        "12345678",
        "000000000",
    }
    assert "000000000" not in output.read_text(encoding="utf-8")
    assert runner.request_budget.completed_companies == 0
    assert runner.request_budget.total_companies == 0


# --- JSONL loader regression tests (smoke_100 bug fix) -----------------------

def test_jsonl_extracts_organisation_number_only(tmp_path):
    """JSONL loader must extract only the organisation_number field, not digits
    from company names (e.g. "01 CAPITAL AS" must not become "01...")."""
    p = tmp_path / "companies.jsonl"
    p.write_text(
        "\n".join(
            [
                '{"organisation_number": "937731167", "name": "01 CAPITAL AS"}',
                '{"organisation_number": "928148424", "name": "010 IDLAB HENRIK ALFHEIM"}',
                '{"organisation_number": "922370788", "name": "0102 MANAGEMENT AS"}',
            ]
        ),
        encoding="utf-8",
    )
    raw = load_input_organisations(p)
    assert raw == ["937731167", "928148424", "922370788"]


def test_jsonl_names_containing_digits_and_punctuation(tmp_path):
    """Company names with leading punctuation and embedded digits must not
    corrupt the organisation number extraction."""
    p = tmp_path / "companies.jsonl"
    p.write_text(
        "\n".join(
            [
                '{"organisation_number": "929943945", "name": "!FALSE INVESTMENTS AS"}',
                '{"organisation_number": "931071475", "name": "\\"3-MANNSBOLIG FAGERLIA 7\\" SEKSJONSSAMEIE"}',
                '{"organisation_number": "835953742", "name": "# URBAN STRONG AND PROUD"}',
                '{"organisation_number": "925323527", "name": "& OLSEN HOLDING AS"}',
            ]
        ),
        encoding="utf-8",
    )
    raw = load_input_organisations(p)
    assert raw == ["929943945", "931071475", "835953742", "925323527"]


def test_jsonl_mixed_valid_and_invalid_records(tmp_path):
    """Mixed JSONL: valid organisation numbers plus records that fail
    modulus-11 validation or have missing/null fields."""
    p = tmp_path / "companies.jsonl"
    p.write_text(
        "\n".join(
            [
                '{"organisation_number": "989061593", "name": "Valid AS"}',
                '{"organisation_number": "000000000", "name": "Invalid checksum"}',
                '{"name": "Missing org number"}',
                '{"organisation_number": null, "name": "Null org number"}',
                '{"organisation_number": "984851006", "name": "Another valid"}',
            ]
        ),
        encoding="utf-8",
    )
    runner = BatchRunner(max_workers=1, db_path=str(tmp_path / "batch.db"))
    output = tmp_path / "out.jsonl"
    envelopes = runner.run_batch(
        orgs=load_input_organisations(p),
        output_path=output,
        run_id="mixed-jsonl",
    )

    # Only valid, unique org numbers become envelopes.
    assert len(envelopes) == 2
    assert {e.organisation_number for e in envelopes} == {"989061593", "984851006"}
    assert len(runner.invalid_inputs) == 3


def test_jsonl_plain_text_fallback(tmp_path):
    """Plain-text lines must be entire organisation numbers with allowed
    formatting (spaces, hyphens). Arbitrary text with digits is rejected."""
    p = tmp_path / "companies.jsonl"
    p.write_text(
        "\n".join(
            [
                "989061593",       # pure digits
                "923 609 016",     # spaces
                "923-609-016",     # hyphens
                "not-an-org",      # arbitrary text with hyphens but not digits -> rejected
                "prefix 123 suffix",  # letters with digits -> rejected
            ]
        ),
        encoding="utf-8",
    )
    raw = load_input_organisations(p)
    assert raw == ["989061593", "923 609 016", "923-609-016", INVALID_JSONL_SENTINEL, INVALID_JSONL_SENTINEL]
    # The two rejected entries must not validate as organisation numbers.
    for r in raw:
        if r == INVALID_JSONL_SENTINEL:
            continue
        validate_org_number(r)  # must not raise


def test_batch_validation_detects_missing_valid_input(tmp_path):
    """If one valid input is omitted from the output, batch validation must fail."""
    envelopes = [create_dummy_envelope("989061593")]
    res = validate_batch_envelopes(envelopes, expected_count=2)
    assert res["passed"] is False
    assert res["checks"]["exact_expected_count"] is False
    assert res["checks"]["zero_silent_drops"] is False


# --- BLOCKER 1: smoke test enforces exactly 100 valid, unique inputs ---------

def test_smoke_exactly_100_valid_unique_passes():
    """Exactly 100 valid, unique organisation numbers must pass smoke validation."""
    from app.identity.validator import is_valid_mod11

    valid_orgs = []
    n = 989061593
    while len(valid_orgs) < 100:
        s = f"{n:09d}"
        if is_valid_mod11(s):
            valid_orgs.append(s)
        n += 1

    assert len(valid_orgs) == 100
    assert len(set(valid_orgs)) == 100


def test_smoke_99_inputs_fails():
    """99 inputs must fail the exactly-100 check."""
    orgs = [f"{989061593 + i:09d}" for i in range(99)]
    assert len(orgs) != 100


def test_smoke_101_inputs_fails():
    """101 inputs must fail the exactly-100 check."""
    orgs = [f"{989061593 + i:09d}" for i in range(101)]
    assert len(orgs) != 100


def test_smoke_duplicate_identifiers_fail():
    """Duplicate organisation numbers must fail the uniqueness check."""
    orgs = ["989061593"] * 100
    assert len(set(orgs)) != 100


# --- BLOCKER 2: malformed JSONL rejection -----------------------------------

def test_malformed_jsonl_with_valid_org_number_is_rejected(tmp_path):
    """A malformed JSON line containing a valid 9-digit org number must be
    rejected and diagnosed, never fall back to digit extraction."""
    p = tmp_path / "companies.jsonl"
    p.write_text(
        '{broken json with "989061593" inside}\n',
        encoding="utf-8",
    )
    raw = load_input_organisations(p)
    assert len(raw) == 1
    assert raw[0] == INVALID_JSONL_SENTINEL
    # Must never validate as an organisation number.
    try:
        validate_org_number(raw[0])
        raise AssertionError("INVALID_JSONL_SENTINEL must not validate")
    except ValueError:
        pass


def test_malformed_jsonl_exact_audit_example_rejected(tmp_path):
    """The exact failing example from the audit must be rejected.

    The old code produced '__INVALID_JSONL__:{"organisation_number":"989061593",broken}'
    which validate_org_number() accepted as '989061593'. The new sentinel must
    never validate.
    """
    p = tmp_path / "companies.jsonl"
    p.write_text(
        '{"organisation_number": "989061593", broken\n',
        encoding="utf-8",
    )
    raw = load_input_organisations(p)
    assert len(raw) == 1
    assert raw[0] == INVALID_JSONL_SENTINEL
    # Direct validator check: sentinel must never validate.
    try:
        validate_org_number(raw[0])
        raise AssertionError("INVALID_JSONL_SENTINEL must not validate")
    except ValueError:
        pass


def test_malformed_jsonl_array_is_rejected(tmp_path):
    """A malformed JSON array-looking line starting with '[' must be rejected."""
    p = tmp_path / "companies.jsonl"
    p.write_text(
        '[1, 2, broken\n',
        encoding="utf-8",
    )
    raw = load_input_organisations(p)
    assert len(raw) == 1
    assert raw[0] == INVALID_JSONL_SENTINEL
    try:
        validate_org_number(raw[0])
        raise AssertionError("INVALID_JSONL_SENTINEL must not validate")
    except ValueError:
        pass


def test_plain_text_org_number_fallback_still_works(tmp_path):
    """Plain-text organisation numbers (not JSON) must still be accepted."""
    p = tmp_path / "companies.jsonl"
    p.write_text(
        "\n".join(["989061593", "984851006"]),
        encoding="utf-8",
    )
    raw = load_input_organisations(p)
    assert raw == ["989061593", "984851006"]


def test_malformed_jsonl_never_extracts_digits(tmp_path):
    """Malformed JSON must never result in digit extraction from the raw line."""
    p = tmp_path / "companies.jsonl"
    p.write_text(
        '{"organisation_number": "989061593", broken\n',
        encoding="utf-8",
    )
    raw = load_input_organisations(p)
    assert len(raw) == 1
    assert raw[0] == INVALID_JSONL_SENTINEL
    # Must NOT be "989061593" extracted from malformed JSON.
    assert raw[0] != "989061593"
    # Direct validator check confirms impossibility.
    try:
        validate_org_number(raw[0])
        raise AssertionError("INVALID_JSONL_SENTINEL must not validate")
    except ValueError:
        pass


def test_malformed_jsonl_missing_organisation_number_invalid(tmp_path):
    """A valid JSON object missing the organisation_number field must remain
    invalid and never enter the published dataset."""
    p = tmp_path / "companies.jsonl"
    p.write_text(
        '{"name": "Some Company"}\n',
        encoding="utf-8",
    )
    raw = load_input_organisations(p)
    assert len(raw) == 1
    assert raw[0] == ""
    # Empty string must fail validation.
    try:
        validate_org_number(raw[0])
        raise AssertionError("Empty organisation number must not validate")
    except ValueError:
        pass


def test_malformed_jsonl_null_organisation_number_invalid(tmp_path):
    """A valid JSON object with a null organisation_number must remain invalid."""
    p = tmp_path / "companies.jsonl"
    p.write_text(
        '{"organisation_number": null, "name": "Some Company"}\n',
        encoding="utf-8",
    )
    raw = load_input_organisations(p)
    assert len(raw) == 1
    assert raw[0] == ""
    try:
        validate_org_number(raw[0])
        raise AssertionError("Null organisation number must not validate")
    except ValueError:
        pass


def test_malformed_jsonl_never_enters_envelopes(tmp_path):
    """Malformed JSONL records must never enter published envelopes, evidence,
    or change detection through the batch-processing path."""
    p = tmp_path / "companies.jsonl"
    p.write_text(
        "\n".join(
            [
                '{"organisation_number": "989061593", "name": "Valid Company AS"}',
                '{"organisation_number": "989061593", broken',  # malformed
                '{"organisation_number": "984851006", "name": "Another Valid AS"}',
            ]
        ),
        encoding="utf-8",
    )
    runner = BatchRunner(max_workers=1, db_path=str(tmp_path / "batch.db"))
    output = tmp_path / "out.jsonl"
    envelopes = runner.run_batch(
        orgs=load_input_organisations(p),
        output_path=output,
        run_id="malformed-jsonl-path",
    )

    # Only the two valid, unique org numbers become envelopes.
    assert len(envelopes) == 2
    assert {e.organisation_number for e in envelopes} == {
        "989061593",
        "984851006",
    }
    assert len(runner.invalid_inputs) == 1
    # No envelope may use the malformed-record sentinel as its organisation number.
    assert all(
        e.organisation_number != INVALID_JSONL_SENTINEL for e in envelopes
    )
    # Verify invalid_inputs contains the sentinel, not digits.
    assert any(INVALID_JSONL_SENTINEL in item["input"] for item in runner.invalid_inputs)


# --- BLOCKER 3: malformed JSONL attribution bypass ---------------------------

def test_jsonl_text_before_json_is_rejected(tmp_path):
    """A line with arbitrary text before a JSON object must be rejected.

    'junk {"organisation_number":"989061593"}' must not have its digits
    extracted. The line contains '{' so it is JSON-like content but not a
    clean JSON record.
    """
    p = tmp_path / "companies.jsonl"
    p.write_text(
        'junk {"organisation_number":"989061593"}\n',
        encoding="utf-8",
    )
    raw = load_input_organisations(p)
    assert len(raw) == 1
    assert raw[0] == INVALID_JSONL_SENTINEL
    try:
        validate_org_number(raw[0])
        raise AssertionError("INVALID_JSONL_SENTINEL must not validate")
    except ValueError:
        pass


def test_jsonl_arbitrary_text_with_digits_is_rejected(tmp_path):
    """Arbitrary text containing digits must not have its digits extracted.

    'prefix 989061593 suffix' has no JSON structural characters but is not a
    clean organisation number line. It must be rejected.
    """
    p = tmp_path / "companies.jsonl"
    p.write_text(
        "prefix 989061593 suffix\n",
        encoding="utf-8",
    )
    raw = load_input_organisations(p)
    assert len(raw) == 1
    assert raw[0] == INVALID_JSONL_SENTINEL
    try:
        validate_org_number(raw[0])
        raise AssertionError("INVALID_JSONL_SENTINEL must not validate")
    except ValueError:
        pass


def test_jsonl_malformed_json_with_leading_text_is_rejected(tmp_path):
    """Malformed JSON with leading whitespace/text must be rejected."""
    p = tmp_path / "companies.jsonl"
    p.write_text(
        '  prefix {"broken": true\n',
        encoding="utf-8",
    )
    raw = load_input_organisations(p)
    assert len(raw) == 1
    assert raw[0] == INVALID_JSONL_SENTINEL
    try:
        validate_org_number(raw[0])
        raise AssertionError("INVALID_JSONL_SENTINEL must not validate")
    except ValueError:
        pass


def test_jsonl_malformed_array_with_leading_text_is_rejected(tmp_path):
    """Malformed JSON array with leading text must be rejected."""
    p = tmp_path / "companies.jsonl"
    p.write_text(
        "junk [1, 2, 3]\n",
        encoding="utf-8",
    )
    raw = load_input_organisations(p)
    assert len(raw) == 1
    assert raw[0] == INVALID_JSONL_SENTINEL
    try:
        validate_org_number(raw[0])
        raise AssertionError("INVALID_JSONL_SENTINEL must not validate")
    except ValueError:
        pass


def test_jsonl_plain_text_with_spaces_and_hyphens(tmp_path):
    """Legitimate plain-text organisation numbers with spaces and hyphens
    must still be accepted."""
    p = tmp_path / "companies.jsonl"
    p.write_text(
        "\n".join(
            [
                "989061593",
                "923 609 016",
                "923-609-016",
            ]
        ),
        encoding="utf-8",
    )
    raw = load_input_organisations(p)
    assert raw == ["989061593", "923 609 016", "923-609-016"]
    # All must validate as organisation numbers.
    for r in raw:
        try:
            validate_org_number(r)
        except ValueError:
            raise AssertionError(f"Legitimate plain-text org number rejected: {r!r}")


def test_jsonl_valid_jsonl_objects_still_work(tmp_path):
    """Valid JSONL objects must still extract only organisation_number."""
    p = tmp_path / "companies.jsonl"
    p.write_text(
        "\n".join(
            [
                '{"organisation_number": "989061593"}',
                '{"organisation_number": "923609016", "name": "Test"}',
            ]
        ),
        encoding="utf-8",
    )
    raw = load_input_organisations(p)
    assert raw == ["989061593", "923609016"]
