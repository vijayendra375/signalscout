# Source Strategy — SignalScout

SignalScout implements a strict, prioritized "Source Ladder" complying with Norwegian and European data access regulations, website Terms of Service, and the Signalpost challenge contract.

## 1. The Source Ladder

```
[Tier 1: Official Registers]
       ↓ (100% authoritative identity anchor)
[Tier 2: Company-Owned Domains]
       ↓ (Verified via Identity Firewall)
[Tier 3: Structured Metadata & Embedded Feeds]
       ↓ (JSON-LD, Microdata, RSS)
[Tier 4: Permitted Open External Directories]
       ↓ (Used strictly where compliant with robots.txt)
[Tier 5: Search Engines for Candidate Discovery Only]
       (Never used as sole factual evidence)
```

## 2. Source Declarations & Adapters

### Tier 1: Brønnøysundregistrene (Brreg)
- **Authority**: Highest (official government registry).
- **Access Method**: Official public REST APIs (`https://data.brreg.no/...`).
- **Endpoints**:
  - `enheter/{org}`: Basic company info.
  - `enheter/{org}/roller`: Management and board members.
  - `regnskap/{org}`: Annual accounts.
  - `underenheter?overordnetEnhet={org}`: Workplaces.
  - `konsernstruktur/{org}`: Group structure.
- **Authentication**: None required.
- **Rate Limit**: Conservative, gentle concurrency (5-10 requests/sec with exponential backoff on HTTP 429).

### Tier 2: Company-Controlled Website
- **Authority**: High for operational details, contact, careers, and self-description.
- **Access Method**: HTTP GET on public HTML endpoints.
- **Rules**:
  - Verify identity first: exact org number, matching name, or matching address/phone on page.
  - Parse `robots.txt` before deep crawling.
  - Timeout: 5.0 seconds per page.
  - Maximum 5 bounded pages per domain (`/`, `/om-oss`, `/kontakt`, `/ledelse`, `/karriere`).

### Tier 3: Structured Feeds & RSS
- Company RSS/Atom feeds (for company announcements and news).
- Open corporate press releases with traceable URLs.

### Prohibited Platforms
- Direct automated scraping of LinkedIn, Meta, Indeed, Glassdoor without licensed credentials is prohibited.
- Declared profile URLs found on verified company websites are recorded as company-declared social assets, but not scraped via unauthorized headless sessions.
