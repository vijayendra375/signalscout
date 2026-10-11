"""Resource, latency, and cost budget accounting."""

from __future__ import annotations

import math
import threading
import time
from typing import Counter, Dict, List, Optional


class BudgetTracker:
    """Thread-safe resource and budget tracker."""

    def __init__(self, declared_cost_usd: float = 0.0) -> None:
        self._lock = threading.Lock()
        self.total_requests: int = 0
        self.total_bytes: int = 0
        self.latencies_ms: List[float] = []
        self.domain_counts: Counter[str] = Counter()
        self.errors_count: int = 0
        self.declared_cost_usd: float = declared_cost_usd
        self.start_time: float = time.time()

    def record_request(self, domain: str, latency_ms: float, response_bytes: int, status_code: int = 200) -> None:
        with self._lock:
            self.total_requests += 1
            self.total_bytes += response_bytes
            self.latencies_ms.append(latency_ms)
            self.domain_counts[domain] += 1
            if status_code >= 400:
                self.errors_count += 1

    def elapsed_ms(self) -> int:
        return int((time.time() - self.start_time) * 1000)

    def summary(self) -> dict[str, int | float | None]:
        with self._lock:
            measured = sorted(self.latencies_ms)
            n = len(measured)
            p50 = measured[int(n * 0.50)] if n else None
            p95 = measured[min(n - 1, math.ceil(n * 0.95) - 1)] if n else None
            max_lat = measured[-1] if n else None

            return {
                "requests": self.total_requests,
                "bytes": self.total_bytes,
                "runtime_ms": self.elapsed_ms(),
                "third_party_cost_usd": self.declared_cost_usd,
                "p50_latency_ms": round(p50, 2) if p50 is not None else None,
                "p95_latency_ms": round(p95, 2) if p95 is not None else None,
                "max_latency_ms": round(max_lat, 2) if max_lat is not None else None,
                "errors_count": self.errors_count,
            }
