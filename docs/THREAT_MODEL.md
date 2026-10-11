# Threat Model & Security Policy — SignalScout

SignalScout retrieves and processes external content from public websites and APIs. The following security architecture mitigates adversarial and operational risks.

## 1. Threats & Mitigations

### 1. Server-Side Request Forgery (SSRF)
- **Threat**: Malicious websites, redirected URLs, or adversarial registry entries could redirect outbound HTTP requests to internal networks (e.g. cloud metadata services `169.254.169.254`, localhost `127.0.0.1`, private IP blocks `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`).
- **Mitigation**: `SafeHttpClient` enforces DNS pre-resolution and IP address validation before establishing any socket connection. Any private, loopback, or multicast IP address raises a security violation and marks the source `blocked`.

### 2. Prompt Injection & Malicious HTML Payloads
- **Threat**: Adversarial web pages containing prompt injections designed to hijack LLM synthesis or corrupt structured JSON outputs.
- **Mitigation**:
  - Fact extraction is primarily deterministic (regex, HTML DOM selectors, JSON-LD schema parsing).
  - LLM synthesis receives only validated, typed facts (`FactRecord`), never raw untrusted HTML.
  - Strict Pydantic output validation prevents unauthorized field injection.

### 3. Denial of Service (ReDoS, Decompression Bombs, Giant Files)
- **Threat**: Web servers returning infinite streams, giant PDF files, or gzip bombs to exhaust memory and CPU.
- **Mitigation**:
  - Response size limit enforced via streaming chunks: maximum 10 MB per download.
  - Strict socket read timeouts (5.0 seconds).
  - Maximum 5 page hops per domain to avoid crawl loops.

### 4. Credential & Secret Leaks
- **Threat**: Accidental leakage of environment variables, local auth tokens, or private developer keys in emitted JSON envelopes or logs.
- **Mitigation**:
  - Zero-cost architecture operates completely without proprietary API keys.
  - Diagnostic logs redact Authorization headers and sensitive environment variables.
  - Repository includes strict `.gitignore` preventing any `.env` or credential files from entering version control.
