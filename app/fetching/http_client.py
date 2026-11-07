"""Safe HTTP client with SSRF defense, bounded memory, retries, and latency tracking."""

from __future__ import annotations

import ipaddress
import random
import socket
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional
from urllib.parse import urljoin, urlparse

import requests
import urllib3
from requests.adapters import DEFAULT_POOLBLOCK, HTTPAdapter
from urllib3 import connection as urllib3_connection
from urllib3 import connectionpool as urllib3_connectionpool

from app.config.settings import settings


# Hard upper bound on redirect hops followed for a single fetch.
MAX_REDIRECTS = 10

# The validated IP is carried in thread-local state from the policy check to the
# connection that actually opens the socket. This closes the DNS-rebinding gap:
# urllib3 never performs a second, independent DNS lookup for a pinned request.
_PIN_LOCAL = threading.local()
_UNSET = object()


@dataclass
class FetchResult:
    url: str
    status_code: int
    content: bytes
    text: str
    content_type: str
    elapsed_ms: float
    bytes_received: int
    error: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    blocked_by_budget: bool = False
    redirect_hops: int = 0


class SecurityException(Exception):
    """Raised when an outbound URL violates SSRF or security constraints."""
    pass


def is_safe_ip(ip_str: str) -> bool:
    """Verify that an IP address is a public, routable IP (defending against SSRF)."""
    try:
        ip = ipaddress.ip_address(ip_str)
        # Check against private, loopback, link-local, reserved, multicast
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
        return True
    except ValueError:
        return False


def resolve_public_ip(hostname: str) -> str:
    """Resolve a hostname and return one validated public IP.

    The function fails closed. Every DNS answer is checked, so a name that
    returns a mixture of public and private/prohibited addresses is rejected
    rather than silently accepting the first answer. The returned IP is the
    address that callers must pin the subsequent connection to.
    """
    if not hostname:
        raise SecurityException("Missing hostname")

    host = hostname.strip().rstrip(".")

    # Direct IP literals do not need DNS and must be checked directly.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not is_safe_ip(host):
            raise SecurityException(f"SSRF blocked: prohibited IP '{host}'")
        return host

    # Normalize internationalized hostnames before asking the resolver.
    try:
        dns_host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise SecurityException(f"Invalid hostname '{host}'") from exc

    try:
        addrs = socket.getaddrinfo(dns_host, None)
    except (socket.gaierror, OSError, UnicodeError) as exc:
        # Fail closed. A host that cannot be validated must not be contacted.
        raise SecurityException(f"DNS resolution failed for '{host}'") from exc

    resolved: list[str] = []
    for _, _, _, _, sockaddr in addrs:
        ip = sockaddr[0]
        if not is_safe_ip(ip):
            raise SecurityException(
                f"SSRF blocked: hostname '{host}' resolves to prohibited IP '{ip}'"
            )
        if ip not in resolved:
            resolved.append(ip)

    if not resolved:
        raise SecurityException(f"DNS resolution returned no addresses for '{host}'")

    return resolved[0]


def validate_url_safety(url: str) -> str:
    """Validate scheme/host and return the public IP that must be contacted."""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise SecurityException(f"Unsupported URL scheme: {parsed.scheme}")

    hostname = parsed.hostname
    if not hostname:
        raise SecurityException(f"Missing hostname in URL: {url}")

    return resolve_public_ip(hostname)


@contextmanager
def _pin_connection(ip: Optional[str]) -> Iterator[None]:
    """Pin the current thread's next socket connection to a validated IP."""
    previous = getattr(_PIN_LOCAL, "ip", _UNSET)
    _PIN_LOCAL.ip = ip
    try:
        yield
    finally:
        if previous is _UNSET:
            try:
                del _PIN_LOCAL.ip
            except AttributeError:
                pass
        else:
            _PIN_LOCAL.ip = previous


class _PinnedConnectionMixin:
    """Connect to the validated IP while retaining the original HTTP host/TLS name."""

    def _new_conn(self):  # type: ignore[no-untyped-def]
        pinned = getattr(_PIN_LOCAL, "ip", None)
        if not pinned:
            return super()._new_conn()

        # urllib3 uses _dns_host for name resolution and self.host (derived from
        # it) for the Host header and TLS SNI. Temporarily substituting the DNS
        # host makes the socket go to the validated IP; restoring it before the
        # TLS/handshake phase preserves certificate hostname verification and
        # the original Host header.
        original_dns_host = self._dns_host
        self._dns_host = pinned
        try:
            return super()._new_conn()
        finally:
            self._dns_host = original_dns_host


class _PinnedHTTPConnection(_PinnedConnectionMixin, urllib3_connection.HTTPConnection):
    pass


class _PinnedHTTPSConnection(_PinnedConnectionMixin, urllib3_connection.HTTPSConnection):
    pass


class _PinnedHTTPConnectionPool(urllib3_connectionpool.HTTPConnectionPool):
    ConnectionCls = _PinnedHTTPConnection


class _PinnedHTTPSConnectionPool(urllib3_connectionpool.HTTPSConnectionPool):
    ConnectionCls = _PinnedHTTPSConnection


class _PinnedPoolManager(urllib3.PoolManager):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.pool_classes_by_scheme = {
            "http": _PinnedHTTPConnectionPool,
            "https": _PinnedHTTPSConnectionPool,
        }


# Connection-pool reuse note: a pooled keep-alive connection is only ever handed
# out for requests to the same host, and it was itself created by
# ``_PinnedConnectionMixin._new_conn`` after the destination IP was validated
# and pinned. urllib3 does not re-resolve the host for a reused connection, so a
# reused connection still contacts a previously-validated IP -- it cannot be
# redirected to an unvalidated or private destination. The pin itself is scoped
# per ``_pin_connection`` block (cleared after each request), so a pin for one
# host never leaks into a connection for another host. The HTTP ``Host`` header
# and TLS SNI/certificate verification continue to use the original hostname
# because ``_dns_host`` is restored before the TLS handshake.
class _PinnedHTTPAdapter(HTTPAdapter):
    """requests adapter that resolves, validates and pins destination IPs.

    Proxies are refused outright. A forward proxy terminates the TLS connection
    and learns the real destination, so destination-IP pinning cannot be
    enforced through one. ``trust_env`` is also disabled on the session so that
    ``HTTP_PROXY``/``HTTPS_PROXY``/``ALL_PROXY`` (and their lowercase variants)
    from the environment are never inherited.
    """

    def init_poolmanager(self, connections, maxsize, block=DEFAULT_POOLBLOCK, **pool_kwargs):  # type: ignore[no-untyped-def]
        super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)
        self.poolmanager = _PinnedPoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            **pool_kwargs,
        )

    def send(self, request, **kwargs):  # type: ignore[no-untyped-def]
        proxies = kwargs.get("proxies") or {}
        if proxies:
            # Fail closed: never fall back to the base adapter, which would
            # route through the proxy and bypass validated-destination pinning.
            raise SecurityException(
                "Proxy configuration is not allowed; it bypasses validated-destination IP pinning"
            )

        pinned = getattr(_PIN_LOCAL, "ip", None)
        if not pinned:
            parsed = urlparse(request.url)
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
                raise SecurityException(f"Refusing to connect to unsafe URL: {request.url}")
            pinned = resolve_public_ip(parsed.hostname)

        with _pin_connection(pinned):
            return super().send(request, **kwargs)


class SafeHttpClient:
    """Production-grade HTTP client with safety boundaries.

    Uses a thread-local ``requests.Session`` so that a single client instance can be
    safely shared by every worker thread in the batch pool. Also maintains a
    thread-local counter of real outbound HTTP requests so that each company's
    ``operations.requests`` figure reflects measured network activity.

    Error policy:
      * SSRF/DNS validation failures are policy blocks and are returned as 403
        (or 400 for a DNS-level validation failure).
      * Expected transport failures are retried and finally returned as 500.
      * Programming errors (AssertionError, TypeError, etc.) are not swallowed;
        they propagate with their original traceback.
      * Budget denials are deliberate controls: no network request is made and
        the result is marked ``blocked_by_budget``.
    """

    DEFAULT_HEADERS = {
        "User-Agent": settings.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
        "Accept-Language": "nb,no;q=0.9,en;q=0.8",
    }

    def __init__(self, budget_tracker: Optional[Any] = None, request_budget: Optional[Any] = None) -> None:
        self.budget = budget_tracker
        self.request_budget = request_budget
        self._local = threading.local()
        self._rate_lock = threading.Lock()
        self._last_request_at: Dict[str, float] = {}

    def _min_interval_for(self, domain: str) -> float:
        if "brreg.no" in domain:
            rate = settings.brreg_rate_limit_per_second
            return (1.0 / rate) if rate > 0 else 0.0
        return max(0.0, settings.website_delay_seconds)

    def _throttle(self, url: str) -> None:
        """Enforce a polite minimum interval between requests to the same domain.

        Throttling is best-effort pacing. Configuration/programming errors in
        this path are not caught, because they indicate a bug rather than a
        transient network condition.
        """
        domain = urlparse(url).netloc.lower()
        if not domain:
            return
        interval = self._min_interval_for(domain)
        if interval <= 0:
            return
        # Reserve a slot under the lock, then sleep outside it.
        while True:
            with self._rate_lock:
                now = time.monotonic()
                last = self._last_request_at.get(domain, 0.0)
                wait = interval - (now - last)
                if wait <= 0:
                    self._last_request_at[domain] = now
                    return
            time.sleep(min(wait, interval))

    @property
    def session(self) -> requests.Session:
        """Return the calling thread's requests session, creating it on first use."""
        current = getattr(self._local, "session", None)
        if current is None:
            current = requests.Session()
            current.trust_env = False
            current.headers.update(self.DEFAULT_HEADERS)
            adapter = _PinnedHTTPAdapter()
            current.mount("http://", adapter)
            current.mount("https://", adapter)
            self._local.session = current
        return current

    def _bump_request_count(self, n: int = 1) -> int:
        count = getattr(self._local, "request_count", 0) + n
        self._local.request_count = count
        return count

    def _bump_denied(self) -> None:
        self._local.denied_count = getattr(self._local, "denied_count", 0) + 1

    def start_request_count(self) -> None:
        """Reset the calling thread's outbound request and denial counters (per-company scope)."""
        self._local.request_count = 0
        self._local.denied_count = 0

    def request_count(self) -> int:
        """Attempted outbound HTTP requests issued on this thread since reset (incl. retries + redirect hops)."""
        return getattr(self._local, "request_count", 0)

    def budget_denied_count(self) -> int:
        """Requests refused by the budget on this thread since the last reset."""
        return getattr(self._local, "denied_count", 0)

    def _record(self, url: str, elapsed_ms: float, bytes_received: int, status_code: int) -> None:
        """Record one actual outbound request in the metrics tracker."""
        if self.budget:
            self.budget.record_request(
                urlparse(url).netloc.lower(),
                elapsed_ms,
                bytes_received,
                status_code,
            )

    def _get(
        self,
        url: str,
        timeout: float,
        headers: Optional[Dict[str, str]],
        pinned_ip: Optional[str],
    ) -> requests.Response:
        # The pin is set only around the call that opens the connection. Host
        # headers and TLS SNI still use the original URL hostname.
        with _pin_connection(pinned_ip):
            return self.session.get(
                url,
                timeout=timeout,
                stream=True,
                allow_redirects=False,
                headers=headers,
            )

    def fetch(
        self,
        url: str,
        timeout: Optional[float] = None,
        max_bytes: Optional[int] = None,
        max_retries: Optional[int] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> FetchResult:
        timeout = timeout or settings.request_timeout_seconds
        max_bytes = max_bytes or settings.max_response_bytes
        max_retries = max_retries if max_retries is not None else settings.max_retries

        start_time = time.time()

        # 1. SSRF check. This is a local policy block: no network request is made
        #    and no request budget is consumed. validate_url_safety returns the
        #    validated IP, which is then pinned for the actual connection.
        try:
            pinned_ip = validate_url_safety(url)
        except SecurityException as sec_err:
            elapsed = (time.time() - start_time) * 1000
            return FetchResult(
                url=url,
                status_code=403,
                content=b"",
                text="",
                content_type="text/plain",
                elapsed_ms=elapsed,
                bytes_received=0,
                error=f"SSRF Blocked: {sec_err}",
            )
        except (socket.gaierror, OSError) as err:
            elapsed = (time.time() - start_time) * 1000
            return FetchResult(
                url=url,
                status_code=400,
                content=b"",
                text="",
                content_type="text/plain",
                elapsed_ms=elapsed,
                bytes_received=0,
                error=f"URL validation failed: {err}",
            )
        # Any other exception is a programming/configuration bug and must
        # propagate instead of being disguised as a network failure.

        # 2. Retries with exponential backoff & jitter. The budget gate runs on
        #    every attempt so retries cannot bypass the ceiling.
        last_error = None
        for attempt in range(max_retries + 1):
            if attempt > 0:
                sleep_sec = (settings.backoff_factor ** attempt) + random.uniform(0.1, 0.5)
                time.sleep(sleep_sec)

            if self.request_budget is not None and not self.request_budget.try_acquire(1):
                self._bump_denied()
                return FetchResult(
                    url=url,
                    status_code=429,
                    content=b"",
                    text="",
                    content_type="text/plain",
                    elapsed_ms=(time.time() - start_time) * 1000,
                    bytes_received=0,
                    error="REQUEST_BUDGET_EXHAUSTED",
                    blocked_by_budget=True,
                )

            self._throttle(url)
            self._bump_request_count(1)
            req_start = time.time()
            current_url = url
            current_pinned_ip = pinned_ip
            current_recorded = False
            request_elapsed = 0.0
            bytes_read = 0
            status: Optional[int] = None
            response: Optional[requests.Response] = None

            try:
                response = self._get(url, timeout, headers, current_pinned_ip)
                request_elapsed = (time.time() - req_start) * 1000
                status = response.status_code
                content_type = response.headers.get("Content-Type", "")

                # Follow redirects manually so every hop is validated,
                # throttled, and charged to the request budget before it is
                # issued. Relative Location headers are resolved against the
                # current response URL, loops are rejected, and a budget
                # denial is surfaced as blocked_by_budget=True.
                redirect_hops = 0
                redirect_budget_exhausted = False
                redirect_error: Optional[str] = None
                visited = {url}

                while response.is_redirect:
                    next_url = response.headers.get("Location")
                    if not next_url:
                        break
                    next_url = urljoin(response.url, next_url)
                    if next_url in visited:
                        redirect_error = "Redirect loop detected"
                        break
                    if redirect_hops >= MAX_REDIRECTS:
                        redirect_error = "Too many redirects"
                        break
                    # Never follow a redirect to an unsafe destination.
                    try:
                        next_pinned_ip = validate_url_safety(next_url)
                    except SecurityException as sec_err:
                        redirect_error = f"SSRF Blocked: unsafe redirect destination ({sec_err})"
                        break
                    # Charge the hop to the global/per-company budget.
                    if self.request_budget is not None and not self.request_budget.try_acquire(1):
                        redirect_budget_exhausted = True
                        break

                    # The current redirect response was a real outbound request;
                    # record it exactly once before moving to the next hop.
                    if not current_recorded:
                        self._record(
                            response.url or current_url,
                            request_elapsed,
                            0,
                            status or 0,
                        )
                        current_recorded = True
                    response.close()

                    self._throttle(next_url)
                    self._bump_request_count(1)
                    redirect_hops += 1
                    visited.add(next_url)
                    current_url = next_url
                    current_pinned_ip = next_pinned_ip
                    req_start = time.time()
                    response = self._get(
                        next_url,
                        timeout,
                        headers,
                        current_pinned_ip,
                    )
                    request_elapsed = (time.time() - req_start) * 1000
                    status = response.status_code
                    content_type = response.headers.get("Content-Type", "")
                    current_recorded = False

                if redirect_budget_exhausted:
                    redirect_error = "REQUEST_BUDGET_EXHAUSTED"

                if status in {429, 503} and attempt < max_retries:
                    last_error = f"HTTP {status}"
                    if not current_recorded:
                        self._record(
                            response.url or current_url,
                            request_elapsed,
                            0,
                            status,
                        )
                        current_recorded = True
                    continue

                # Stream chunks up to max_bytes
                chunks = []
                bytes_read = 0
                for chunk in response.iter_content(chunk_size=16384):
                    if chunk:
                        bytes_read += len(chunk)
                        if bytes_read > max_bytes:
                            if not current_recorded:
                                self._record(
                                    response.url or current_url,
                                    request_elapsed,
                                    bytes_read,
                                    413,
                                )
                                current_recorded = True
                            return FetchResult(
                                url=response.url,
                                status_code=413,
                                content=b"".join(chunks),
                                text="",
                                content_type=content_type,
                                elapsed_ms=request_elapsed,
                                bytes_received=bytes_read,
                                error="Payload Too Large (Exceeded max_response_bytes)",
                                redirect_hops=redirect_hops,
                            )
                        chunks.append(chunk)

                full_content = b"".join(chunks)
                # Decode text safely.
                text = ""
                try:
                    text = full_content.decode(response.encoding or "utf-8", errors="replace")
                except (UnicodeError, LookupError):
                    text = full_content.decode("utf-8", errors="replace")

                if not current_recorded:
                    self._record(
                        response.url or current_url,
                        request_elapsed,
                        bytes_read,
                        status or 0,
                    )
                    current_recorded = True

                return FetchResult(
                    url=response.url,
                    status_code=status,
                    content=full_content,
                    text=text,
                    content_type=content_type,
                    elapsed_ms=request_elapsed,
                    bytes_received=bytes_read,
                    headers=dict(response.headers),
                    redirect_hops=redirect_hops,
                    error=redirect_error,
                    blocked_by_budget=redirect_budget_exhausted,
                )
            except SecurityException as err:
                # Policy failure discovered at connection time (e.g. DNS changed
                # after the preflight). This is a deliberate block, not a retry.
                if not current_recorded:
                    self._record(
                        current_url,
                        request_elapsed,
                        bytes_read,
                        403,
                    )
                    current_recorded = True
                return FetchResult(
                    url=current_url,
                    status_code=403,
                    content=b"",
                    text="",
                    content_type="text/plain",
                    elapsed_ms=(time.time() - start_time) * 1000,
                    bytes_received=0,
                    error=f"SSRF Blocked: {err}",
                )
            except (requests.RequestException, socket.timeout, socket.error) as err:
                # Expected transport failure: retry within policy, then return a
                # normal FetchResult so callers never receive None.
                last_error = str(err)
                if not current_recorded:
                    self._record(
                        current_url,
                        request_elapsed,
                        bytes_read,
                        status or 500,
                    )
                    current_recorded = True
                if attempt == max_retries:
                    break
            finally:
                if response is not None:
                    response.close()

        elapsed = (time.time() - start_time) * 1000
        return FetchResult(
            url=url,
            status_code=500,
            content=b"",
            text="",
            content_type="text/plain",
            elapsed_ms=elapsed,
            bytes_received=0,
            error=last_error or "Network failure",
        )
