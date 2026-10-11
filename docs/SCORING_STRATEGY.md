# Scoring and Optimization Strategy — SignalScout

## 1. Challenge Scoring Framework
- Total possible score: **100 points**
- Qualification threshold: **$\ge 65/100$ on an official run**
- Component Breakdown:
  1. **Recall and Coverage: 50 points** (Formula: $0.70 \times \text{Company Recall} + 0.30 \times \text{Claim Recall}$)
  2. **Precision and Evidence: 30 points** (Zero wrong-company match, claim-level evidence links, dates, periods)
  3. **Synthesis: 12 points** (Concise, sourced, zero hallucinated facts, explicit unknowns)
  4. **User Experience: 8 points** (Desktop & mobile usability, evidence inspection, filtering)

## 2. Strategic Insights from the Official Standings
The official leaderboard shows that 37 submissions were made, 28 assessed, and 0 qualified (highest score: 60.80).
Almost all previous entrants scored ~13/50 on Recall and Coverage, while maxing out Synthesis (12/12) and UX (8/8) and getting ~27/30 on Evidence.
**To cross 65/100, the primary bottleneck is Recall and Coverage across all five scorer-facing dimensions.**

## 3. High-Recall Optimization Tactics
1. **Breadth over Depth First**: Ensure every single company in the batch gets a complete Pass 1 sweep across:
   - Official company record (100% company coverage via Brreg Enhetsregisteret API).
   - Roles (management and board via Brreg Roller API).
   - Annual accounts (all available years via Brreg Regnskap API).
   - Operating workplaces (subunits via Brreg Underenheter API).
   - Group structure (parent/subsidiary links via Brreg Konsernstruktur API).
2. **Domain Discovery & Verification**:
   - Primary: Check official website reported in registry (`hjemmeside`).
   - Secondary: If missing or redirected, perform safe domain candidate discovery.
   - Verification: Pass through Identity Firewall before accepting.
3. **Company Site Deep Sweep**:
   - Extract sitemaps and probe `/om-oss`, `/kontakt`, `/ledelse`, `/karriere`, `/nyheter`.
   - Parse embedded JSON-LD (Schema.org `Organization`, `JobPosting`).
   - Extract declared social handles (LinkedIn, Facebook, YouTube, GitHub, Twitter).
4. **Hiring and Public Signals**:
   - Extract career postings directly from company website `/karriere` or structured data.
   - Monitor company news releases, RSS feeds, and official registry announcements.
5. **Zero Wrong-Company Tolerance**:
   - Quarantining ambiguous matches protects the 30 Evidence points and prevents disqualification gates from failing.
