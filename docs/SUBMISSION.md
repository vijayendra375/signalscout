# Submission Guide & Deliverables Checklist — SignalScout

## 1. Submission Overview
- **Challenge**: Builderr Signalpost Hackathon
- **Agent**: SignalScout
- **Submission destination**: `submit@builderr.ai`
- **Third-party cost**: $0.00 (no paid APIs; deterministic by default)

## 2. Official evaluator run command

```bash
python run.py --input <input-file> --output <output-file> --report <report-file>
```

Accepts JSON array, JSONL, or plain-text batches of organisation numbers. Emits
exactly one terminal JSONL envelope per input plus a machine-readable report.

## 3. Deliverables checklist

- [x] Pinned dependencies (`requirements.txt`, `pyproject.toml`) and reproducible setup.
- [x] Official input/output contracts implemented (`docs/EVALUATION_CONTRACT.md`).
- [x] Identity Firewall rejecting same-name / conflicting entities.
- [x] Coverage across all five categories (company record, financials, people &
  locations, website, hiring & public activity).
- [x] Immutable evidence chains with SHA-256 and verbatim spans.
- [x] Idempotent refresh / temporal change detection (missing data is never a change).
- [x] 100-company smoke test with machine report (`out/smoke_100_report.json`) and
  human summary (`out/smoke_100_summary.md`).
- [x] Previous-snapshot → material-change path (`scripts/diff_snapshots.py`).
- [x] Reproducible one-command execution (`python run.py ...`).
- [x] Declared models/APIs and source-rights assumptions (`docs/PERMITTED_SOURCES.md`,
  `docs/SOURCE_STRATEGY.md`, `docs/THREAT_MODEL.md`).
- [x] $0 third-party cost accounting.

## 4. Reproduction

```bash
python -m pip install -r requirements.txt
python -m pytest -q                          # offline regression suite
python scripts/smoke_100.py                  # live 100-company smoke test
python scripts/diff_snapshots.py \
  --previous out/smoke_100_envelopes.jsonl \
  --current  out/smoke_100_envelopes.jsonl \
  --output   out/changes.json                # idempotency: 0 changes
python run.py --input data/smoke_100_companies.jsonl \
  --output out/envelopes.jsonl --report out/report.json
```

## 5. Final preflight audit

Run the structural preflight against the exact evaluator input and outputs:

```bash
python scripts/audit_submission.py \
  --input <evaluator-input.jsonl> \
  --expected-count 1000 \
  --output <evaluator-output.jsonl> \
  --report <evaluator-report.json>
```

Use the evaluator's actual frozen batch size (the official rules specify 1,000
to 1,100 records); do not manufacture a substitute dataset. A passing preflight
checks structural integrity and declared limits, not information recall or
source correctness. Those still require separate review.

## 6. Model / API declaration
- Registry data: Brønnøysundregistrene public REST APIs (no auth).
- Websites: direct, robots-compliant HTTP; no login-walled scraping.
- Model: none required. Optional OpenAI-compatible provider is opt-in and never
  selected automatically.
