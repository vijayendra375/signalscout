# Official Rules — Builderr Signalpost Hackathon

## 1. Challenge Overview
- **Challenge Title**: Signalpost Company Intelligence Challenge
- **Platform**: Builderr (https://builderr.ai/challenges/signalpost)
- **Primary Goal**: Given a Norwegian organisation number (9 digits), research the company, discover verified public information across official filings, company-owned sources, and permitted external sources, preserve source evidence, detect temporal changes, and emit structured result envelopes.
- **Universe**: 411,160 Norwegian entities with 2025 annual-account records.
- **Local Testing**: 100-company smoke test required in the submitted artifact.
- **Evaluation Mechanism**: Evaluator runs all submissions against the same official frozen company batch (1,000 to 1,100 companies).

## 2. Hard Deadlines and Constraints
- **Builder Hard Submission Deadline**: October 17, 2026, at 9:00 PM IST.
- **Platform Round 1 Cutoff**: October 21, 2026.
- **Budget**: ₹0 / $0 required third-party cost.
- **Zero Fabricated Claims**: Zero wrong-entity publications and zero fabricated financial values are mandatory qualification gates.

## 3. Scoring Breakdown (100 Points Total)
- **Recall and Coverage (50 points)**:
  - For each information category, coverage is calculated as `70% * (company recall) + 30% * (individual claims recall)` against the union of verified discoveries.
  - Categories:
    1. Company record (registry, legal name, address, employee count, NACE code, form)
    2. Financials (revenue, operating result, net profit, balance sheet assets/equity/debt)
    3. People and locations (management roles: CEO/daglig leder, board chair/members; operating subunits/workplaces)
    4. Company website (verified website URL, sitemap, meta descriptions, contact details)
    5. Hiring and public activity (job postings, careers page, news/announcements, press releases, social profiles)
- **Precision, Identity & Evidence (30 points)**:
  - Exact legal identity matching.
  - Claim-level source attribution, retrieval timestamp, content hash, reporting period.
  - Zero wrong-company matches.
- **Synthesis (12 points)**:
  - Overview, key metrics, verified recent changes, explicit unknowns and uncertainties.
  - Every substantive claim cited to verified evidence.
- **User Experience (8 points)**:
  - Clean, responsive desktop and mobile verification interface.
  - Inspection of evidence links, reporting periods, and filters.

## 4. Qualification Requirements
- **Qualification Threshold**: Overall score of at least 65/100 on an official run.
- **Batch Completeness Invariant**: Exactly one terminal envelope per input organisation number:
  $$\text{Count}(\text{inputs}) == \text{Count}(\text{terminal envelopes})$$
- **Allowed States**: `available`, `not_available`, `blocked`, `not_applicable`, `ambiguous`, `failed`.
- **Honest Absence**: Never substitute zero for missing values. Missing information must be represented explicitly.
- **Idempotency**: Repeated runs on identical source snapshots must produce zero false changes and zero duplicate records.

## 5. Permitted Sources & Legal Compliance
- Official registers: Brønnøysundregistrene (Enhetsregisteret, Regnskapsregisteret, Roller, Underenheter, Konsernstruktur).
- Company-controlled sites: Verified homepage, about, contact, leadership, jobs, news.
- Permitted external sources: Public APIs, lawful search discovery, RSS feeds, open company directories conforming to robots.txt and terms of service.
- Prohibited: Scraped unauthorized closed platforms, CAPTCHA bypass, credential theft, private competitor work.
