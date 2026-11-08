# Official Rules — Builderr Signalpost

**Source of truth:** https://builderr.ai/challenges/signalpost  
**Last checked:** 7 November 2026

This file records the live challenge page, not the older Unstop listing or earlier round brief. If this document and the challenge page differ, the live challenge page controls.

## 1. Challenge

Build an agent that accepts a Norwegian organisation number, finds public company facts, attributes each fact to its correct company, links sources and retrieval dates, marks missing information honestly, and refreshes profiles to detect changes.

The published universe contains 411,160 eligible Norwegian companies with 2025 annual-account records.

## 2. Current entry and revision rules

- The challenge page currently says entries and revisions remain open through **16 November 2026**.
- Submit the agent, a **100-company smoke-test result or run report**, repository link, exact commit hash, one-command run instruction, model/API/licence details, expected official-run cost, and contact details.
- Builderr supplies the official company batch. **Do not submit a self-selected company manifest or precomputed profiles as a substitute for the agent.**
- The public company list may be used for additional scale testing, including 1,000+ companies.
- The challenge page states one initial version plus up to four revisions.
- The official batch is shared across eligible entries and may grow (the page gives 1,000 to 1,100 as an example). The agent must process every supplied company and return one terminal result per input.

## 3. Scoring

| Category | Points |
| :--- | ---: |
| Recall and coverage | 50 |
| Precision and evidence | 30 |
| Synthesis | 12 |
| User experience | 8 |
| **Total** | **100** |

### Recall and coverage (50)

The challenge page describes a weighted recall measure for each information type:

- 70%: the proportion of companies in the checked collection for which the agent found relevant information.
- 30%: the proportion of checked facts the agent found.

The collection is assembled from submissions and Builderr's own crawlers, with duplicates and wrong-company findings removed. It is not a claim that every fact on the internet has been discovered.

The five information categories used by this project are company record, financials, people and locations, company website, and hiring/public activity. The exact checked facts and their weights are controlled by the evaluator.

### Precision and evidence (30)

Facts must belong to the correct legal entity and have a valid source and date. Unsupported facts lose points. A material wrong-company publication blocks qualification.

### Synthesis (12)

The profile should explain what the company does, what changed, and what remains unknown, with sources for substantive conclusions.

### User experience (8)

Users must be able to find, compare, and verify information on desktop and mobile.

## 4. Qualification and integrity

- At least **65/100** on an official run.
- The current challenge page does not state separate category minimums.
- Return exactly one terminal result for every supplied company, including when facts are missing or blocked.
- Preserve source, retrieval date, and reporting period for every relevant claim.
- Repeated runs must be idempotent: no duplicate records or false changes from the same source snapshot.
- Never replace missing values with zero.
- A material wrong-company match is a qualification blocker.

Allowed result states: `available`, `not_available`, `blocked`, `not_applicable`, `ambiguous`, and `failed`.

## 5. Runtime and cost limits

The live challenge page says each official run has a fixed time and resource budget and that a small external API budget is available. **The public page checked on 7 November 2026 does not expose the exact numeric runtime, request, or dollar caps.** Do not present older figures as current official limits without checking the latest technical evaluation contract or confirming with Builderr.

SignalScout's local defaults remain conservative/configurable. Its deterministic path uses no paid model and reports $0 third-party API cost. Any optional model/API use must be declared and reproducible by the evaluator.

## 6. Source and security requirements

- Use permitted public sources and respect source terms and robots policies.
- Keep company identity matching conservative.
- Preserve verifiable source URLs, retrieval timestamps, hashes, and claim spans.
- Do not fabricate facts, financial values, sources, dates, or benchmark results.
- Do not use credentials tied to a personal account if the evaluator cannot reproduce the run.
- Keep secrets out of the repository.

## 7. Operational submission checklist

1. Clean-clone the exact commit.
2. Install only declared dependencies.
3. Run the single documented command.
4. Run the 100-company smoke test and retain its report/output.
5. Confirm one terminal envelope per input and inspect claim/evidence integrity.
6. Declare model/API use, licences, and expected cost.
7. Submit the repository, exact commit, command, smoke-test artifact, and contact details to the destination shown on the challenge page.

The smoke test proves basic execution and completeness; it is not the official score. The official evaluator uses its supplied batch.
