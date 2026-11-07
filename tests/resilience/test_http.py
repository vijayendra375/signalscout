"""Unit tests for SafeHttpClient resilience and SSRF protection."""

import socket
import ssl as _ssl
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from app.budget.tracker import BudgetTracker
from app.fetching.http_client import (
    FetchResult,
    SafeHttpClient,
    SecurityException,
    _PinnedHTTPConnection,
    _PinnedHTTPSConnection,
    _pin_connection,
    is_safe_ip,
    resolve_public_ip,
    validate_url_safety,
)


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


def test_fetch_returns_result_after_retry_exhaustion(monkeypatch):
    """F1: exhausted retries must still return a FetchResult, never None."""
    import requests
    from app.fetching import http_client as hc

    calls = {"n": 0}

    def boom(self, *args, **kwargs):
        calls["n"] += 1
        raise requests.ConnectionError("simulated network failure")

    monkeypatch.setattr(hc, "validate_url_safety", lambda url: None)
    monkeypatch.setattr(hc.time, "sleep", lambda *_: None)
    monkeypatch.setattr(requests.Session, "get", boom)

    client = SafeHttpClient()
    res = client.fetch("https://example.com/", max_retries=2)

    assert isinstance(res, FetchResult)
    assert res.status_code == 500
    assert res.error and "simulated network failure" in res.error
    assert calls["n"] == 3  # initial attempt + 2 retries


def test_fetch_does_not_hide_programming_errors(monkeypatch):
    """F7: AssertionError and other programming errors must propagate."""
    import requests
    from app.fetching import http_client as hc

    def boom(self, *args, **kwargs):
        raise AssertionError("programming bug")

    monkeypatch.setattr(hc, "validate_url_safety", lambda url: None)
    monkeypatch.setattr(hc.time, "sleep", lambda *_: None)
    monkeypatch.setattr(requests.Session, "get", boom)

    with pytest.raises(AssertionError, match="programming bug"):
        SafeHttpClient().fetch("https://example.com/", max_retries=1)


def test_fetch_returns_result_on_expected_validation_error(monkeypatch):
    """F7: expected DNS/validation failures are ordinary results, not crashes."""
    from app.fetching import http_client as hc

    def broken_validate(url):
        raise socket.gaierror("dns lookup failed")

    monkeypatch.setattr(hc, "validate_url_safety", broken_validate)

    res = SafeHttpClient().fetch("https://example.com/")

    assert isinstance(res, FetchResult)
    assert res.status_code == 400
    assert res.error and "URL validation failed" in res.error


def test_fetch_does_not_hide_unexpected_validation_errors(monkeypatch):
    from app.fetching import http_client as hc

    def broken_validate(url):
        raise RuntimeError("unexpected validation bug")

    monkeypatch.setattr(hc, "validate_url_safety", broken_validate)

    with pytest.raises(RuntimeError, match="unexpected validation bug"):
        SafeHttpClient().fetch("https://example.com/")


def _dns_answer(*ips):
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))
        for ip in ips
    ]


def test_dns_validation_fails_closed_for_unresolved_hosts(monkeypatch):
    def no_answer(host, port):
        raise socket.gaierror("name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", no_answer)

    with pytest.raises(SecurityException, match="DNS resolution failed"):
        resolve_public_ip("does-not-exist.example")

    res = SafeHttpClient().fetch("https://does-not-exist.example/")
    assert res.status_code == 403
    assert "SSRF Blocked" in (res.error or "")


def test_dns_validation_rejects_mixed_public_and_private_answers(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port: _dns_answer("8.8.8.8", "127.0.0.1"),
    )

    with pytest.raises(SecurityException, match="127.0.0.1"):
        resolve_public_ip("mixed.example")

    res = SafeHttpClient().fetch("https://mixed.example/")
    assert res.status_code == 403


def test_dns_validation_rejects_loopback_and_metadata_destinations(monkeypatch):
    for ip in ("127.0.0.1", "169.254.169.254", "10.0.0.1"):
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda host, port, ip=ip: _dns_answer(ip),
        )
        with pytest.raises(SecurityException):
            resolve_public_ip("unsafe.example")


def test_changing_dns_answers_are_rechecked_and_fail_closed(monkeypatch):
    answers = iter([_dns_answer("8.8.8.8"), _dns_answer("127.0.0.1")])
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port: next(answers))

    assert resolve_public_ip("changing.example") == "8.8.8.8"
    with pytest.raises(SecurityException):
        resolve_public_ip("changing.example")


def test_connection_uses_validated_pinned_ip_without_second_dns_lookup(monkeypatch):
    """F2: the socket address must be the IP that passed validation."""
    import urllib3.util.connection as urllib3_connection

    calls = []

    def fake_create_connection(address, *args, **kwargs):
        calls.append(address)
        return object()

    def must_not_resolve(*args, **kwargs):
        raise AssertionError("connection attempted a second DNS lookup")

    monkeypatch.setattr(urllib3_connection, "create_connection", fake_create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", must_not_resolve)

    with _pin_connection("93.184.216.34"):
        conn = _PinnedHTTPConnection("example.com", 80)
        conn._new_conn()

    assert calls == [("93.184.216.34", 80)]
    assert conn._dns_host == "example.com"


def test_https_connection_pin_keeps_tls_hostname(monkeypatch):
    import urllib3.util.connection as urllib3_connection

    def fake_create_connection(address, *args, **kwargs):
        return object()

    monkeypatch.setattr(urllib3_connection, "create_connection", fake_create_connection)

    with _pin_connection("93.184.216.34"):
        conn = _PinnedHTTPSConnection("secure.example", 443)
        conn._new_conn()

    # tls SNI / certificate verification still use the original hostname.
    assert conn._dns_host == "secure.example"


class _FakeResponse:
    def __init__(self, url, status=200, location=None, body=b"ok"):
        self.url = url
        self.status_code = status
        self.headers = {}
        if location is not None:
            self.headers["Location"] = location
        self.encoding = "utf-8"
        self._body = body

    @property
    def is_redirect(self):
        return self.status_code in {301, 302, 303, 307, 308} and "Location" in self.headers

    def iter_content(self, chunk_size=16384):
        yield self._body

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_redirect_stub(monkeypatch, mapping, requested, unsafe_prefix=None):
    import requests
    from app.fetching import http_client as hc

    def fake_validate(url):
        if unsafe_prefix and unsafe_prefix in url:
            raise SecurityException("unsafe destination")
        return None

    def fake_get(self, url, **kwargs):
        requested.append(url)
        return mapping[url]

    monkeypatch.setattr(hc, "validate_url_safety", fake_validate)
    monkeypatch.setattr(SafeHttpClient, "_throttle", lambda self, url: None)
    monkeypatch.setattr(requests.Session, "get", fake_get)


def test_redirect_relative_location_is_resolved(monkeypatch):
    """F4: relative Location headers must be resolved against the response URL."""
    requested = []
    mapping = {
        "https://example.com/a": _FakeResponse("https://example.com/a", 302, "/b"),
        "https://example.com/b": _FakeResponse("https://example.com/b", 200, body=b"done"),
    }
    _install_redirect_stub(monkeypatch, mapping, requested)

    res = SafeHttpClient().fetch("https://example.com/a", max_retries=0)

    assert res.status_code == 200
    assert res.text == "done"
    assert res.redirect_hops == 1
    assert requested == ["https://example.com/a", "https://example.com/b"]


def test_redirect_to_unsafe_destination_is_not_followed(monkeypatch):
    """F4: a redirect to a private/metadata address must not be requested."""
    requested = []
    mapping = {
        "https://example.com/a": _FakeResponse(
            "https://example.com/a", 302, "http://169.254.169.254/latest/meta-data"
        ),
    }
    _install_redirect_stub(
        monkeypatch, mapping, requested, unsafe_prefix="169.254.169.254"
    )

    res = SafeHttpClient().fetch("https://example.com/a", max_retries=0)

    assert "169.254.169.254" not in requested
    assert res.status_code == 302
    assert res.error and "SSRF Blocked: unsafe redirect destination" in res.error


def test_redirect_loop_is_detected(monkeypatch):
    """F4: redirect loops stop instead of following forever."""
    requested = []
    mapping = {
        "https://example.com/a": _FakeResponse("https://example.com/a", 302, "/b"),
        "https://example.com/b": _FakeResponse("https://example.com/b", 302, "/a"),
    }
    _install_redirect_stub(monkeypatch, mapping, requested)

    res = SafeHttpClient().fetch("https://example.com/a", max_retries=0)

    assert res.error == "Redirect loop detected"
    assert requested == ["https://example.com/a", "https://example.com/b"]


def test_redirect_budget_exhaustion_is_exposed(monkeypatch):
    """F4: budget exhausted on a redirect hop must set blocked_by_budget=True."""
    from app.budget.request_budget import RequestBudget

    requested = []
    mapping = {
        "https://example.com/a": _FakeResponse("https://example.com/a", 302, "/b"),
    }
    _install_redirect_stub(monkeypatch, mapping, requested)

    budget = RequestBudget(global_limit=1, per_company_limit=None, deadline_seconds=None)
    res = SafeHttpClient(request_budget=budget).fetch("https://example.com/a", max_retries=0)

    assert res.blocked_by_budget is True
    assert res.status_code == 302
    assert res.error == "REQUEST_BUDGET_EXHAUSTED"
    assert requested == ["https://example.com/a"]


def test_tracker_records_every_redirect_hop_once(monkeypatch):
    """F8: tracker totals and per-domain counts match actual redirect requests."""
    tracker = BudgetTracker()
    requested = []
    mapping = {
        "https://a.example/start": _FakeResponse(
            "https://a.example/start", 302, "https://b.example/next"
        ),
        "https://b.example/next": _FakeResponse(
            "https://b.example/next", 302, "/final"
        ),
        "https://b.example/final": _FakeResponse(
            "https://b.example/final", 200, body=b"done"
        ),
    }
    _install_redirect_stub(monkeypatch, mapping, requested)

    client = SafeHttpClient(budget_tracker=tracker)
    res = client.fetch("https://a.example/start", max_retries=0)

    assert res.status_code == 200
    assert requested == [
        "https://a.example/start",
        "https://b.example/next",
        "https://b.example/final",
    ]
    assert tracker.total_requests == 3
    assert tracker.domain_counts == {"a.example": 1, "b.example": 2}
    assert tracker.total_bytes == 4
    assert client.request_count() == tracker.total_requests


def test_tracker_records_denied_redirect_only_once(monkeypatch):
    """F8: a denied hop is never recorded as an outbound request."""
    from app.budget.request_budget import RequestBudget

    tracker = BudgetTracker()
    requested = []
    mapping = {
        "https://example.com/a": _FakeResponse("https://example.com/a", 302, "/b"),
    }
    _install_redirect_stub(monkeypatch, mapping, requested)

    budget = RequestBudget(global_limit=1, per_company_limit=None, deadline_seconds=None)
    client = SafeHttpClient(budget_tracker=tracker, request_budget=budget)
    res = client.fetch("https://example.com/a", max_retries=0)

    assert res.blocked_by_budget is True
    assert requested == ["https://example.com/a"]
    assert tracker.total_requests == 1
    assert tracker.domain_counts == {"example.com": 1}
    assert client.request_count() == 1


def test_tracker_records_retries_and_destination_domains(monkeypatch):
    """F8: retries are counted exactly once and use the attempted destination."""
    import requests
    from app.fetching import http_client as hc

    tracker = BudgetTracker()
    calls = []

    def fake_get(self, url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise requests.ConnectionError("transient")
        if len(calls) == 2:
            return _FakeResponse("https://a.example/start", 302, "https://b.example/ok")
        return _FakeResponse("https://b.example/ok", 200, body=b"ok")

    monkeypatch.setattr(hc, "validate_url_safety", lambda url: None)
    monkeypatch.setattr(SafeHttpClient, "_throttle", lambda self, url: None)
    monkeypatch.setattr(hc.time, "sleep", lambda *_: None)
    monkeypatch.setattr(requests.Session, "get", fake_get)

    client = SafeHttpClient(budget_tracker=tracker)
    res = client.fetch("https://a.example/start", max_retries=1)

    assert res.status_code == 200
    assert calls == [
        "https://a.example/start",
        "https://a.example/start",
        "https://b.example/ok",
    ]
    assert tracker.total_requests == 3
    assert tracker.domain_counts == {"a.example": 2, "b.example": 1}
    assert tracker.errors_count == 1
    assert client.request_count() == tracker.total_requests


# ---------------------------------------------------------------------------
# Finding 1: proxy-based SSRF bypass
# ---------------------------------------------------------------------------

_CERTDATA = os.path.join(os.path.dirname(_ssl.__file__), "test", "certdata")
_KEYCERT = os.path.join(_CERTDATA, "keycert.pem")        # self-signed cert+key for "localhost"
_KEYCERT2 = os.path.join(_CERTDATA, "keycert2.pem")      # self-signed cert+key for "fakehostname"


class _SilentHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):  # noqa: N802
        pass


def _start_https_server(certfile: str):
    ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SilentHandler)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def test_session_disables_environment_proxy_inheritance(monkeypatch):
    """F1: HTTP_PROXY/HTTPS_PROXY/ALL_PROXY (any case) must never be inherited."""
    for var in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    ):
        monkeypatch.setenv(var, "http://evil.proxy:8080")

    client = SafeHttpClient()
    sess = client.session
    # Disabling trust_env is the control that stops environment proxy inheritance.
    assert sess.trust_env is False
    assert sess.proxies == {}


def test_proxy_adapter_send_raises_instead_of_fallback():
    """F1: an explicit proxy must be refused, never routed through the base adapter."""
    import requests

    from app.fetching.http_client import _PinnedHTTPAdapter

    adapter = _PinnedHTTPAdapter()
    prepared = requests.Request("GET", "http://example.com/").prepare()
    with pytest.raises(SecurityException, match="Proxy configuration is not allowed"):
        adapter.send(prepared, proxies={"http": "http://evil.proxy:8080"})


def test_configured_session_proxy_is_refused_fail_closed(monkeypatch):
    """F1: a session-level proxy makes fetch fail closed (403), never bypass pinning."""
    from app.fetching import http_client as hc

    monkeypatch.setattr(hc, "validate_url_safety", lambda url: "93.184.216.34")
    client = SafeHttpClient()
    client.session.proxies = {
        "http": "http://evil.proxy:8080",
        "https": "http://evil.proxy:8080",
    }
    res = client.fetch("http://example.com/", max_retries=0)
    assert res.status_code == 403
    assert "Proxy configuration is not allowed" in (res.error or "")


def test_per_request_proxy_is_refused():
    """F1: a per-request proxy is refused by the adapter."""
    client = SafeHttpClient()
    with pytest.raises(SecurityException, match="Proxy configuration is not allowed"):
        client.session.get("http://example.com/", proxies={"http": "http://evil.proxy:8080"})


def test_local_https_handshake_uses_pinned_ip_and_original_hostname(monkeypatch):
    """F1: a pinned HTTPS connection performs a real TLS handshake to the pinned IP
    while using the original hostname for SNI / certificate verification."""
    import urllib3.util.connection as u3conn

    server, port = _start_https_server(_KEYCERT)
    try:
        ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_verify_locations(_KEYCERT)
        ctx.check_hostname = True
        ctx.verify_mode = _ssl.CERT_REQUIRED

        recorded: list = []
        real_create = u3conn.create_connection

        def fake_create(address, *args, **kwargs):
            recorded.append(address)
            # Redirect the socket to the local test server regardless of the
            # pinned IP, proving the address passed to create_connection is the
            # validated pinned IP rather than a DNS-resolved address.
            return real_create(("127.0.0.1", port), *args, **kwargs)

        monkeypatch.setattr(u3conn, "create_connection", fake_create)

        with _pin_connection("93.184.216.34"):
            conn = _PinnedHTTPSConnection("localhost", port, ssl_context=ctx)
            conn.connect()
            conn.close()

        # The socket was directed at the validated pinned IP.
        assert recorded == [("93.184.216.34", port)]
        # _dns_host is restored before TLS, so SNI/cert verification use the
        # original hostname ("localhost"), not the pinned IP.
        assert conn._dns_host == "localhost"
    finally:
        server.shutdown()
        server.server_close()


def test_local_https_hostname_verification_rejects_mismatched_cert(monkeypatch):
    """F1: hostname verification is active and uses the original hostname."""
    import urllib3.util.connection as u3conn

    server, port = _start_https_server(_KEYCERT2)  # certificate for "fakehostname"
    try:
        ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_verify_locations(_KEYCERT)  # trusts "localhost", not "fakehostname"
        ctx.check_hostname = True
        ctx.verify_mode = _ssl.CERT_REQUIRED

        recorded: list = []
        real_create = u3conn.create_connection

        def fake_create(address, *args, **kwargs):
            recorded.append(address)
            return real_create(("127.0.0.1", port), *args, **kwargs)

        monkeypatch.setattr(u3conn, "create_connection", fake_create)

        with _pin_connection("93.184.216.34"):
            conn = _PinnedHTTPSConnection("localhost", port, ssl_context=ctx)
            with pytest.raises(_ssl.SSLError):
                conn.connect()

        # Connection was still directed at the pinned IP; verification rejected it.
        assert recorded == [("93.184.216.34", port)]
    finally:
        server.shutdown()
        server.server_close()


def test_pin_is_scoped_per_request_no_stale_pin():
    """F1: the validated-IP pin is cleared after each request so it cannot leak
    into a connection for a different host (connection-pool reuse safety)."""
    from app.fetching.http_client import _PIN_LOCAL

    if hasattr(_PIN_LOCAL, "ip"):
        del _PIN_LOCAL.ip
    with _pin_connection("1.1.1.1"):
        assert getattr(_PIN_LOCAL, "ip") == "1.1.1.1"
    assert not hasattr(_PIN_LOCAL, "ip"), "pin must not leak between requests"
