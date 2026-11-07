"""Tests for budget-block propagation from the Brreg adapter."""

from app.evidence.store import EvidenceStore
from app.fetching.http_client import FetchResult
from app.sources.brreg import BrregAdapter


class _StaticClient:
    def __init__(self, result: FetchResult) -> None:
        self.result = result

    def fetch(self, url, **kwargs):
        return self.result


def _result(status: int, blocked: bool) -> FetchResult:
    return FetchResult(
        url="https://data.brreg.no/enhetsregisteret/api/enheter/989061593",
        status_code=status,
        content=b"",
        text="",
        content_type="application/json",
        elapsed_ms=1.0,
        bytes_received=0,
        error="REQUEST_BUDGET_EXHAUSTED" if blocked else None,
        blocked_by_budget=blocked,
    )


def test_brreg_flags_redirect_budget_block():
    """F4: a redirect hop denied by the budget must be distinguishable from a 404."""
    adapter = BrregAdapter(http_client=_StaticClient(_result(302, True)))

    data, ev_id = adapter.fetch_entity("989061593", EvidenceStore())

    assert data is None
    assert ev_id is None
    assert adapter.last_fetch_blocked_by_budget() is True


def test_brreg_does_not_flag_ordinary_404():
    adapter = BrregAdapter(http_client=_StaticClient(_result(404, False)))

    data, ev_id = adapter.fetch_entity("989061593", EvidenceStore())

    assert data is None
    assert ev_id is None
    assert adapter.last_fetch_blocked_by_budget() is False


def test_brreg_flag_resets_between_fetches():
    """The blocked flag describes only the most recent fetch on this thread."""

    class _SequenceClient:
        def __init__(self):
            self.calls = 0

        def fetch(self, url, **kwargs):
            self.calls += 1
            return _result(302, True) if self.calls == 1 else _result(404, False)

    adapter = BrregAdapter(http_client=_SequenceClient())
    adapter.fetch_entity("989061593", EvidenceStore())
    assert adapter.last_fetch_blocked_by_budget() is True

    adapter.fetch_entity("989061593", EvidenceStore())
    assert adapter.last_fetch_blocked_by_budget() is False
