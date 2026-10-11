"""Unit tests for the Identity Firewall."""

from app.identity.firewall import (
    IdentityDecision,
    IdentityFirewall,
    normalize_text_for_comparison,
)


def test_normalize_text_for_comparison():
    assert normalize_text_for_comparison("EQUINOR ASA") == "equinor"
    assert normalize_text_for_comparison("Statkraft Energi AS") == "statkraft energi"
    assert normalize_text_for_comparison("Telenor Norge AS") == "telenor"


def test_firewall_exact_org_number_matches():
    assessment = IdentityFirewall.evaluate_website_evidence(
        target_org="923609016",
        target_legal_name="Equinor ASA",
        official_domain="equinor.com",
        page_url="https://www.equinor.com/about",
        page_text="Welcome to Equinor. Organisation number: 923609016. All rights reserved.",
    )
    assert assessment.decision == IdentityDecision.TRUSTED
    assert assessment.confidence >= 0.95
    assert assessment.matched_org_number is True


def test_firewall_conflicting_org_number_rejected():
    # Page lists a different company's org number (e.g. parent or competitor)
    assessment = IdentityFirewall.evaluate_website_evidence(
        target_org="923609016",
        target_legal_name="Equinor ASA",
        official_domain="equinor.com",
        page_url="https://www.example.no",
        page_text="Copyright 2026 Other Company AS. Org nr: 984851006.",
    )
    assert assessment.decision == IdentityDecision.REJECTED
    assert assessment.confidence == 0.0
    assert "conflicting organisation number" in assessment.rejection_reason.lower()


def test_firewall_domain_and_name_match():
    assessment = IdentityFirewall.evaluate_website_evidence(
        target_org="923609016",
        target_legal_name="Equinor ASA",
        official_domain="https://www.equinor.com",
        page_url="https://www.equinor.com/en",
        page_text="Equinor is an international energy company committed to creating long-term value.",
    )
    assert assessment.decision == IdentityDecision.TRUSTED
    assert assessment.matched_domain is True
    assert assessment.matched_legal_name is True


def test_firewall_ambiguous_quarantined():
    # Only domain matched, but text has no matching company name
    assessment = IdentityFirewall.evaluate_website_evidence(
        target_org="923609016",
        target_legal_name="Equinor ASA",
        official_domain="https://www.equinor.com",
        page_url="https://www.equinor.com/blank",
        page_text="Maintenance page. Please check back later.",
    )
    assert assessment.decision == IdentityDecision.QUARANTINED
    assert assessment.confidence < 0.90


def test_role_identity_evaluation():
    official_roles = ["Anders Opedal", "Jon Erik Reinhardsen"]
    assert IdentityFirewall.evaluate_role_identity("Anders Opedal", official_roles) is True
    assert IdentityFirewall.evaluate_role_identity("Opedal, Anders", official_roles) is True
    assert IdentityFirewall.evaluate_role_identity("John Doe", official_roles) is False
