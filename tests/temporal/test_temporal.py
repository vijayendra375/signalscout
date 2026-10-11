"""Unit tests for temporal change detection and idempotent replay."""

from app.output.models import AvailabilityState, Claim
from app.temporal.change_detector import ChangeDetector


def test_idempotent_replay_zero_changes():
    prior_claims = {
        "legal_name": "EQUINOR ASA",
        "latest_revenue": 1000000000.0,
        "managing_director": "Anders Opedal",
    }
    current_claims = [
        Claim(field="legal_name", value="EQUINOR ASA", availability=AvailabilityState.AVAILABLE),
        Claim(field="latest_revenue", value=1000000000.0, availability=AvailabilityState.AVAILABLE),
        Claim(field="managing_director", value="Anders Opedal", availability=AvailabilityState.AVAILABLE),
    ]
    changes = ChangeDetector.detect_changes(prior_claims, current_claims)
    assert len(changes) == 0  # Zero false changes!


def test_detect_material_financial_change():
    prior_claims = {
        "latest_revenue": 1000000000.0,
        "managing_director": "Anders Opedal",
    }
    current_claims = [
        Claim(field="latest_revenue", value=1200000000.0, availability=AvailabilityState.AVAILABLE),
        Claim(field="managing_director", value="Anders Opedal", availability=AvailabilityState.AVAILABLE),
    ]
    changes = ChangeDetector.detect_changes(prior_claims, current_claims)
    assert len(changes) == 1
    assert changes[0].field == "latest_revenue"
    assert changes[0].old_value == 1000000000.0
    assert changes[0].new_value == 1200000000.0
    assert changes[0].materiality == "material_financial"


def test_detect_leadership_transition():
    prior_claims = {
        "managing_director": "Old CEO Name",
    }
    current_claims = [
        Claim(field="managing_director", value="New CEO Name", availability=AvailabilityState.AVAILABLE),
    ]
    changes = ChangeDetector.detect_changes(prior_claims, current_claims)
    assert len(changes) == 1
    assert changes[0].field == "managing_director"
    assert changes[0].old_value == "Old CEO Name"
    assert changes[0].new_value == "New CEO Name"
    assert changes[0].materiality == "leadership_transition"
