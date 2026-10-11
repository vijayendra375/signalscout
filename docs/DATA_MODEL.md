# Internal and External Data Model — SignalScout

SignalScout maintains strongly typed internal models (using Pydantic) that serialize into the exact official evaluation envelope required by the Builderr challenge.

## 1. Output Contract Schema (External)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "SignalpostTerminalEnvelope",
  "type": "object",
  "required": ["organisation_number", "run", "claims", "evidence", "changes", "errors", "operations"],
  "properties": {
    "organisation_number": { "type": "string", "pattern": "^[0-9]{9}$" },
    "run": {
      "type": "object",
      "required": ["run_id", "started_at", "completed_at", "terminal_status"],
      "properties": {
        "run_id": { "type": "string" },
        "started_at": { "type": "string", "format": "date-time" },
        "completed_at": { "type": "string", "format": "date-time" },
        "terminal_status": { "type": "string", "enum": ["completed", "failed", "partial"] }
      }
    },
    "claims": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["field", "value", "availability", "confidence", "evidence_ids"],
        "properties": {
          "field": { "type": "string" },
          "value": {},
          "availability": {
            "type": "string",
            "enum": ["available", "not_available", "blocked", "not_applicable", "ambiguous", "failed"]
          },
          "confidence": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
          "evidence_ids": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "evidence": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "source_url", "source_class", "retrieved_at", "content_sha256", "claim_span"],
        "properties": {
          "id": { "type": "string" },
          "source_url": { "type": "string" },
          "source_class": { "type": "string", "enum": ["official_registry", "company_owned", "licensed_external", "public_web"] },
          "retrieved_at": { "type": "string", "format": "date-time" },
          "content_sha256": { "type": "string" },
          "claim_span": { "type": "string" }
        }
      }
    },
    "changes": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["field", "old_value", "new_value", "detected_at"],
        "properties": {
          "field": { "type": "string" },
          "old_value": {},
          "new_value": {},
          "detected_at": { "type": "string", "format": "date-time" },
          "materiality": { "type": "string" }
        }
      }
    },
    "errors": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["code", "message"],
        "properties": {
          "code": { "type": "string" },
          "message": { "type": "string" },
          "timestamp": { "type": "string", "format": "date-time" }
        }
      }
    },
    "operations": {
      "type": "object",
      "required": ["requests", "runtime_ms", "third_party_cost_usd"],
      "properties": {
        "requests": { "type": "integer", "minimum": 0 },
        "runtime_ms": { "type": "integer", "minimum": 0 },
        "third_party_cost_usd": { "type": "number", "minimum": 0.0 }
      }
    }
  }
}
```

## 2. Core Internal Models

- **`CompanyIdentity`**: Anchored org number, legal name, alternate trade names, address, status, NACE code, website candidate, confidence score.
- **`FactRecord`**: Field key, normalized value, raw value, unit/currency, fiscal year, reporting period (`start_date`, `end_date`), evidence pointers.
- **`EvidenceRecord`**: Source URL, canonical URL, SHA-256 hash, HTTP status, retrieval timestamp, verbatim citation text, selector/page.
- **`FinancialRecord`**: Fiscal year, reporting period, revenue (`driftsinntekter`), operating profit (`driftsresultat`), profit before tax, annual net profit, total assets, equity, debt, currency (NOK).
- **`LeadershipRole`**: Full name, role code/title, date of entry, active status.
- **`WorkplaceSubunit`**: Org number, subunit name, municipality, employee count.
- **`PublicActivityRecord`**: Category (`job_posting`, `news_release`, `partnership`, `filing`), title, summary, publication date, source URL.
- **`TemporalChange`**: Field, old value, new value, timestamp, material change classification.
