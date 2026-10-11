"""Cost/request budget accounting and the $0 guarantee."""

from app.budget.tracker import BudgetTracker


def test_budget_tracker_counts_and_zero_cost():
    budget = BudgetTracker(declared_cost_usd=0.0)
    budget.record_request("data.brreg.no", 120.0, 2048, 200)
    budget.record_request("acme.no", 80.0, 1024, 200)
    budget.record_request("acme.no", 50.0, 0, 404)
    summary = budget.summary()
    assert summary["requests"] == 3
    assert summary["bytes"] == 3072
    assert summary["errors_count"] == 1
    assert summary["third_party_cost_usd"] == 0.0
    assert summary["p50_latency_ms"] is not None


def test_budget_tracker_empty_is_safe():
    summary = BudgetTracker().summary()
    assert summary["requests"] == 0
    assert summary["p50_latency_ms"] is None
    assert summary["third_party_cost_usd"] == 0.0


def test_declared_nonzero_cost_is_reported():
    summary = BudgetTracker(declared_cost_usd=1.25).summary()
    assert summary["third_party_cost_usd"] == 1.25
