"""Central request-budget enforcement.

Provides a single, thread-safe authority for how many outbound HTTP requests a
run may make, how many a single company may make, and how long the run may take.
The HTTP client consults this before every attempt (including retries) so that
retries can never silently bypass the budget, and the pipeline consults it to
decide whether optional work (subunits, group structure, website crawl) is worth
attempting.

Counting definitions used across the system:
  * attempted  — HTTP attempts actually issued to the network (incl. retries and
                 redirect hops).
  * completed    — attempts that received an HTTP response of any status.
  * denied       — attempts the budget refused before any network call was made.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class BudgetSnapshot:
    global_limit: Optional[int]
    global_used: int
    global_remaining: Optional[int]
    per_company_limit: Optional[int]
    deadline_seconds: Optional[float]
    expired: bool
    denied: int

    def as_dict(self) -> Dict[str, object]:
        return {
            "global_limit": self.global_limit,
            "global_used": self.global_used,
            "global_remaining": self.global_remaining,
            "per_company_limit": self.per_company_limit,
            "deadline_seconds": self.deadline_seconds,
            "expired": self.expired,
            "denied": self.denied,
        }


class RequestBudget:
    """Thread-safe global + per-company + wall-clock request budget.

    Fairness uses a stable reservation, not a dynamically growing
    ``current_used + fair_share`` allowance. When a company starts it is
    allocated a fixed share based on the currently unallocated budget and the
    number of companies that have not started/completed yet. The company can
    spend only within that reservation. Completing a company releases its
    unused reservation for companies that start later.
    """

    def __init__(
        self,
        global_limit: Optional[int] = None,
        per_company_limit: Optional[int] = None,
        deadline_seconds: Optional[float] = None,
    ) -> None:
        self.global_limit = global_limit if global_limit and global_limit > 0 else None
        self.per_company_limit = per_company_limit if per_company_limit and per_company_limit > 0 else None
        self.deadline_seconds = deadline_seconds if deadline_seconds and deadline_seconds > 0 else None
        self._lock = threading.Lock()
        self._global_used = 0
        self._company_used: Dict[str, int] = {}
        self._denied = 0
        self._start = time.monotonic()
        self._local = threading.local()
        self._total_companies = 0
        self._completed_companies = 0
        self._allocation: Dict[str, int] = {}

    # --- company context (one company is processed per worker thread) ---------
    def start_company(self, org: str) -> None:
        with self._lock:
            self._local.org = org
            if org not in self._allocation:
                self._allocation[org] = self._initial_allowance_locked()

    def end_company(self) -> None:
        self._local.org = None

    def complete_company(self, org: str) -> None:
        """Release this company's unused reservation and mark it complete."""
        with self._lock:
            self._allocation.pop(org, None)
            self._completed_companies += 1
        self.end_company()

    def _current_org(self) -> Optional[str]:
        return getattr(self._local, "org", None)

    def company_used(self, org: str) -> int:
        with self._lock:
            return self._company_used.get(org, 0)

    def set_total_companies(self, count: int) -> None:
        """Start a new batch scope for fair allocation.

        A complete reset is only safe when no company holds an active
        reservation: resetting mid-batch would discard in-flight workers'
        allowances. If workers are active, refuse to reset. Otherwise clear
        usage as well so a reused runner does not carry previous-batch
        consumption into the next batch.
        """
        with self._lock:
            if self._allocation:
                raise RuntimeError(
                    "Cannot reset budget scope while companies are still active"
                )
            self._total_companies = count
            self._completed_companies = 0
            self._global_used = 0
            self._company_used.clear()
            self._denied = 0
            self._start = time.monotonic()
            self._allocation.clear()

    @property
    def completed_companies(self) -> int:
        """Number of companies that have completed the research lifecycle."""
        with self._lock:
            return self._completed_companies

    @property
    def total_companies(self) -> int:
        """Number of companies counted for fair-share allocation."""
        with self._lock:
            return self._total_companies

    # --- policy ---------------------------------------------------------------
    def expired(self) -> bool:
        return self.deadline_seconds is not None and (time.monotonic() - self._start) > self.deadline_seconds

    def remaining(self) -> Optional[int]:
        if self.global_limit is None:
            return None
        with self._lock:
            return max(0, self.global_limit - self._global_used)

    def company_remaining(self) -> Optional[int]:
        org = self._current_org()
        with self._lock:
            if org is not None and org in self._allocation:
                return max(0, self._allocation[org] - self._company_used.get(org, 0))
            if self.per_company_limit is None:
                return None
            if org is None:
                return self.per_company_limit
            return max(0, self.per_company_limit - self._company_used.get(org, 0))

    def _reserved_remaining_locked(self) -> int:
        """Unspent reservations held by currently active companies."""
        return sum(
            max(0, allowance - self._company_used.get(org, 0))
            for org, allowance in self._allocation.items()
        )

    def _initial_allowance_locked(self) -> int:
        """Stable allowance assigned when a company starts. Must hold _lock."""
        if self.global_limit is None:
            return self.per_company_limit or 2**31 - 1
        if self._total_companies == 0:
            return self.per_company_limit or self.global_limit

        remaining_companies = max(
            1,
            self._total_companies
            - self._completed_companies
            - len(self._allocation),
        )
        available = max(
            0,
            self.global_limit
            - self._global_used
            - self._reserved_remaining_locked(),
        )
        allowance = available // remaining_companies
        if self.per_company_limit is not None:
            allowance = min(allowance, self.per_company_limit)
        return max(0, allowance)

    def _allowance_for_locked(self, org: Optional[str]) -> Optional[int]:
        """Return the active reservation, or the non-fair fallback allowance."""
        if org is None:
            return None
        if org in self._allocation:
            return self._allocation[org]
        if self._total_companies == 0:
            return self.per_company_limit
        return None

    def can_spend(self, n: int = 1) -> bool:
        """Return True if ``n`` more requests are allowed right now."""
        if self.expired():
            return False
        with self._lock:
            if self.global_limit is not None and self._global_used + n > self.global_limit:
                return False
            org = self._current_org()
            allowance = self._allowance_for_locked(org)
            if org is not None and allowance is not None:
                if self._company_used.get(org, 0) + n > allowance:
                    return False
        return True

    def try_acquire(self, n: int = 1) -> bool:
        """Atomically reserve ``n`` requests. Returns False (and records a denial) if not allowed."""
        if self.expired():
            with self._lock:
                self._denied += 1
            return False
        with self._lock:
            if self.global_limit is not None and self._global_used + n > self.global_limit:
                self._denied += 1
                return False
            org = self._current_org()
            allowance = self._allowance_for_locked(org)
            if org is not None and allowance is not None:
                if self._company_used.get(org, 0) + n > allowance:
                    self._denied += 1
                    return False
            self._global_used += n
            if org is not None:
                self._company_used[org] = self._company_used.get(org, 0) + n
            return True

    def charge_extra(self, n: int) -> None:
        """Account for already-issued requests discovered after the fact.

        Does not exceed the global limit or the active company's reservation;
        only charges up to the remaining allowance.
        """
        if n <= 0:
            return
        with self._lock:
            if self.global_limit is not None:
                available = self.global_limit - self._global_used
                if available <= 0:
                    return  # Budget exhausted, cannot charge extra
                n = min(n, available)
            org = self._current_org()
            allowance = self._allowance_for_locked(org)
            if org is not None and allowance is not None:
                n = min(n, max(0, allowance - self._company_used.get(org, 0)))
            if n <= 0:
                return
            self._global_used += n
            if org is not None:
                self._company_used[org] = self._company_used.get(org, 0) + n

    def snapshot(self) -> BudgetSnapshot:
        with self._lock:
            remaining = None if self.global_limit is None else max(0, self.global_limit - self._global_used)
            return BudgetSnapshot(
                global_limit=self.global_limit,
                global_used=self._global_used,
                global_remaining=remaining,
                per_company_limit=self.per_company_limit,
                deadline_seconds=self.deadline_seconds,
                expired=self.expired(),
                denied=self._denied,
            )
