"""Temporal change detection: idempotency and the missing-data rule."""

from app.output.models import AvailabilityState, Claim
from app.temporal.change_detector import ChangeDetector


def test_missing_data_is_not_a_change():
    # Prior run observed a revenue; this run the source was unavailable.
    # Absence of evidence must NOT be reported as a change.
    prior = {"latest_revenue": 1000.0}
    current = [Claim(field="latest_revenue", value=None, availability=AvailabilityState.NOT_AVAILABLE)]
    assert ChangeDetector.detect_changes(prior, current) == []


def test_blocked_source_is_not_a_change():
    prior = {"managing_director": "Jane Doe"}
    current = [Claim(field="managing_director", value=None, availability=AvailabilityState.BLOCKED)]
    assert ChangeDetector.detect_changes(prior, current) == []


def test_ambiguous_source_is_not_a_change():
    prior = {"official_website": "https://a.no"}
    current = [Claim(field="official_website", value="https://a.no", availability=AvailabilityState.AMBIGUOUS)]
    assert ChangeDetector.detect_changes(prior, current) == []


def test_idempotent_when_values_identical():
    prior = {"legal_name": "COMPANY AS", "latest_revenue": 5.0}
    current = [
        Claim(field="legal_name", value="COMPANY AS", availability=AvailabilityState.AVAILABLE),
        Claim(field="latest_revenue", value=5.0, availability=AvailabilityState.AVAILABLE),
    ]
    assert ChangeDetector.detect_changes(prior, current) == []


def test_real_change_is_detected_once():
    prior = {"latest_revenue": 1000.0}
    current = [Claim(field="latest_revenue", value=2000.0, availability=AvailabilityState.AVAILABLE)]
    changes = ChangeDetector.detect_changes(prior, current)
    assert len(changes) == 1
    assert changes[0].materiality == "material_financial"
