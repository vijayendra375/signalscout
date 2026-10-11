"""Safe HTTP client with SSRF defense, bounded memory, retries, and latency tracking."""

from __future__ import annotations

import ipaddress
import random
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlparse
import requests

from app.config.settings import settings


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


def validate_url_safety(url: str) -> None:
    """Validate that the URL uses HTTP/HTTPS and resolves to a safe, public IP."""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise SecurityException(f"Unsupported URL scheme: {parsed.scheme}")
    
    hostname = parsed.hostname
    if not hostname:
        raise SecurityException(f"Missing hostname in URL: {url}")
        
    # Check for direct IP in URL
    if is_safe_ip(hostname):
        return
        
    try:
        # Resolve DNS
        addrs = socket.getaddrinfo(hostname, None)
        for family, _, _, _, sockaddr in addrs:
            ip = sockaddr[0]
            if not is_safe_ip(ip):
                raise SecurityException(f"SSRF blocked: Hostname '{hostname}' resolves to private/prohibited IP '{ip}'")
    except socket.gaierror as e:
        # DNS resolution failure will be handled gracefully by the request layer
        pass


class SafeHttpClient:
    """Production-grade HTTP client with safety boundaries.

    Uses a thread-local ``requests.Session`` so that a single client instance can be
    safely shared by every worker thread in the batch pool. Also maintains a
    thread-local counter of real outbound HTTP requests so that each company's
    ``operations.requests`` figure reflects measured network activity.
    """

    DEFAULT_HEADERS = {
        "User-Agent": settings.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
        "Accept-Language": "nb,no;q=0.9,en;q=0.8",
    }

    def __init__(self, budget_tracker: Optional[Any] = None) -> None:
        self.budget = budget_tracker
        self._local = threading.local()
        self._rate_lock = threading.Lock()
        self._last_request_at: Dict[str, float] = {}

    def _min_interval_for(self, domain: str) -> float:
        if "brreg.no" in domain:
            rate = settings.brreg_rate_limit_per_second
            return (1.0 / rate) if rate > 0 else 0.0
        return max(0.0, settings.website_delay_seconds)

    def _throttle(self, url: str) -> None:
        """Enforce a polite minimum interval between requests to the same domain."""
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
            current.headers.update(self.DEFAULT_HEADERS)
            self._local.session = current
        return current

    def _bump_request_count(self) -> int:
        count = getattr(self._local, "request_count", 0) + 1
        self._local.request_count = count
        return count

    def start_request_count(self) -> None:
        """Reset the calling thread's outbound request counter (per-company scope)."""
        self._local.request_count = 0

    def request_count(self) -> int:
        """Return the number of outbound HTTP requests issued on this thread since reset."""
        return getattr(self._local, "request_count", 0)

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
        
        # 1. SSRF check
        try:
            validate_url_safety(url)
        except SecurityException as sec_err:
            elapsed = (time.time() - start_time) * 1000
            if self.budget:
                self.budget.record_request(urlparse(url).netloc, elapsed, 0, 403)
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

        # 2. Retries with exponential backoff & jitter
        last_error = None
        for attempt in range(max_retries + 1):
            if attempt > 0:
                sleep_sec = (settings.backoff_factor ** attempt) + random.uniform(0.1, 0.5)
                time.sleep(sleep_sec)
                
            req_start = time.time()
            self._throttle(url)
            self._bump_request_count()
            try:
                with self.session.get(url, timeout=timeout, stream=True, allow_redirects=True, headers=headers) as response:
                    elapsed = (time.time() - req_start) * 1000
                    status = response.status_code
                    content_type = response.headers.get("Content-Type", "")
                    
                    if status in {429, 503} and attempt < max_retries:
                        last_error = f"HTTP {status}"
                        continue
                        
                    # Stream chunks up to max_bytes
                    chunks = []
                    bytes_read = 0
                    for chunk in response.iter_content(chunk_size=16384):
                        if chunk:
                            bytes_read += len(chunk)
                            if bytes_read > max_bytes:
                                if self.budget:
                                    self.budget.record_request(urlparse(url).netloc, elapsed, bytes_read, 413)
                                return FetchResult(
                                    url=response.url,
                                    status_code=413,
                                    content=b"".join(chunks),
                                    text="",
                                    content_type=content_type,
                                    elapsed_ms=elapsed,
                                    bytes_received=bytes_read,
                                    error="Payload Too Large (Exceeded max_response_bytes)",
                                )
                            chunks.append(chunk)
                            
                    full_content = b"".join(chunks)
                    # Decode text safely
                    text = ""
                    try:
                        text = full_content.decode(response.encoding or "utf-8", errors="replace")
                    except Exception:
                        text = full_content.decode("utf-8", errors="replace")
                        
                    if self.budget:
                        self.budget.record_request(urlparse(url).netloc, elapsed, bytes_read, status)

                    return FetchResult(
                        url=response.url,
                        status_code=status,
                        content=full_content,
                        text=text,
                        content_type=content_type,
                        elapsed_ms=elapsed,
                        bytes_received=bytes_read,
                        headers=dict(response.headers),
                    )
            except (requests.RequestException, socket.timeout, socket.error) as err:
                last_error = str(err)
                if attempt == max_retries:
                    break
                    
        elapsed = (time.time() - start_time) * 1000
        if self.budget:
            self.budget.record_request(urlparse(url).netloc, elapsed, 0, 500)
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
