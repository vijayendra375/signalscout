"""Tests for RequestBudget batch lifecycle and fair-share reset (Finding 2).

Covers:
  * reset must refuse while workers hold active reservations,
  * sequential runner reuse starts from zero usage,
  * concurrent starts share a stable fair allocation,
  * completion releases unused reservations for later companies,
  * the global ceiling holds under concurrent fair-share acquires.
"""

import threading

import pytest

from app.budget.request_budget import RequestBudget


def test_reset_refuses_while_workers_are_active():
    """F2: reset must never discard an active worker's reservation."""
    budget = RequestBudget(global_limit=100, per_company_limit=10, deadline_seconds=None)
    budget.set_total_companies(10)
    budget.start_company("active-org")
    try:
        with pytest.raises(RuntimeError, match="while companies are still active"):
            budget.set_total_companies(5)
    finally:
        budget.complete_company("active-org")

    # Once the worker completed, a fresh scope may be established.
    budget.set_total_companies(5)
    budget.start_company("fresh-org")
    assert budget.try_acquire(1) is True


def test_reset_clears_usage_for_sequential_batch_reuse():
    """F2: a reused runner starts the next batch from zero usage."""
    budget = RequestBudget(global_limit=10, per_company_limit=10, deadline_seconds=None)
    budget.set_total_companies(2)
    budget.start_company("org-a")
    budget.try_acquire(4)
    budget.complete_company("org-a")

    # Second batch on the same budget: usage must not carry over.
    budget.set_total_companies(2)
    assert budget.remaining() == 10
    budget.start_company("org-b")
    # Fair share for 2 companies: 10 / 2 = 5 (per-company cap 10 does not raise it).
    assert budget.try_acquire(5) is True
    assert budget.try_acquire(1) is False


def test_concurrent_starts_share_fair_allocation():
    """F2: companies that start concurrently each receive a stable fair share."""
    budget = RequestBudget(global_limit=100, per_company_limit=50, deadline_seconds=None)
    budget.set_total_companies(4)
    results = []
    lock = threading.Lock()
    barrier = threading.Barrier(4)

    def worker(org):
        barrier.wait()  # genuinely concurrent starts
        budget.start_company(org)
        n = 0
        while budget.can_spend(1):
            if budget.try_acquire(1):
                n += 1
        with lock:
            results.append((org, n))
        budget.complete_company(org)

    threads = [threading.Thread(target=worker, args=(f"org-{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total_granted = sum(n for _, n in results)
    assert total_granted <= 100
    assert all(n >= 1 for _, n in results), results


def test_completion_releases_unused_reservation():
    """F2: completing a company releases its unused reservation for later companies."""
    budget = RequestBudget(global_limit=100, per_company_limit=None, deadline_seconds=None)
    budget.set_total_companies(2)

    budget.start_company("a")
    # Fair share with 2 companies: 100 / 2 = 50.
    assert budget.try_acquire(10) is True
    budget.complete_company("a")  # releases the unused 40

    budget.start_company("b")
    # Recomputed fair share: (100 - 10) / 1 = 90.
    assert budget.try_acquire(90) is True
    assert budget.try_acquire(1) is False  # global ceiling reached (100)


def test_global_ceiling_under_concurrent_fair_share():
    """F2: concurrent fair-share acquires never exceed the global ceiling."""
    budget = RequestBudget(global_limit=20, per_company_limit=None, deadline_seconds=None)
    budget.set_total_companies(4)
    results = []
    lock = threading.Lock()

    def worker():
        for _ in range(5):
            ok = budget.try_acquire(1)
            with lock:
                results.append(ok)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total_granted = sum(1 for r in results if r)
    total_denied = sum(1 for r in results if not r)
    assert total_granted <= 20
    assert total_granted + total_denied == 8 * 5
    assert budget.snapshot().global_used == total_granted
