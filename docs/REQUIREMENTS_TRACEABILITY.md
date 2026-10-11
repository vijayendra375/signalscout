# Requirements Traceability Matrix — SignalScout

Maps each official Builderr Signalpost requirement to the implementing component
and the automated test that verifies it. Every test path below exists in the
repository and runs offline (no network, no API keys).

| ID | Official requirement | Implementation | Verification test |
| :--- | :--- | :--- | :--- |
| **REQ-01** | Accept a 9-digit Norwegian organisation number | `app.identity.validator.validate_org_number` | `tests/identity/test_validator.py` |
| **REQ-02** | Exactly one terminal envelope per input | `app.orchestrator.batch.BatchRunner.run_batch`, `app.output.serializer.validate_batch_envelopes` | `tests/batch/test_batch.py`, `tests/batch/test_schema_conformance.py` |
| **REQ-03** | Zero silent drops / unhandled exceptions across a batch | `app.orchestrator.batch.BatchRunner` (fault-isolated worker) | `tests/batch/test_batch.py` |
| **REQ-04** | Valid availability states | `app.output.models.AvailabilityState` | `tests/batch/test_schema_conformance.py` |
| **REQ-05** | Anchor identity in the official register | `app.sources.brreg.BrregAdapter` | `tests/sources/test_brreg_parsing.py` |
| **REQ-06** | Identity Firewall: reject same-name / conflicting entities | `app.identity.firewall.IdentityFirewall` | `tests/identity/test_firewall.py`, `tests/adversarial/test_adversarial.py` |
| **REQ-07** | Company-record extraction (name, form, address, NACE, employees) | `app.extraction.company_record.extract_company_record` | `tests/extraction/test_extractors.py` |
| **REQ-08** | Financial extraction + reported currency and period | `app.extraction.financials.extract_financials` | `tests/extraction/test_extractors.py`, `tests/sources/test_brreg_parsing.py` |
| **REQ-09** | Never convert missing numbers to zero; distinguish checked-empty vs unchecked | `app.verification.validator.create_claim_record` / `normalize_metric` | `tests/extraction/test_extractors.py`, `tests/extraction/test_activity.py` |
| **REQ-10** | People & workplaces (CEO, board, subunits) | `app.extraction.people_locations.extract_people_and_locations` | `tests/extraction/test_extractors.py`, `tests/extraction/test_people_locations.py` |
| **REQ-11** | Verified website, robots-compliant bounded crawl, contacts | `app.extraction.website.WebsiteExtractor`, `app.fetching.robots.RobotsGate` | `tests/sources/test_website_crawl.py`, `tests/resilience/test_robots.py` |
| **REQ-12** | Hiring & public activity (jobs, news, structured data) | `app.extraction.activity.extract_hiring_and_activity` | `tests/extraction/test_activity.py` |
| **REQ-13** | Immutable evidence with SHA-256 and verbatim spans | `app.evidence.store.EvidenceStore` | `tests/evidence/test_store.py` |
| **REQ-14** | Robust Brreg ingestion (JSON + XML fallback, no silent drops) | `app.sources.brreg.parse_brreg_payload` | `tests/sources/test_brreg_parsing.py` |
| **REQ-15** | Idempotent refresh & temporal diff (missing data is not a change) | `app.temporal.change_detector.ChangeDetector` | `tests/temporal/test_temporal.py`, `tests/temporal/test_change_detector.py` |
| **REQ-16** | Bounded HTTP client: SSRF defense, timeouts, retries, rate limits | `app.fetching.http_client.SafeHttpClient` | `tests/resilience/test_http.py`, `tests/adversarial/test_adversarial.py` |
| **REQ-17** | Grounded synthesis with explicit unknowns; optional model cannot invent numbers | `app.synthesis.synthesizer.Synthesizer`, `app.llm.provider.is_grounded` | `tests/llm/test_provider.py` |
| **REQ-18** | 100-company smoke test with machine- and human-readable reports | `scripts/smoke_100.py` | Run: `python scripts/smoke_100.py` (produces `out/smoke_100_report.json`) |
| **REQ-19** | $0 third-party cost accounting | `app.budget.tracker.BudgetTracker` | `tests/resilience/test_cost_tracker.py` |
| **REQ-20** | Clean-machine single run command | `run.py` / `python -m app.cli` | README section 4; `python run.py --help` |

## Notes on status

- All 69 automated tests pass offline: `python -m pytest -q`.
- REQ-18 is exercised by a live 100-company smoke run; the committed machine
  report is `out/smoke_100_report.json` and the human summary is
  `out/smoke_100_summary.md`.
- A model provider is intentionally **optional** (REQ-17). The default is fully
  deterministic; the numeric grounding guard is unit-tested.
