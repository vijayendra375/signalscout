"""Unit tests for SafeHttpClient resilience and SSRF protection."""

import pytest
from app.fetching.http_client import SafeHttpClient, is_safe_ip, validate_url_safety, SecurityException


def test_is_safe_ip_public_and_private():
    # Public IP
    assert is_safe_ip("8.8.8.8") is True
    assert is_safe_ip("1.1.1.1") is True
    assert is_safe_ip("146.247.168.10") is True

    # Private and loopback IPs
    assert is_safe_ip("127.0.0.1") is False
    assert is_safe_ip("10.0.0.1") is False
    assert is_safe_ip("192.168.1.1") is False
    assert is_safe_ip("172.16.0.1") is False
    assert is_safe_ip("169.254.169.254") is False  # AWS/GCP metadata


def test_ssrf_blocking_in_url_validation():
    with pytest.raises(SecurityException):
        validate_url_safety("http://127.0.0.1:8080/admin")

    with pytest.raises(SecurityException):
        validate_url_safety("http://localhost:8000")

    with pytest.raises(SecurityException):
        validate_url_safety("http://169.254.169.254/latest/meta-data")


def test_client_blocks_ssrf_gracefully():
    client = SafeHttpClient()
    res = client.fetch("http://127.0.0.1:8080/secret")
    assert res.status_code == 403
    assert "SSRF Blocked" in res.error
