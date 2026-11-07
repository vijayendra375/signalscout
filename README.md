# SignalScout

SignalScout is an evidence-backed, deterministic Norwegian company-intelligence
agent built for the **Builderr Signalpost** challenge. Given a Norwegian
organisation number it anchors identity in the official Brønnøysund registries,
collects permitted public evidence, attaches a source URL, retrieval timestamp
and SHA-256 content hash to every published claim, and emits exactly one
terminal JSONL envelope per input.

- **Total third-party cost:** $0.00 (no paid APIs, no paid model required).
- **Zero wrong-company publications:** enforced by an Identity Firewall.
- **Honest absence:** missing data is `not_available`, never a fabricated `0`.
- **Offline-testable:** the test suite makes no network calls and needs no keys.

## 1. Requirements

- Python 3.10+ (verified on 3.14)
- No API keys, accounts, or paid services

## 2. Install

```bash
python -m pip install -r requirements.txt
# For the test suite:
python -m pip install -r requirements-dev.txt
```

## 3. Configure (optional)

All settings have safe defaults and are environment-overridable. Copy the
placeholder file to create a local, ignored `.env` and edit as needed:

```bash
copy .env.example .env     # Windows
# cp .env.example .env      # macOS / Linux
```

No secret values are stored in this repository. If you enable the optional
model provider, export the key in your shell (never commit it):

```bash
set SIGNALSCOUT_MODEL_API_KEY=...        # Windows
# export SIGNALSCOUT_MODEL_API_KEY=...   # macOS / Linux
```

## 4. Run (one documented command)

The evaluator command accepts a JSON array, JSONL, or plain-text batch of
organisation numbers and writes envelopes plus a machine-readable report:

```bash
python run.py --input data/smoke_100_companies.jsonl \
              --output out/envelopes.jsonl \
              --report out/report.json \
              --dashboard out/dashboard.html \
              --run-id eval-2026-10-17-a
```

Useful flags: `--workers N` (bounded concurrency), `--expected-count N`
(assert batch size), `--resume` (continue an interrupted run from `--output`).

Run a batch of any size (1,000+) the same way:

```bash
python run.py --input my-1000-companies.jsonl \
              --output out/envelopes-1000.jsonl \
              --report out/report-1000.json \
              --run-id local-1000 \
              --expected-count 1000 \
              --resume
```

Input formats accepted:

```jsonc
// JSON array
[{"organisation_number": "923609016"}]
// JSONL
{"organisation_number": "923609016"}
// Plain text
923609016
```

## 5. The 100-company smoke test

```bash
python scripts/smoke_100.py \
  --input data/smoke_100_companies.jsonl \
  --output out/smoke_100_envelopes.jsonl \
  --report out/smoke_100_report.json \
  --summary out/smoke_100_summary.md
```

This writes a machine-readable report, a human-readable summary, one dashboard
HTML file, and 100 terminal envelopes. The committed report and summary live in
`out/`.

## 6. Test

```bash
python -m pytest -q
```

The suite is fully offline (mocked HTTP and fixtures) and must not require paid
access.

## 7. Submission preflight audit

Before packaging a competition run, validate the exact manifest, output JSONL,
and machine report. For the included smoke manifest:

```bash
python scripts/audit_submission.py --input data/smoke_100_companies.jsonl --expected-count 100
```

For an official run, audit the exact input file Builderr supplies and the
matching output/report from that same run. Set `--expected-count` to the
actual number of supplied companies; do not substitute a self-selected list:

```bash
python scripts/audit_submission.py --input <builderr-input.jsonl> --expected-count N --output out/evaluator.jsonl --report out/evaluator-report.json
```

Builderr's current challenge page requires a 100-company smoke-test artifact
and supplies the official evaluation batch itself. Precomputed profiles are
not a substitute for running the agent on that supplied batch.

The audit checks valid unique organisation numbers, exact input/output order,
terminal-envelope invariants, claim-to-evidence references, evidence hashes and
timestamps, and configured request/runtime/cost ceilings. It is an offline
structural preflight; it does **not** prove recall, source freshness, legal
permission, or zero wrong-company matches. Those require a live evidence audit.

## 8. Output contract

Each input produces exactly one terminal envelope:

```json
{
  "organisation_number": "989061593",
  "run": {"run_id": "...", "started_at": "...", "completed_at": "...", "terminal_status": "completed"},
  "claims": [{"field": "latest_revenue", "value": 20000.0, "availability": "available", "confidence": 1.0, "evidence_ids": ["ev-3"]}],
  "evidence": [{"id": "ev-3", "source_url": "https://data.brreg.no/...", "source_class": "official_registry", "retrieved_at": "...", "content_sha256": "...", "claim_span": "..."}],
  "changes": [],
  "errors": [],
  "operations": {"requests": 13, "runtime_ms": 8123, "third_party_cost_usd": 0.0}
}
```

Allowed availability states: `available`, `not_available`, `blocked`,
`not_applicable`, `ambiguous`, `failed`. A source that was checked but contained
nothing (e.g. zero job postings) yields `available` with an empty value, which is
distinct from a source that was not checked (`not_available`).

See `docs/EVALUATION_CONTRACT.md`, `docs/DATA_MODEL.md` and
`docs/REQUIREMENTS_TRACEABILITY.md` for the full specification.

## 9. Sources & evidence policy (summary)

- **Tier 1 — official registry:** Brønnøysundregistrene (Enhetsregisteret,
  Roller, Underenheter, Konsernstruktur, Regnskapsregisteret). JSON is requested
  explicitly, with an XML fallback parser so no source is silently dropped.
- **Tier 2 — company-owned sites:** the registry-listed domain, verified through
  the Identity Firewall, crawled within a bounded page budget and honouring
  `robots.txt`.
- **Prohibited:** login-walled platforms, CAPTCHA/bot-detection evasion,
  `robots.txt` violations, and search snippets as sole evidence.

Every element of a fetched page is treated as untrusted data; instructions
embedded in pages are ignored. See `docs/PERMITTED_SOURCES.md`,
`docs/SOURCE_STRATEGY.md` and `docs/THREAT_MODEL.md`.

### Evidence record schema

| Field | Meaning |
| :--- | :--- |
| `id` | Stable per-envelope identifier referenced by claims |
| `source_url` | Canonical URL the fact was read from |
| `source_class` | `official_registry` \| `company_owned` \| `licensed_external` \| `public_web` |
| `retrieved_at` | ISO-8601 UTC retrieval timestamp |
| `content_sha256` | SHA-256 of the exact retrieved bytes |
| `claim_span` | Verbatim excerpt or structured field proving the fact |

## 10. Model / provider

The pipeline is **deterministic by default** and requires no model.
`SIGNALSCOUT_MODEL_PROVIDER=deterministic` (default) does no network I/O. An
optional OpenAI-compatible endpoint may be enabled explicitly via
`SIGNALSCOUT_MODEL_BASE_URL` / `SIGNALSCOUT_MODEL_NAME`; it is used only to
rephrase already-validated facts and is rejected if it introduces any number not
present in the validated facts. SignalScout never silently switches to a paid
service.

## 11. Cost

| Component | Provider | Cost per 100 | Cost per 1,000 |
| :--- | :--- | :--- | :--- |
| Registry & accounts | Brreg public APIs | $0.00 | $0.00 |
| Website / feeds | Direct HTTP | $0.00 | $0.00 |
| Synthesis | Deterministic | $0.00 | $0.00 |
| **Total** | | **$0.00** | **$0.00** |

`operations.third_party_cost_usd` is reported as `0.0`; run-level request counts
and latency percentiles are in the JSON report. See `docs/COST_MODEL.md`.

## 12. Known limitations

- Financial figures reflect the currency reported by Regnskapsregisteret (may be
  USD/EUR for some large groups); the currency is emitted alongside the figures.
- Website intelligence depends on a registry-registered `hjemmeside`; companies
  without one correctly return `not_available` for website/activity categories.
- Only structured/machine-readable job and news signals plus on-page career
  heuristics are collected; login-walled job boards are intentionally excluded.
- The `narrative` field is absent unless an optional model provider is enabled.

## 13. Project layout

```
app/            package (identity, sources, fetching, extraction, evidence,
                verification, temporal, synthesis, output, orchestrator, ui, llm)
scripts/        smoke_100.py (100-company smoke run)
data/           smoke input manifest
docs/           architecture, rules, source policy, data model, cost, test plan
tests/          offline unit + adversarial suites
run.py          evaluator entry point
```
