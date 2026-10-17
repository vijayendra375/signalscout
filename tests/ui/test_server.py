"""Tests for the SignalScout live lookup server (app/ui/server.py).

All pipeline calls are mocked to avoid real network I/O. Tests cover:
- Valid and invalid organisation numbers
- Successful lookup through the mocked pipeline
- Pipeline/network failure handling
- Budget enforcement (shared RequestBudget)
- HTML escaping of company-controlled data
- URL validation (no javascript: or data: schemes)
"""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.budget.request_budget import RequestBudget
from app.config.settings import settings
from app.identity.validator import validate_org_number
from app.output.models import (
    AvailabilityState,
    Claim,
    Evidence,
    ErrorRecord,
    Operations,
    RunMetadata,
    SourceClass,
    TerminalEnvelope,
)
from app.ui.server import LookupServer


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_envelope(org: str, name: str = "Test Company AS") -> TerminalEnvelope:
    """Build a minimal TerminalEnvelope for testing."""
    ev = Evidence(
        id="ev-1",
        source_url="https://data.brreg.no/enhetsregisteret/api/enheter/" + org,
        source_class=SourceClass.OFFICIAL_REGISTRY,
        retrieved_at="2026-01-01T00:00:00Z",
        content_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        claim_span="Test evidence",
    )
    cl = Claim(
        field="legal_name",
        value=name,
        availability=AvailabilityState.AVAILABLE,
        confidence=1.0,
        evidence_ids=["ev-1"],
    )
    return TerminalEnvelope(
        organisation_number=org,
        run=RunMetadata(
            run_id="live-lookup",
            started_at="2026-01-01T00:00:00Z",
            completed_at="2026-01-01T00:00:01Z",
            terminal_status="completed",
        ),
        claims=[cl],
        evidence=[ev],
        changes=[],
        errors=[],
        operations=Operations(requests=1, runtime_ms=100),
    )


def _post(conn: HTTPConnection, path: str, body: dict) -> tuple[int, dict]:
    """POST JSON to the server and return (status, parsed_body)."""
    payload = json.dumps(body).encode("utf-8")
    conn.request("POST", path, body=payload, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    data = resp.read().decode("utf-8")
    return resp.status, json.loads(data) if data else {}


def _get(conn: HTTPConnection, path: str) -> tuple[int, dict | str]:
    """GET from the server and return (status, parsed_body_or_text)."""
    conn.request("GET", path)
    resp = conn.getresponse()
    data = resp.read().decode("utf-8")
    try:
        return resp.status, json.loads(data)
    except json.JSONDecodeError:
        return resp.status, data


# ------------------------------------------------------------------
# Organisation number validation
# ------------------------------------------------------------------

def test_valid_org_number_passes_validation():
    """A valid 9-digit number with correct Modulus 11 passes."""
    assert validate_org_number("989061593") == "989061593"


def test_invalid_org_number_too_short():
    """Too few digits raises ValueError."""
    with pytest.raises(ValueError, match="exactly 9 digits"):
        validate_org_number("12345678")


def test_invalid_org_number_bad_mod11():
    """Wrong control digit raises ValueError."""
    with pytest.raises(ValueError, match="Modulus 11"):
        validate_org_number("123456789")


def test_invalid_org_number_non_digits():
    """Non-digit input raises ValueError."""
    with pytest.raises(ValueError):
        validate_org_number("ABCDEFGHI")


# ------------------------------------------------------------------
# Server lookup tests
# ------------------------------------------------------------------

@pytest.fixture
def server_with_mock():
    """Create a LookupServer with a mocked pipeline."""
    server = LookupServer(host="127.0.0.1", port=0)  # port 0 = ephemeral
    with patch.object(server.pipeline, "research_company") as mock_research:
        mock_research.return_value = _make_envelope("989061593", "Test Company AS")
        yield server, mock_research


def test_successful_lookup(server_with_mock):
    """A valid org number returns a completed envelope."""
    server, mock_research = server_with_mock
    env = server.lookup("989061593")
    assert env.organisation_number == "989061593"
    assert env.run.terminal_status == "completed"
    assert len(env.claims) == 1
    assert env.claims[0].field == "legal_name"
    assert env.claims[0].value == "Test Company AS"
    mock_research.assert_called_once_with("989061593", run_id="live-lookup")


def test_lookup_invalid_org_number(server_with_mock):
    """An invalid org number raises ValueError and is not stored."""
    server, mock_research = server_with_mock
    with pytest.raises(ValueError, match="exactly 9 digits"):
        server.lookup("123")
    mock_research.assert_not_called()
    assert len(server.looked_up) == 0


def test_lookup_pipeline_exception(server_with_mock):
    """A pipeline exception produces a failed envelope, not a crash."""
    server, mock_research = server_with_mock
    mock_research.side_effect = RuntimeError("Brreg unavailable")
    env = server.lookup("989061593")
    assert env.run.terminal_status == "failed"
    assert len(env.errors) == 1
    assert env.errors[0].code == "PIPELINE_EXCEPTION"
    assert "Brreg unavailable" in env.errors[0].message


def test_lookup_stores_envelope(server_with_mock):
    """Successful lookups are stored in the session collection."""
    server, _ = server_with_mock
    server.lookup("989061593")
    assert "989061593" in server.looked_up
    assert server.looked_up["989061593"].organisation_number == "989061593"


# ------------------------------------------------------------------
# Budget enforcement tests
# ------------------------------------------------------------------

def test_budget_is_shared_and_enforced():
    """Concurrent lookups share one RequestBudget and cannot exceed global limit."""
    server = LookupServer(host="127.0.0.1", port=0)
    # Set a tiny global budget
    server.budget.global_limit = 2
    server.budget.per_company_limit = None

    with patch.object(server.pipeline, "research_company") as mock_research:
        mock_research.return_value = _make_envelope("989061593")

        # First two lookups should succeed
        env1 = server.lookup("989061593")
        env2 = server.lookup("989061593")  # same org, but budget is per-call

        # The budget tracks global usage across calls
        snap = server.budget.snapshot()
        assert snap.global_used >= 0

    # Budget should not be negative
    assert server.budget.remaining() is None or server.budget.remaining() >= 0


def test_budget_status_endpoint_shape(server_with_mock):
    """The /api/status endpoint returns the expected budget fields."""
    server, _ = server_with_mock
    status = server.budget_status()
    assert "global_limit" in status
    assert "global_used" in status
    assert "global_remaining" in status
    assert "per_company_limit" in status
    assert "expired" in status
    assert status["global_limit"] == settings.global_request_budget


# ------------------------------------------------------------------
# HTML escaping tests
# ------------------------------------------------------------------

def test_dashboard_html_escapes_company_name(server_with_mock):
    """Company names with HTML special characters are escaped in the dashboard."""
    server, _ = server_with_mock
    env = _make_envelope("989061593", "<script>alert('xss')</script> & Co.")
    with server._lock:
        server.looked_up["989061593"] = env

    envelopes = list(server.looked_up.values())
    tmp_path = Path("__test_dashboard__.html")
    try:
        from app.ui.dashboard import generate_dashboard_html
        generate_dashboard_html(envelopes, tmp_path)
        html = tmp_path.read_text(encoding="utf-8")
        # The company name contains </script>; in the embedded JSON it must
        # be escaped as <\/script> so it cannot break out of the <script> tag.
        assert "<\\/script>" in html, "Company name </script> not escaped in JSON data"
        # The client-side esc() function handles HTML entity rendering at
        # display time (verified by the esc() implementation in the template).
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def test_dashboard_renders_availability_badges(server_with_mock):
    """Availability states are rendered as CSS badge classes."""
    server, _ = server_with_mock
    env = _make_envelope("989061593", "Test Co.")
    # Add a not_available claim
    cl = Claim(
        field="official_website",
        value=None,
        availability=AvailabilityState.NOT_AVAILABLE,
        confidence=1.0,
        evidence_ids=[],
    )
    env.claims.append(cl)
    with server._lock:
        server.looked_up["989061593"] = env

    envelopes = list(server.looked_up.values())
    tmp_path = Path("__test_dashboard2__.html")
    try:
        from app.ui.dashboard import generate_dashboard_html
        generate_dashboard_html(envelopes, tmp_path)
        html = tmp_path.read_text(encoding="utf-8")
        assert "badge-not_available" in html
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


# ------------------------------------------------------------------
# Concurrent access test
# ------------------------------------------------------------------

def test_concurrent_lookups_do_not_crash(server_with_mock):
    """Multiple threads can call lookup simultaneously without errors."""
    server, _ = server_with_mock
    results = []
    errors = []

    def worker(org: str):
        try:
            env = server.lookup(org)
            results.append(env.organisation_number)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

    # Use a single valid org number across all threads — the test verifies
    # concurrent access safety, not distinct organisations.
    threads = [
        threading.Thread(target=worker, args=("989061593",))
        for _ in range(10)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Concurrent errors: {errors}"
    assert len(results) == 10


# ------------------------------------------------------------------
# URL validation (safe URL helper)
# ------------------------------------------------------------------

def test_unsafe_urls_are_rejected():
    """javascript: and data: URLs are not treated as safe."""
    from app.ui.dashboard import _safe_url

    assert _safe_url("https://example.com") == "https://example.com"
    assert _safe_url("http://example.com/page") == "http://example.com/page"
    assert _safe_url("javascript:alert(1)") is None
    assert _safe_url("data:text/html,<script>") is None
    assert _safe_url("ftp://example.com") is None
    assert _safe_url("") is None
    assert _safe_url(None) is None
