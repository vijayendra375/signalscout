# Source policy and implemented source scope — SignalScout

This document describes the sources the current implementation actually uses. It is not a blanket legal opinion or a claim that every public website permits automated access. The live Builderr Signalpost challenge page and its linked technical evaluation contract take precedence over this project document.

## 1. Primary source: official Norwegian registers

Identity resolution starts with the Brønnøysundregistrene (Brreg) APIs:

| Endpoint | Information used |
| --- | --- |
| `https://data.brreg.no/enhetsregisteret/api/enheter/{org}` | Legal name, organisation form, registered address, industry code, employee count, registered website/email, registration date. |
| `https://data.brreg.no/enhetsregisteret/api/enheter/{org}/roller` | Registered leadership, board roles and related role data. |
| `https://data.brreg.no/regnskapsregisteret/regnskap/{org}` | Filed annual accounts, revenue, operating result, annual result, balance sheet and reporting period. |
| `https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={org}&size=1000` | Registered subunits and workplace information. |
| `https://data.brreg.no/enhetsregisteret/api/konsernstruktur/{org}` | Group structure when available and applicable. |

The registry organisation number is the primary identity key. A missing registry response is not replaced with an inferred financial value or guessed company fact.

## 2. Secondary source: the company's own public website

The crawler may use public pages on:
- A website explicitly registered by Brreg; or
- A candidate domain derived from a custom-domain email address recorded in the official Brreg entity record.

An email-derived domain is only a discovery hint. It is not published as the company's website unless the fetched page independently passes the identity firewall. Public mailbox and ISP email providers are excluded from this discovery path.

The crawler may inspect the homepage and bounded same-site pages such as contact, about, leadership, careers, jobs, news and press pages. Sitemap entries are only crawl candidates; they do not override the identity check or crawl limits.

## 3. Access and crawl safeguards

- Consult `robots.txt` before requesting the homepage or any discovered page.
- Respect explicit disallow rules. If the robots policy cannot be retrieved because of a network/server failure, fail closed and do not crawl that site for that run.
- A missing `robots.txt` (HTTP 404/410) is treated as no published robots policy; it is not treated as proof that other terms permit scraping.
- Do not bypass authentication, paywalls, CAPTCHAs, rate limits, bot protections or other access controls.
- Do not crawl a source where its published terms or licence prohibit the intended automated access. The crawler does not automatically interpret every website's terms; source eligibility remains a conservative operational check, not an automated legal guarantee.
- Keep requests bounded, same-site, attributable and evidence-linked. Do not use search snippets as factual evidence.

## 4. Sources not currently used for factual extraction

The current implementation does not scrape LinkedIn, Meta, Glassdoor, Indeed, login-walled directories, competitor private repositories or private datasets. It does not use public search snippets, third-party company directories, news aggregators or RSS feeds as factual evidence. Adding any external source requires a separate review of its access terms, licence, robots policy, identity controls and evidence provenance before implementation.

## 5. Evidence requirements

Every published claim must link to evidence from the source that supports it. Evidence records preserve the source URL, retrieval timestamp, content hash and claim span. If identity is uncertain, the system should omit the company-owned claim rather than attribute it to the wrong legal entity.

## 6. Compliance boundary

This implementation is designed to follow the public-source, attribution, identity, robots and integrity requirements stated on the Builderr Signalpost challenge page. It cannot guarantee legal permission for every third-party site or replace review of the latest evaluation contract. When a source's permission is unclear, do not add it merely to increase recall.
