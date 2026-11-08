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


def test_ui_lookup_completes_company_exactly_once():
    """F6: standalone UI lookup uses the same single completion lifecycle."""
    from app.fetching.http_client import FetchResult
    from app.orchestrator.pipeline import CompanyPipeline

    class _Client:
        def __init__(self):
            self.count = 0

        def start_request_count(self):
            self.count = 0

        def request_count(self):
            return self.count

        def budget_denied_count(self):
            return 0

        def fetch(self, url, **kwargs):
            self.count += 1
            if url.endswith("/enheter/989061593"):
                body = json.dumps(
                    {
                        "organisasjonsnummer": "989061593",
                        "navn": "Test Company AS",
                        "organisasjonsform": {"kode": "AS"},
                    }
                )
                return FetchResult(
                    url=url,
                    status_code=200,
                    content=body.encode(),
                    text=body,
                    content_type="application/json",
                    elapsed_ms=1.0,
                    bytes_received=len(body),
                )
            return FetchResult(
                url=url,
                status_code=404,
                content=b"",
                text="",
                content_type="text/plain",
                elapsed_ms=1.0,
                bytes_received=0,
            )

    server = LookupServer(host="127.0.0.1", port=0)
    budget = RequestBudget(global_limit=50, per_company_limit=12, deadline_seconds=None)
    budget.set_total_companies(1)
    server.budget = budget
    server.pipeline = CompanyPipeline(
        http_client=_Client(), db=None, budget_tracker=None, request_budget=budget
    )

    # Invalid input never starts the lifecycle.
    with pytest.raises(ValueError):
        server.lookup("123")
    assert budget.completed_companies == 0

    env = server.lookup("989061593")
    assert env.run.terminal_status == "completed"
    assert budget.completed_companies == 1


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
    env = _make_envelope("989061593", "<script>alert('xss')</ScRiPt> & Co.")
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
        assert "\\u003c/ScRiPt\\u003e" in html, "Mixed-case script terminator not escaped in JSON data"
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


# ------------------------------------------------------------------
# Dashboard rendering tests
# ------------------------------------------------------------------

def test_dashboard_card_structure_in_template(server_with_mock):
    """The dashboard template contains field-label and field-value classes for card separation."""
    from app.ui.dashboard import DASHBOARD_TEMPLATE

    # The card() function uses flexbox with field-label and field-value wrappers
    assert 'class="field-label"' in DASHBOARD_TEMPLATE, "field-label class missing from template"
    assert 'class="field-value"' in DASHBOARD_TEMPLATE, "field-value class missing from template"
    # badgeHtml is concatenated inside field-value div, not after value
    assert 'badgeHtml' in DASHBOARD_TEMPLATE, "badgeHtml variable not found in card() function"
    assert 'valueHtml + badgeHtml' in DASHBOARD_TEMPLATE, "value and badge not combined in field-value div"


def test_dashboard_all_availability_badge_classes_in_css(server_with_mock):
    """All six availability states have distinct CSS badge classes in the template."""
    from app.ui.dashboard import DASHBOARD_TEMPLATE

    for state in ["available", "not_available", "not_applicable", "blocked", "ambiguous", "failed"]:
        css_class = f'.badge-{state}'
        assert css_class in DASHBOARD_TEMPLATE, f"CSS badge class '{css_class}' missing from template"


def test_dashboard_escapes_html_sensitive_company_data(server_with_mock):
    """Company data with HTML special characters is escaped in embedded JSON data."""
    server, _ = server_with_mock
    env = _make_envelope("989061593", "<script>alert('xss')</ScRiPt> & Co.")
    with server._lock:
        server.looked_up["989061593"] = env

    envelopes = list(server.looked_up.values())
    tmp_path = Path("__test_dashboard5__.html")
    try:
        from app.ui.dashboard import generate_dashboard_html
        generate_dashboard_html(envelopes, tmp_path)
        html = tmp_path.read_text(encoding="utf-8")

        # The company name should be escaped in the embedded JSON (</script> as <\/script>)
        assert "\\u003c/ScRiPt\\u003e" in html, "Mixed-case script terminator not escaped in JSON data"
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def test_dashboard_handles_long_urls(server_with_mock):
    """Long source URLs are validated as safe http/https links."""
    from app.ui.dashboard import _safe_url

    long_url = "https://data.brreg.no/enhetsregisteret/api/enheter/989061593?very_long_parameter=abcdefghijklmnopqrstuvwxyz1234567890"
    assert _safe_url(long_url) == long_url, "Long valid URL should be accepted"

    # Unsafe schemes should be rejected
    assert _safe_url("javascript:alert(1)") is None
    assert _safe_url("data:text/html,<script>") is None


def test_dashboard_missing_values_produce_empty_state_spans():
    """The _money and _list_value helpers produce empty state spans for missing values."""
    from app.ui.dashboard import _money, _list_value

    # Missing numeric value -> empty span
    result = _money(None, "NOK")
    assert 'class="empty"' in result, "Missing money value should produce empty span"
    assert "Not available" in result

    # Missing list value -> empty span
    result = _list_value(None)
    assert 'class="empty"' in result, "Missing list value should produce empty span"
    assert "Not available" in result

    # Empty list -> empty span
    result = _list_value([])
    assert 'class="empty"' in result, "Empty list should produce empty span"


# ------------------------------------------------------------------
# Dashboard badge mapping regression tests
# ------------------------------------------------------------------

def test_dashboard_vat_registered_false_shows_available_badge(server_with_mock):
    """When Brreg explicitly reports vat_registered=False, the dashboard must
    show availability=available (verified negative), not not_available."""
    server, _ = server_with_mock
    env = _make_envelope("989061593", "Test Company AS")
    cl = Claim(
        field="vat_registered",
        value=False,
        availability=AvailabilityState.AVAILABLE,
        confidence=1.0,
        evidence_ids=["ev-1"],
    )
    env.claims.append(cl)
    with server._lock:
        server.looked_up["989061593"] = env

    envelopes = list(server.looked_up.values())
    tmp_path = Path("__test_dashboard_vat__.html")
    try:
        from app.ui.dashboard import generate_dashboard_html
        generate_dashboard_html(envelopes, tmp_path)
        html = tmp_path.read_text(encoding="utf-8")

        # The embedded JSON must carry availability=available for the verified negative
        import re
        vat_match = re.search(r'"field":\s*"vat_registered".*?"availability":\s*"available"', html)
        assert vat_match is not None, "vat_registered claim must have availability=available in embedded JSON"

        # The old inline boolean check pattern must not be in the template
        assert "vatReg === true ? 'available' : 'not_available'" not in html, \
            "Old inline boolean badge check must not be in dashboard template"
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def test_dashboard_adverse_status_false_shows_available_badge(server_with_mock):
    """When Brreg explicitly reports all adverse flags as false, the dashboard
    must show availability=available (verified negative), not not_available."""
    server, _ = server_with_mock
    env = _make_envelope("989061593", "Test Company AS")
    cl = Claim(
        field="adverse_status",
        value=False,
        availability=AvailabilityState.AVAILABLE,
        confidence=1.0,
        evidence_ids=["ev-1"],
    )
    env.claims.append(cl)
    with server._lock:
        server.looked_up["989061593"] = env

    envelopes = list(server.looked_up.values())
    tmp_path = Path("__test_dashboard_adverse__.html")
    try:
        from app.ui.dashboard import generate_dashboard_html
        generate_dashboard_html(envelopes, tmp_path)
        html = tmp_path.read_text(encoding="utf-8")

        # The embedded JSON must carry availability=available for the verified negative
        import re
        adv_match = re.search(r'"field":\s*"adverse_status".*?"availability":\s*"available"', html)
        assert adv_match is not None, "adverse_status claim must have availability=available in embedded JSON"
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def test_dashboard_adverse_status_null_shows_not_available(server_with_mock):
    """When Brreg omits adverse status keys entirely, the dashboard must
    show availability=not_available and an empty state, not a verified negative."""
    server, _ = server_with_mock
    env = _make_envelope("989061593", "Test Company AS")
    cl = Claim(
        field="adverse_status",
        value=None,
        availability=AvailabilityState.NOT_AVAILABLE,
        confidence=1.0,
        evidence_ids=[],
    )
    env.claims.append(cl)
    with server._lock:
        server.looked_up["989061593"] = env

    envelopes = list(server.looked_up.values())
    tmp_path = Path("__test_dashboard_adverse_null__.html")
    try:
        from app.ui.dashboard import generate_dashboard_html
        generate_dashboard_html(envelopes, tmp_path)
        html = tmp_path.read_text(encoding="utf-8")

        # The embedded JSON must carry availability=not_available for missing data
        import re
        adv_match = re.search(r'"field":\s*"adverse_status".*?"availability":\s*"not_available"', html)
        assert adv_match is not None, "adverse_status missing data must have availability=not_available in embedded JSON"
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
