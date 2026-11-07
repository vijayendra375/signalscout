"""Unit tests for Norwegian organisation number validation."""

import pytest
from app.identity.validator import is_valid_mod11, normalize_org_number, validate_org_number


def test_normalize_org_number():
    assert normalize_org_number("NO 923 609 016 MVA") == "923609016"
    assert normalize_org_number("923609016") == "923609016"
    assert normalize_org_number(923609016) == "923609016"
    assert normalize_org_number(None) == ""
    assert normalize_org_number("abc") == ""


def test_is_valid_mod11_valid_orgs():
    # Equinor ASA
    assert is_valid_mod11("923609016") is True
    # Known valid org from test fixtures
    assert is_valid_mod11("993578843") is True
    # DNB Bank ASA
    assert is_valid_mod11("984851006") is True


def test_is_valid_mod11_invalid_checksum():
    # Wrong control digit
    assert is_valid_mod11("923609017") is False
    assert is_valid_mod11("993578844") is False


def test_is_valid_mod11_invalid_length():
    assert is_valid_mod11("12345678") is False
    assert is_valid_mod11("1234567890") is False
    assert is_valid_mod11("") is False


def test_validate_org_number_success():
    assert validate_org_number("923609016") == "923609016"
    assert validate_org_number("NO 923 609 016 MVA") == "923609016"


def test_validate_org_number_failure():
    with pytest.raises(ValueError):
        validate_org_number("12345")
        
    with pytest.raises(ValueError):
        validate_org_number("923609017")  # invalid checksum

    with pytest.raises(ValueError):
        validate_org_number("000000000")  # literal placeholder is not an identity

    with pytest.raises(ValueError):
        validate_org_number("not-an-org")
