"""robots.txt compliance gate for polite, lawful website crawling."""

from __future__ import annotations

import threading
from typing import Dict, Optional
from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser

from app.fetching.http_client import SafeHttpClient


class RobotsGate:
    """Fetches and caches robots.txt policies, and answers crawl-permission queries.

    A missing robots.txt is treated as permissive (standard convention); an
    unreachable robots.txt fails closed for non-homepage paths to stay lawful.
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
            elif res.status_code in {401, 403}:
                parser = RobotFileParser()
                parser.disallow_all = True
            else:
                # 404 or other: no published policy.
                parser = None
        except Exception:
            parser = None

        with self._lock:
            self._cache[origin] = parser
        return parser

    def allowed(self, url: str) -> bool:
        """Return True when the user agent may fetch the given URL."""
        try:
            parser = self._parser_for(url)
        except Exception:
            parser = None
        if parser is None:
            return True
        try:
            return parser.can_fetch(self.user_agent, url)
        except Exception:
            return True
