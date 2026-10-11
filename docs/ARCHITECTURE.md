# System Architecture — SignalScout

SignalScout is an autonomous, evidence-backed Norwegian company intelligence agent. It is designed around deterministic verification, strict identity containment, and complete evidence reproducibility.

## 1. High-Level Pipeline

```mermaid
flowchart LR
    In[Batch Input] --> Val[Org Validator]
    Val --> IdFw[Identity Firewall]
    IdFw --> Brreg[Brreg Official Adapter]
    Brreg --> Disc[Source Discovery & Router]
    Disc --> Fetch[Safe HTTP Fetcher]
    Fetch --> Parse[HTML / PDF Parsers]
    Parse --> Extr[Category Extractors]
    Extr --> EvStore[Evidence Store]
    EvStore --> FactVal[Fact Validator]
    FactVal --> TempDiff[Temporal Change Detector]
    TempDiff --> Synth[Factual Synthesizer]
    Synth --> Ser[Contract Output Serializer]
    Ser --> Out[Batch JSONL Envelopes]
```

## 2. Key Modules & Separation of Concerns

1. **`app.config`**:
   - Central configuration: request timeouts, rate limits, retry policies, max concurrency, logging settings.
2. **`app.budget`**:
   - Centrally enforces time budgets, per-company request limits, bandwidth ceilings, and zero-dollar cost accounting.
3. **`app.identity`**:
   - `validator`: Validates 9-digit Norwegian organisation numbers with Modulus 11 checksum.
   - `firewall`: Compares candidate documents, URLs, and snippets against official identity anchors (exact org number, exact legal name, postal address, management). Quarantines ambiguous entities and outright rejects subsidiaries/parents as false positives.
4. **`app.sources`**:
   - Registry and router for permitted sources: Brønnøysundregistrene (Enhetsregisteret, Regnskapsregisteret, Roller, Underenheter, Konsernstruktur), verified websites, open feeds.
5. **`app.fetching`**:
   - `SafeHttpClient`: Requests with exponential backoff and jitter, thread-local connection pooling, user-agent compliance, per-domain rate limiting (Brreg respects `brreg_rate_limit_per_second`), URL sanitization, SSRF protection (loopback/private IP rejection), and response size limits (max 10MB). Maintains a per-thread outbound request counter for accurate `operations.requests`.
   - `robots`: `RobotsGate` fetches and caches `robots.txt` and enforces crawl permission before any subpage request.
6. **`app.documents`**:
   - Text, metadata, tables, contact details and JSON-LD parsing from HTML (BeautifulSoup, trafilatura, lxml) and PDF (pypdf). Removes boilerplate.
7. **`app.extraction`**:
   - Specialized modular extractors across all 5 scorer-facing families:
     1. Company record (registry identifiers, form, status, NACE, employees)
     2. Financials (multi-year revenue, operating result, net income, assets, equity, debt, reporting periods, currency)
     3. People & Locations (roles: daglig leder, styreleder, styremedlemmer; operating subunits)
     4. Website & Digital Footprint (homepage + bounded subpage/sitemap crawl, meta, contacts, declared social handles)
     5. Hiring & Public Activity (JSON-LD job postings, news/press, career-page heuristics) — wired from the crawled pages
   - The `website` extractor aggregates per-page evidence so every activity/contact claim cites the exact page that proved it.
8. **`app.evidence`**:
   - Stores raw snapshot content hashes (SHA-256), canonical source URLs, retrieval timestamps, and exact verbatim text spans.
9. **`app.verification`**:
   - Fact normalization (currencies in NOK, metric units, calendar date normalization).
   - Enforces the non-zero rule: missing financials are tagged `not_available` or `not_applicable`, never numeric 0.
10. **`app.temporal`**:
    - Compares current extracted claims against previous snapshots. Computes idempotent field-level diffs, material changes, and suppresses false positives.
11. **`app.synthesis`**:
    - Synthesizes concise company summaries, key highlights, recent developments, and explicit unknowns. Strictly constrained to validated facts; cannot introduce hallucinated claims.
12. **`app.output`**:
    - Serializes outputs into the exact contract JSON envelope. Validates batch completeness: exactly one terminal envelope per input company with zero silent drops.
13. **`app.orchestrator`**:
    - Multi-threaded batch controller with fault isolation. A failure or timeout on one company never terminates the batch.
14. **`app.ui`**:
    - Standalone interactive evidence dashboard for desktop and mobile inspection.
15. **`app.llm`** (optional):
    - `provider`: environment-configurable provider abstraction. Default is the
      deterministic no-op; an explicit OpenAI-compatible endpoint may be enabled.
      A numeric grounding guard rejects any model text that introduces a number
      absent from validated facts. SignalScout never auto-selects a paid service.
