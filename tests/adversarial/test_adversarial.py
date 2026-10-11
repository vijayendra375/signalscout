"""Adversarial tests: edge cases, deceptive domains, parent/subsidiary confusion."""

import pytest
from app.identity.firewall import IdentityDecision, IdentityFirewall
from app.identity.validator import is_valid_mod11, validate_org_number
from app.extraction.financials import extract_financials
from app.fetching.http_client import SafeHttpClient


def test_adversarial_similar_company_different_org():
    # Two companies with similar names: Target is Equinor ASA (923609016)
    # Competitor or unrelated firm mentions "Equinor" but has a different org number
    assessment = IdentityFirewall.evaluate_website_evidence(
        target_org="923609016",
        target_legal_name="Equinor ASA",
        official_domain="equinor.com",
        page_url="https://fake-equinor.no",
        page_text="Equinor Partner AS. Org nr: 993578843. Not the principal ASA.",
    )
    # The firewall must reject because the conflicting org number 993578843 contradicts 923609016
    assert assessment.decision == IdentityDecision.REJECTED


def test_adversarial_malformed_checksums():
    # 9-digit numbers that look real but have altered control digits
    invalid_orgs = [
        "123456789",
        "923609010",
        "923609011",
        "923609012",
        "923609013",
        "923609014",
        "923609015",
    ]
    for org in invalid_orgs:
        assert is_valid_mod11(org) is False
        with pytest.raises(ValueError):
            validate_org_number(org)


def test_adversarial_missing_financial_statement():
    # Empty statement response must not generate zeroes
    claims = extract_financials([], "ev-empty")
    for claim in claims:
        # Check that none of the numeric fields became 0 or 0.0
        if "revenue" in claim.field or "result" in claim.field or "assets" in claim.field:
            assert claim.value is None


def test_adversarial_ssrf_attacks():
    client = SafeHttpClient()
    attack_urls = [
        "http://127.0.0.1/",
        "http://localhost:8080/",
        "http://169.254.169.254/computeMetadata/v1/",
        "http://10.0.0.5/internal-api",
        "http://192.168.1.100/",
    ]
    for u in attack_urls:
        res = client.fetch(u)
        assert res.status_code == 403
        assert "SSRF Blocked" in res.error
