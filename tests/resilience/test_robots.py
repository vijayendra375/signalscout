"""robots.txt compliance gate tests (offline)."""

from app.fetching.http_client import FetchResult
from app.fetching.robots import RobotsGate


class FakeClient:
    def __init__(self, robots_status=200, robots_text="User-agent: *\nDisallow: /private"):
        self.robots_status = robots_status
        self.robots_text = robots_text
        self.calls = []

    def fetch(self, url, **kwargs):
        self.calls.append(url)
        return FetchResult(
            url=url,
            status_code=self.robots_status,
            content=self.robots_text.encode(),
            text=self.robots_text,
            content_type="text/plain",
            elapsed_ms=1.0,
            bytes_received=len(self.robots_text),
        )


def test_disallowed_path_blocked():
    gate = RobotsGate(FakeClient(), "SignalScout/1.0")
    assert gate.allowed("https://example.no/private/page") is False
    assert gate.allowed("https://example.no/public") is True


def test_missing_robots_is_permissive():
    gate = RobotsGate(FakeClient(robots_status=404, robots_text=""), "SignalScout/1.0")
    assert gate.allowed("https://example.no/anything") is True


def test_forbidden_robots_fails_closed():
    gate = RobotsGate(FakeClient(robots_status=403, robots_text=""), "SignalScout/1.0")
    assert gate.allowed("https://example.no/anything") is False


def test_robots_is_cached_per_origin():
    client = FakeClient()
    gate = RobotsGate(client, "SignalScout/1.0")
    gate.allowed("https://example.no/a")
    gate.allowed("https://example.no/b")
    assert sum(1 for c in client.calls if c.endswith("/robots.txt")) == 1



def test_server_error_robots_fails_closed():
    gate = RobotsGate(FakeClient(robots_status=503, robots_text=""), "SignalScout/1.0")
    assert gate.allowed("https://example.no/anything") is False


class RaisingClient:
    def fetch(self, url, **kwargs):
        raise OSError("temporary DNS failure")


def test_unreachable_robots_fails_closed():
    gate = RobotsGate(RaisingClient(), "SignalScout/1.0")
    assert gate.allowed("https://example.no/anything") is False
