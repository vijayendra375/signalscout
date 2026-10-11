"""Interactive Evidence Dashboard HTML generator for desktop and mobile inspection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List
from app.output.models import TerminalEnvelope


DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SignalScout — Norwegian Company Intelligence Dashboard</title>
<style>
:root {
  --bg: #f8fafc;
  --card-bg: #ffffff;
  --text: #0f172a;
  --muted: #64748b;
  --border: #e2e8f0;
  --primary: #123eaa;
  --primary-hover: #0c2b7a;
  --accent: #0284c7;
  --badge-avail: #166534;
  --badge-avail-bg: #dcfce7;
  --badge-unavail: #854d0e;
  --badge-unavail-bg: #fef9c3;
  --badge-err: #991b1b;
  --badge-err-bg: #fee2e2;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.5;
  padding: 20px;
}
header {
  max-width: 1200px;
  margin: 0 auto 24px;
  background: var(--card-bg);
  padding: 24px;
  border-radius: 12px;
  border: 1px solid var(--border);
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
h1 { font-size: 26px; font-weight: 700; color: var(--primary); margin-bottom: 6px; }
p.subtitle { color: var(--muted); font-size: 14px; }
.metrics-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-top: 16px;
}
.metric-box {
  background: var(--bg);
  padding: 12px 16px;
  border-radius: 8px;
  border: 1px solid var(--border);
}
.metric-val { font-size: 22px; font-weight: 700; color: var(--text); }
.metric-lbl { font-size: 12px; color: var(--muted); text-transform: uppercase; font-weight: 600; }
.controls {
  max-width: 1200px;
  margin: 0 auto 16px;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
.search-input {
  flex: 1;
  min-width: 260px;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 14px;
  background: var(--card-bg);
}
.container {
  max-width: 1200px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: 20px;
}
@media (max-width: 840px) {
  .container { grid-template-columns: 1fr; }
}
.company-list {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  max-height: 750px;
  overflow-y: auto;
}
.company-item {
  padding: 14px;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background 0.15s ease;
}
.company-item:hover, .company-item.active { background: #eff6ff; }
.company-item h3 { font-size: 15px; font-weight: 600; color: var(--text); }
.company-item p { font-size: 13px; color: var(--muted); }
.detail-panel {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 24px;
}
.section { margin-bottom: 24px; border-bottom: 1px solid var(--border); padding-bottom: 20px; }
.section:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
.section h2 { font-size: 18px; font-weight: 600; color: var(--primary); margin-bottom: 12px; }
.grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
.card { background: var(--bg); padding: 12px; border-radius: 8px; border: 1px solid var(--border); }
.card span { font-size: 11px; text-transform: uppercase; color: var(--muted); font-weight: 600; display: block; }
.card strong { font-size: 14px; color: var(--text); }
.badge {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 9999px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}
.badge-available { background: var(--badge-avail-bg); color: var(--badge-avail); }
.badge-not_available { background: var(--badge-unavail-bg); color: var(--badge-unavail); }
.badge-failed { background: var(--badge-err-bg); color: var(--badge-err); }
table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 8px; }
th, td { padding: 8px 10px; border-bottom: 1px solid var(--border); text-align: left; }
th { color: var(--muted); font-weight: 600; }
.evidence-box {
  background: #f1f5f9;
  border-left: 3px solid var(--accent);
  padding: 10px 14px;
  border-radius: 4px;
  margin-top: 8px;
  font-size: 12px;
}
.evidence-box a { color: var(--primary); text-decoration: none; word-break: break-all; }
.evidence-box code { font-family: monospace; font-size: 11px; color: #475569; }
</style>
</head>
<body>
<header>
  <h1>SignalScout Intelligence Laboratory</h1>
  <p class="subtitle">Autonomous, verified Norwegian company intelligence grounded in official Brønnøysund registries.</p>
  <div class="metrics-row" id="metrics"></div>
</header>

<div class="controls">
  <input type="text" id="searchInput" class="search-input" placeholder="Filter companies by name, org number, municipality...">
</div>

<div class="container">
  <div class="company-list" id="companyList"></div>
  <div class="detail-panel" id="detailPanel">
    <p style="color: var(--muted); text-align: center; padding: 40px;">Select a company from the list to inspect verified intelligence.</p>
  </div>
</div>

<script>
const ENVELOPES = __DATA_PLACEHOLDER__;
let selectedOrg = ENVELOPES.length > 0 ? ENVELOPES[0].organisation_number : null;

function renderMetrics() {
  const total = ENVELOPES.length;
  const accountsFound = ENVELOPES.filter(e => e.claims.some(c => c.field === 'latest_revenue' && c.availability === 'available')).length;
  const websitesFound = ENVELOPES.filter(e => e.claims.some(c => c.field === 'official_website' && c.availability === 'available')).length;
  const hiringActive = ENVELOPES.filter(e => e.claims.some(c => c.field === 'hiring_active' && c.value === true)).length;

  document.getElementById('metrics').innerHTML = `
    <div class="metric-box"><div class="metric-val">${total}</div><div class="metric-lbl">Companies Processed</div></div>
    <div class="metric-box"><div class="metric-val">${accountsFound}</div><div class="metric-lbl">Annual Accounts Verified</div></div>
    <div class="metric-box"><div class="metric-val">${websitesFound}</div><div class="metric-lbl">Verified Domains</div></div>
    <div class="metric-box"><div class="metric-val">${hiringActive}</div><div class="metric-lbl">Hiring Signals Captured</div></div>
  `;
}

function getClaim(env, field) {
  return env.claims.find(c => c.field === field);
}

function renderList() {
  const query = document.getElementById('searchInput').value.toLowerCase().trim();
  const list = document.getElementById('companyList');
  list.innerHTML = '';

  const filtered = ENVELOPES.filter(e => {
    const name = (getClaim(e, 'legal_name')?.value || '').toLowerCase();
    const org = e.organisation_number;
    const mun = (getClaim(e, 'municipality')?.value || '').toLowerCase();
    return name.includes(query) || org.includes(query) || mun.includes(query);
  });

  filtered.forEach(e => {
    const name = getClaim(e, 'legal_name')?.value || 'Unnamed Entity';
    const form = getClaim(e, 'organisation_form')?.value || '';
    const mun = getClaim(e, 'municipality')?.value || 'Location not reported';
    const div = document.createElement('div');
    div.className = 'company-item' + (e.organisation_number === selectedOrg ? ' active' : '');
    div.innerHTML = `<h3>${name}</h3><p>${e.organisation_number} · ${form} · ${mun}</p>`;
    div.onclick = () => {
      selectedOrg = e.organisation_number;
      renderList();
      renderDetail();
    };
    list.appendChild(div);
  });
}

function renderDetail() {
  const panel = document.getElementById('detailPanel');
  const env = ENVELOPES.find(e => e.organisation_number === selectedOrg);
  if (!env) return;

  const name = getClaim(env, 'legal_name')?.value || 'Unknown Entity';
  const org = env.organisation_number;
  const form = getClaim(env, 'organisation_form')?.value || 'N/A';
  const address = getClaim(env, 'registered_office')?.value || 'N/A';
  const mun = getClaim(env, 'municipality')?.value || 'N/A';
  const employees = getClaim(env, 'registered_employees')?.value ?? 'Not reported';
  const industry = getClaim(env, 'industry_description')?.value || getClaim(env, 'industry_code')?.value || 'N/A';

  const rev = getClaim(env, 'latest_revenue')?.value;
  const opRes = getClaim(env, 'latest_operating_result')?.value;
  const curr = getClaim(env, 'financial_currency')?.value || 'NOK';

  const ceo = getClaim(env, 'managing_director')?.value || 'Not reported';
  const chair = getClaim(env, 'board_chair')?.value || 'Not reported';
  const website = getClaim(env, 'official_website')?.value;

  const synthesis = env.profile?.synthesis?.overview || 'Factual overview not synthesized.';

  let html = `
    <div class="section">
      <h2>${name}</h2>
      <p style="color: var(--muted); margin-bottom: 12px;">Org.nr: <strong>${org}</strong> · Legal Form: <strong>${form}</strong></p>
      <div style="background: #eef2ff; border-left: 3px solid var(--primary); padding: 12px 16px; border-radius: 4px; font-size: 14px; margin-bottom: 16px;">
        <strong>Autonomous Synthesis:</strong> ${synthesis}
      </div>
      <div class="grid-2">
        <div class="card"><span>Address</span><strong>${address}</strong></div>
        <div class="card"><span>Municipality</span><strong>${mun}</strong></div>
        <div class="card"><span>Industry</span><strong>${industry}</strong></div>
        <div class="card"><span>Employees</span><strong>${employees}</strong></div>
      </div>
    </div>

    <div class="section">
      <h2>Financial Statements</h2>
      <div class="grid-2">
        <div class="card"><span>Latest Revenue</span><strong>${rev !== null && rev !== undefined ? Number(rev).toLocaleString() + ' ' + curr : 'Not available'}</strong></div>
        <div class="card"><span>Operating Result</span><strong>${opRes !== null && opRes !== undefined ? Number(opRes).toLocaleString() + ' ' + curr : 'Not available'}</strong></div>
      </div>
    </div>

    <div class="section">
      <h2>Leadership & Governance</h2>
      <div class="grid-2">
        <div class="card"><span>Managing Director / CEO</span><strong>${ceo}</strong></div>
        <div class="card"><span>Board Chair</span><strong>${chair}</strong></div>
      </div>
    </div>

    <div class="section">
      <h2>Website & Digital Footprint</h2>
      <p>${website ? `<a href="${website}" target="_blank" style="color:var(--primary); font-weight:600;">${website} ↗</a>` : 'No official domain verified.'}</p>
    </div>

    <div class="section">
      <h2>Evidence & Provenance (${env.evidence.length} records)</h2>
      ${env.evidence.map(ev => `
        <div class="evidence-box">
          <div><strong>Source URL:</strong> <a href="${ev.source_url}" target="_blank">${ev.source_url}</a></div>
          <div><strong>Class:</strong> ${ev.source_class} · <strong>Retrieved:</strong> ${ev.retrieved_at}</div>
          <div><strong>Citation Span:</strong> <em>"${ev.claim_span}"</em></div>
          <div><strong>SHA-256:</strong> <code>${ev.content_sha256}</code></div>
        </div>
      `).join('')}
    </div>
  `;

  panel.innerHTML = html;
}

document.getElementById('searchInput').addEventListener('input', renderList);
renderMetrics();
renderList();
renderDetail();
</script>
</body>
</html>
"""


def generate_dashboard_html(envelopes: List[TerminalEnvelope], output_path: str | Path) -> None:
    """Export a standalone, interactive HTML dashboard containing verified evidence."""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    
    # Dump envelopes as JSON
    envelopes_data = [e.model_dump(mode="json") for e in envelopes]
    data_json = json.dumps(envelopes_data, ensure_ascii=False)
    
    html_content = DASHBOARD_TEMPLATE.replace("__DATA_PLACEHOLDER__", data_json)
    target.write_text(html_content, encoding="utf-8")
