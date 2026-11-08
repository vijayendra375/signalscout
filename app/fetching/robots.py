"""robots.txt compliance gate for polite, lawful website crawling."""

from __future__ import annotations

import threading
from typing import Dict, Optional
from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser

from app.fetching.http_client import SafeHttpClient


class RobotsGate:
    """Fetches and caches robots.txt policies, and answers crawl-permission queries.

    A missing robots.txt (404/410) is treated as having no published policy.
    Explicit disallow rules and robots retrieval failures fail closed for every
    URL, including the homepage.
    """

    def __init__(self, client: SafeHttpClient, user_agent: str) -> None:
        self.client = client
        self.user_agent = user_agent
        self._cache: Dict[str, Optional[RobotFileParser]] = {}
        self._lock = threading.Lock()

    def _robots_url(self, url: str) -> str:
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))

    def _parser_for(self, url: str) -> Optional[RobotFileParser]:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        with self._lock:
            if origin in self._cache:
                return self._cache[origin]

        parser: Optional[RobotFileParser]
        try:
            res = self.client.fetch(self._robots_url(url))
            if res.status_code == 200 and res.text:
                parser = RobotFileParser()
                parser.set_url(self._robots_url(url))
                parser.parse(res.text.splitlines())
            elif res.status_code in {404, 410}:
                # No published robots policy: ordinary public crawl convention.
                parser = None
            else:
                # 401/403, server errors, unexpected statuses and empty 200
                # responses fail closed. A temporary robots outage must never
                # silently grant permission to crawl the target page.
                parser = RobotFileParser()
                parser.set_url(self._robots_url(url))
                parser.disallow_all = True
        except Exception:
            # Network/DNS/TLS failures are not evidence of permission.
            parser = RobotFileParser()
            parser.set_url(self._robots_url(url))
            parser.disallow_all = True

        with self._lock:
            self._cache[origin] = parser
        return parser

    def allowed(self, url: str) -> bool:
        """Return True when the user agent may fetch the given URL."""
        try:
            parser = self._parser_for(url)
        except Exception:
            return False
        if parser is None:
            return True
        try:
            return parser.can_fetch(self.user_agent, url)
        except Exception:
            return True
