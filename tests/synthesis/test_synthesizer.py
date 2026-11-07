"""Regression tests for evidence-grounded profile synthesis."""

from app.output.models import AvailabilityState, Claim
from app.synthesis.synthesizer import Synthesizer


def _claim(field, value):
    return Claim(field=field, value=value, availability=AvailabilityState.AVAILABLE)


def test_missing_operating_result_does_not_crash_financial_summary():
    claims = [
        _claim("legal_name", "Example AS"),
        _claim("latest_revenue", 0),
        _claim("latest_operating_result", None),
        _claim("financial_currency", "NOK"),
        _claim("hiring_active", False),
    ]
    result = Synthesizer.synthesize_overview(claims, [])
    assert "0 NOK" in result["financial_summary"]
    assert "no operating-result figure was reported" in result["financial_summary"]
    assert "annual_accounts" not in result["explicit_unknowns"]


def test_unverified_hiring_is_not_reported_as_no_hiring():
    claims = [
        _claim("legal_name", "Example AS"),
        Claim(
            field="hiring_active",
            value=None,
            availability=AvailabilityState.NOT_AVAILABLE,
        ),
    ]
    result = Synthesizer.synthesize_overview(claims, [])
    assert "Hiring status not verified" in result["digital_summary"]
    assert "hiring_signals" in result["explicit_unknowns"]


def test_checked_no_hiring_is_distinguished_from_unverified():
    claims = [
        _claim("legal_name", "Example AS"),
        _claim("hiring_active", False),
    ]
    result = Synthesizer.synthesize_overview(claims, [])
    assert "No active hiring signal observed" in result["digital_summary"]
    assert "hiring_signals" not in result["explicit_unknowns"]
