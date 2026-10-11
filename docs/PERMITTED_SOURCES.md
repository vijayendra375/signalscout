# Permitted Sources Policy — SignalScout

SignalScout strictly complies with the Builderr Signalpost Hackathon source policy. Discovery is rewarded only when the resulting evidence is lawful, reproducible, and verifiably attributable to the target legal entity.

## 1. Primary Authoritative Tier: Official Norwegian Registers
All identity resolution begins at official Norwegian state registries provided by Brønnøysundregistrene (Brreg):

| Endpoint / Source | Resource | Purpose |
| :--- | :--- | :--- |
| `https://data.brreg.no/enhetsregisteret/api/enheter/{org}` | Central Coordinating Register for Legal Entities | Legal name, org form (`organisasjonsform`), registered office (`forretningsadresse`), NACE industry code (`naeringskode1`), employee count (`antallAnsatte`), official registered website (`hjemmeside`), registration date. |
| `https://data.brreg.no/enhetsregisteret/api/enheter/{org}/roller` | Register of Business Enterprises Roles | Board of directors (`styremedlemmer`, `styreleder`), General Manager / CEO (`dagligLeder`), Auditors, Signatories. |
| `https://data.brreg.no/regnskapsregisteret/regnskap/{org}` | Register of Company Accounts | Filed annual accounts (`aarsregnskap`), revenue (`driftsinntekter`), operating profit (`driftsresultat`), ordinary profit before tax (`ordinaertResultatFoerSkattekostnad`), annual result (`aarsresultat`), balance sheet (`eiendeler`, `egenkapital`, `gjeld`), accounting period dates (`fraDato`, `tilDato`), currency. |
| `https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={org}` | Subunit Registry | Operating workplaces (`bedrifter`), physical branches, subunit employee counts. |
| `https://data.brreg.no/enhetsregisteret/api/konsernstruktur/{org}` | Corporate Group Structure | Ultimate parent entity, immediate parent entity, domestic subsidiaries. |
| `https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org}/aar` | Annual Report Copies | Historical filing years. |

## 2. Secondary Tier: Company-Controlled Sources
Once the official website is verified through the Identity Firewall:
- Verified Homepage & Sitemap (`/sitemap.xml`, `/robots.txt`).
- Standard informational sections:
  - `/om-oss`, `/about`, `/about-us`
  - `/kontakt`, `/contact`
  - `/ledelse`, `/leadership`, `/team`
  - `/karriere`, `/careers`, `/ledige-stillinger`, `/jobs`
  - `/nyheter`, `/news`, `/press`, `/presse`
  - `/investor`, `/investor-relations`
- Embedded structured metadata (JSON-LD Schema.org, OpenGraph, Microdata).
- Company-controlled outbound social links explicitly declared on the verified website.

## 3. Tertiary Tier: Permitted Public Web & Open APIs
- Open news feeds and public RSS feeds (e.g. Google News RSS for corporate announcements).
- Open company directories conforming to `robots.txt` and permissive Terms of Service.
- Public search engines (used strictly for URL candidate generation; never as sole factual evidence).

## 4. Prohibited Sources & Scrapers
- No unauthorized scraping of login-walled or anti-scraping platforms (e.g., unofficial LinkedIn scrapers, Meta, Glassdoor, Indeed without official APIs).
- No CAPTCHA defeating or bot-detection evasion.
- No bypassing of `robots.txt` disallow directives.
- No scraping of competitor private repositories or private datasets.
- No unverified search snippet attribution (search snippets serve only as discovery pointers to underlying documents).
