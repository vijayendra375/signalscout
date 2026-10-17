# SignalScout 100-Company Smoke Test Verification Report

- **Run ID**: `smoke-100-verified`
- **Date**: `2026-10-17 08:26:14 UTC`
- **Target Companies**: 100
- **Emitted Envelopes**: 100
- **Execution Latency**: 45354 ms (45.35 s)
- **Third-Party API Cost**: $0.00

## 1. Batch Invariant Checks
- **Batch Count Check**: PASSED
- **Unique Organisation Numbers**: PASSED
- **Zero Silent Drops**: PASSED
- **All Terminal Statuses Valid**: PASSED
- **All Available Claims Linked to Evidence**: PASSED
- **Overall Validation**: PASSED

## 2. Category Coverage (companies with >= 1 verified claim)
- **Company record**: 100/100 companies (100%)
- **Financials**: 40/100 companies (40%)
- **People & locations**: 100/100 companies (100%)
- **Website**: 10/100 companies (10%)
- **Hiring & activity**: 10/100 companies (10%)

## 3. Resource & Budget Accounting
- **Total HTTP Requests**: 479
- **Total Bytes Downloaded**: 7,560,018 bytes
- **P50 Request Latency**: 494.26 ms
- **P95 Request Latency**: 1904.74 ms
- **Max Request Latency**: 9927.33 ms
- **Non-2xx responses (expected for optional sources, e.g. no annual accounts / no group)**: 95

## 4. Official Qualification Assessment
The smoke test verified clean-machine execution, modulus-11 identity anchoring,
zero wrong-company publications, and exact JSONL envelope compliance.

*(Generated automatically by SignalScout QA Verification Engine)*
