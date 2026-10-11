# Evaluation Contract — SignalScout

## 1. Input Specification
The evaluation harness feeds an input batch of Norwegian organisation numbers in one of three standard formats:
1. JSON array of objects: `[{"organisation_number": "923609016"}, ...]`
2. JSON Lines (JSONL): `{"organisation_number": "923609016"}\n...`
3. Plain text: 9-digit numbers one per line.

Each organisation number is verified as a 9-digit string satisfying the Norwegian Modulus 11 control digit algorithm:
$$\text{Control Digit} = 11 - \left(\sum_{i=1}^{8} d_i \cdot w_i \pmod{11}\right)$$
Weights: $[3, 2, 7, 6, 5, 4, 3, 2]$.

## 2. Output Specification
The agent outputs one terminal JSON envelope per organisation number in strict JSONL format:

```json
{
  "organisation_number": "123456789",
  "run": {
    "run_id": "eval-2026-10-11-a",
    "started_at": "2026-10-11T15:00:00Z",
    "completed_at": "2026-10-11T15:00:05Z",
    "terminal_status": "completed"
  },
  "claims": [
    {
      "field": "official_website",
      "value": "https://example.no/",
      "availability": "available",
      "confidence": 0.99,
      "evidence_ids": ["ev-1"]
    }
  ],
  "evidence": [
    {
      "id": "ev-1",
      "source_url": "https://example.no/",
      "source_class": "company_owned",
      "retrieved_at": "2026-10-11T15:00:02Z",
      "content_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "claim_span": "Example AS, org.nr. 123 456 789"
    }
  ],
  "changes": [],
  "errors": [],
  "operations": {
    "requests": 4,
    "runtime_ms": 4210,
    "third_party_cost_usd": 0
  }
}
```

### Mandatory Fields & Enveloping Invariants
1. `organisation_number` (string, 9 digits).
2. `run`: Object with `run_id`, `started_at` (ISO 8601 UTC), `completed_at` (ISO 8601 UTC), `terminal_status` (`completed` | `failed` | `partial`).
3. `claims`: List of validated claims. Each claim has:
   - `field`: string
   - `value`: primitive, dict, or list
   - `availability`: `available` | `not_available` | `blocked` | `not_applicable` | `ambiguous` | `failed`
   - `confidence`: float between 0.0 and 1.0
   - `evidence_ids`: list of string references matching `evidence[].id`
4. `evidence`: List of immutable evidence records:
   - `id`: string
   - `source_url`: canonical URL
   - `source_class`: `official_registry` | `company_owned` | `licensed_external` | `public_web`
   - `retrieved_at`: ISO 8601 UTC timestamp
   - `content_sha256`: hexadecimal SHA-256 hash
   - `claim_span`: excerpt or verbatim text span proving the fact
5. `changes`: List of detected temporal changes compared to prior snapshot:
   - `field`, `old_value`, `new_value`, `detected_at`, `materiality`
6. `errors`: List of diagnostic error descriptors without breaking batch execution.
7. `operations`:
   - `requests`: integer count of HTTP/network requests
   - `runtime_ms`: integer wall-clock latency in milliseconds
   - `third_party_cost_usd`: float external API cost (must be 0.0 for zero-cost operation)

## 3. Strict Batch Invariants
- Envelopes emitted == Input organisation count.
- Zero silent drops.
- Zero duplicate organisation numbers in output.
- Every non-trivial claim must reference at least one valid evidence ID.
- Missing fields must have availability `not_available`, `not_applicable`, `blocked`, or `ambiguous` — never fabricated numeric zero.
