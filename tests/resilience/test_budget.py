"""Tests for the thread-safe RequestBudget (Workstream A).

Covers global budget, per-company budget, concurrent accounting, retry/redirect
charging, deadline expiry, and graceful exhaustion without crashing.
"""

from __future__ import annotations

import threading
import time

from app.budget.request_budget import BudgetSnapshot, RequestBudget


# --- Global budget -----------------------------------------------------------

def test_global_budget_enforces_hard_ceiling():
    budget = RequestBudget(global_limit=3, per_company_limit=None, deadline_seconds=None)
    assert budget.try_acquire(1) is True
    assert budget.try_acquire(1) is True
    assert budget.try_acquire(1) is True
    # Ceiling reached: next acquire must be denied.
    assert budget.try_acquire(1) is False
    assert budget.snapshot().global_used == 3
    assert budget.snapshot().denied == 1
    assert budget.remaining() == 0


def test_global_budget_zero_unlimited():
    budget = RequestBudget(global_limit=0, per_company_limit=None, deadline_seconds=None)
    assert budget.try_acquire(1) is True
    assert budget.remaining() is None


def test_global_budget_negative_treated_as_unlimited():
    budget = RequestBudget(global_limit=-1, per_company_limit=None, deadline_seconds=None)
    assert budget.try_acquire(100) is True


# --- Per-company budget ------------------------------------------------------

def test_per_company_budget_is_isolated():
    budget = RequestBudget(global_limit=None, per_company_limit=2, deadline_seconds=None)

    budget.start_company("org-a")
    assert budget.try_acquire(1) is True
    assert budget.try_acquire(1) is True
    assert budget.try_acquire(1) is False  # per-company ceiling for org-a

    # Another company is unaffected.
    budget.start_company("org-b")
    assert budget.try_acquire(1) is True
    assert budget.company_used("org-a") == 2
    assert budget.company_used("org-b") == 1


def test_per_company_budget_zero_unlimited():
    budget = RequestBudget(global_limit=None, per_company_limit=0, deadline_seconds=None)
    budget.start_company("org-x")
    assert budget.try_acquire(50) is True


# --- Can-spend (non-mutating peek) ------------------------------------------

def test_can_spend_does_not_consume():
    budget = RequestBudget(global_limit=2, per_company_limit=None, deadline_seconds=None)
    assert budget.can_spend(1) is True
    assert budget.remaining() == 2  # not consumed
    assert budget.try_acquire(1) is True
    assert budget.remaining() == 1


def test_can_spend_respects_per_company():
    budget = RequestBudget(global_limit=None, per_company_limit=1, deadline_seconds=None)
    budget.start_company("org-a")
    assert budget.can_spend(1) is True       # nothing used yet
    assert budget.try_acquire(1) is True     # consume the single slot
    assert budget.can_spend(1) is False      # now at limit


# --- Retry / redirect accounting (charge_extra) ------------------------------

def test_charge_extra_accounts_for_redirect_hops():
    budget = RequestBudget(global_limit=5, per_company_limit=None, deadline_seconds=None)
    # Main request reserves 1, redirect hops reserve 2 more after the fact.
    assert budget.try_acquire(1) is True
    budget.charge_extra(2)
    assert budget.snapshot().global_used == 3
    assert budget.try_acquire(2) is True
    assert budget.try_acquire(1) is False


def test_charge_extra_zero_is_noop():
    budget = RequestBudget(global_limit=5, per_company_limit=None, deadline_seconds=None)
    budget.charge_extra(0)
    budget.charge_extra(-1)
    assert budget.snapshot().global_used == 0


# --- Deadline ----------------------------------------------------------------

def test_deadline_expiry_denies_all_acquires():
    budget = RequestBudget(
        global_limit=None, per_company_limit=None, deadline_seconds=0.05
    )
    assert budget.try_acquire(1) is True
    time.sleep(0.1)
    assert budget.expired() is True
    assert budget.try_acquire(1) is False
    assert budget.snapshot().expired is True


def test_no_deadline_never_expires():
    budget = RequestBudget(global_limit=None, per_company_limit=None, deadline_seconds=None)
    assert budget.expired() is False


# --- Concurrency -------------------------------------------------------------

def test_concurrent_acquires_respect_global_limit():
    budget = RequestBudget(global_limit=20, per_company_limit=None, deadline_seconds=None)
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
    assert total_granted <= 20, f"Granted {total_granted} over global limit 20"
    assert total_granted + total_denied == 8 * 5
    assert budget.snapshot().global_used == total_granted


def test_concurrent_per_company_isolation():
    budget = RequestBudget(global_limit=None, per_company_limit=3, deadline_seconds=None)
    results_a = []
    results_b = []
    lock = threading.Lock()

    def worker_a():
        budget.start_company("org-a")
        for _ in range(5):
            ok = budget.try_acquire(1)
            with lock:
                results_a.append(ok)

    def worker_b():
        budget.start_company("org-b")
        for _ in range(5):
            ok = budget.try_acquire(1)
            with lock:
                results_b.append(ok)

    ta = threading.Thread(target=worker_a)
    tb = threading.Thread(target=worker_b)
    ta.start(); tb.start()
    ta.join(); tb.join()

    assert sum(1 for r in results_a if r) <= 3
    assert sum(1 for r in results_b if r) <= 3
    assert budget.company_used("org-a") <= 3
    assert budget.company_used("org-b") <= 3


# --- Snapshot ----------------------------------------------------------------

def test_snapshot_returns_complete_state():
    budget = RequestBudget(global_limit=10, per_company_limit=4, deadline_seconds=3600)
    budget.start_company("org-1")
    budget.try_acquire(2)
    snap = budget.snapshot()
    assert isinstance(snap, BudgetSnapshot)
    assert snap.global_limit == 10
    assert snap.global_used == 2
    assert snap.global_remaining == 8
    assert snap.per_company_limit == 4
    assert snap.deadline_seconds == 3600
    assert snap.expired is False
    assert snap.denied == 0
