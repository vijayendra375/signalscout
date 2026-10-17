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
    """Thread-safe global + per-company + wall-clock request budget."""

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

    # --- company context (one company is processed per worker thread) ---------
    def start_company(self, org: str) -> None:
        self._local.org = org

    def end_company(self) -> None:
        self._local.org = None

    def _current_org(self) -> Optional[str]:
        return getattr(self._local, "org", None)

    def company_used(self, org: str) -> int:
        with self._lock:
            return self._company_used.get(org, 0)

    # --- policy ---------------------------------------------------------------
    def expired(self) -> bool:
        return self.deadline_seconds is not None and (time.monotonic() - self._start) > self.deadline_seconds

    def remaining(self) -> Optional[int]:
        if self.global_limit is None:
            return None
        with self._lock:
            return max(0, self.global_limit - self._global_used)

    def company_remaining(self) -> Optional[int]:
        if self.per_company_limit is None:
            return None
        org = self._current_org()
        if org is None:
            return self.per_company_limit
        with self._lock:
            return max(0, self.per_company_limit - self._company_used.get(org, 0))

    def can_spend(self, n: int = 1) -> bool:
        """Return True if ``n`` more requests are allowed right now (no reservation)."""
        if self.expired():
            return False
        with self._lock:
            if self.global_limit is not None and self._global_used + n > self.global_limit:
                return False
            org = self._current_org()
            if self.per_company_limit is not None and org is not None:
                if self._company_used.get(org, 0) + n > self.per_company_limit:
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
            if self.per_company_limit is not None and org is not None:
                if self._company_used.get(org, 0) + n > self.per_company_limit:
                    self._denied += 1
                    return False
            self._global_used += n
            if org is not None:
                self._company_used[org] = self._company_used.get(org, 0) + n
            return True

    def charge_extra(self, n: int) -> None:
        """Account for already-issued requests discovered after the fact (e.g. redirect hops)."""
        if n <= 0:
            return
        with self._lock:
            self._global_used += n
            org = self._current_org()
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
