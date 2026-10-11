# Test Plan & Quality Assurance — SignalScout

SignalScout follows a comprehensive, multi-tiered test strategy designed to guarantee contract compliance, adversarial resilience, and clean-machine reproducibility.

## 1. Test Suite Taxonomy

| Suite | Focus | Target Location |
| :--- | :--- | :--- |
| **Unit: Identity** | Org number validation (Mod 11 checksum), normalization, name matching | `tests/identity/` |
| **Unit: Evidence** | SHA-256 hash calculation, citation span generation, immutability | `tests/evidence/` |
| **Unit: Extraction** | HTML/PDF table normalization, currency, date parsing, non-zero handling | `tests/extraction/` |
| **Adversarial: Identity** | Same-name entities, renamed entities, subsidiaries, parent confusion | `tests/adversarial/` |
| **Resilience & Faults** | HTTP 429 backoff, HTTP 500 retries, timeouts, SSRF defense, memory caps | `tests/resilience/` |
| **Batch Invariants** | Equal input/output envelopes, zero silent drops, unique org IDs, valid states | `tests/batch/` |
| **Temporal: Refresh** | Idempotency on unchanged sources, detecting genuine new/modified facts | `tests/temporal/` |
| **End-to-End: Smoke 100** | Full pipeline execution across 100 companies with machine report generation | `scripts/smoke_100.py` |

## 2. Adversarial Scenarios Covered
1. **Wrong-Company Traps**:
   - Two companies with similar names in different municipalities.
   - A holding parent company vs. operating subsidiary with shared brand names.
   - Historical company names that changed after corporate restructuring.
2. **Missing vs. Zero Values**:
   - A newly established holding company with 0 employees or missing annual accounts. Verify output produces `not_available` / `not_applicable` instead of `0`.
3. **Network Disruptions**:
   - Connection drops, DNS failure, 10-second server hang. Verify company receives `failed` envelope without aborting remaining batch.
4. **SSRF & Security Attacks**:
   - Company website pointing to `127.0.0.1`, `169.254.169.254`, or internal private subnets (`10.0.0.0/8`, `192.168.0.0/16`). Verify request is safely blocked with `blocked` state.

## 3. Acceptance Verification Criteria
- `100%` pass rate on all unit, integration, and adversarial tests.
- 100-company smoke test completes with exactly 100 valid terminal envelopes.
- Clean machine test verifies zero external undeclared dependencies.
