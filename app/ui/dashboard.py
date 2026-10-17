"""Static HTML dashboard generator for SignalScout company intelligence.

This module renders a standalone, offline HTML report from a batch of
TerminalEnvelope objects. It is **not** a live web application: no server,
no API, no live lookups. All data is embedded at generation time from the
already-fetched envelopes.

Security:
  * Every company-provided string is HTML-escaped before insertion.
  * Evidence URLs are validated (http/https only) before rendering as links.
  * No innerHTML is used with untrusted data; textContent-style escaping
    is applied via the Python ``escape`` helper.
"""

from __future__ import annotations

import html as _html
import json
import re
from pathlib import Path
from typing import Any, List
from urllib.parse import urlparse

from app.output.models import TerminalEnvelope

# ---------------------------------------------------------------------------
# HTML escaping helpers
# ---------------------------------------------------------------------------

_URL_SCHEME_RE = re.compile(r"^https?://", re.I)


def _escape(text: Any) -> str:
    """Escape a value for safe insertion into HTML text content."""
    if text is None:
        return ""
    return _html.escape(str(text), quote=True)


def _safe_url(url: Any) -> str | None:
    """Return ``url`` if it is a safe http/https URL, otherwise None."""
    if not url:
        return None
    s = str(url).strip()
    if not _URL_SCHEME_RE.match(s):
        return None
    try:
        parsed = urlparse(s)
    except ValueError:
        return None
    if not parsed.netloc:
        return None
    return s


# ---------------------------------------------------------------------------
# Claim lookup helpers
# ---------------------------------------------------------------------------

def _get_claim(env: dict[str, Any], field: str) -> dict[str, Any] | None:
    for c in env.get("claims", []):
        if c.get("field") == field:
            return c
    return None


def _claim_value(env: dict[str, Any], field: str) -> Any:
    c = _get_claim(env, field)
    return c.get("value") if c else None


def _claim_availability(env: dict[str, Any], field: str) -> str:
    c = _get_claim(env, field)
    return c.get("availability", "not_available") if c else "not_available"


def _badge(availability: str) -> str:
    """Render an availability badge span."""
    cls = f"badge-{availability}"
    return f'<span class="badge {cls}">{_escape(availability)}</span>'


def _money(value: Any, currency: str | None) -> str:
    """Format a monetary value with currency, or an empty-state placeholder."""
    if value is None or value == "":
        return '<span class="empty">Not available</span>'
    try:
        num = float(value)
    except (TypeError, ValueError):
        return _escape(str(value))
    curr = _escape(currency or "NOK")
    return f"{num:,.2f} {curr}"


def _list_value(value: Any) -> str:
    """Render a list value (e.g. secondary activities, board members)."""
    if not value:
        return '<span class="empty">Not available</span>'
    if isinstance(value, list):
        items = "".join(f"<li>{_escape(str(v))}</li>" for v in value if v)
        if not items:
            return '<span class="empty">Not available</span>'
        return f"<ul class='compact-list'>{items}</ul>"
    return _escape(str(value))


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

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
  --success: #166534;
  --success-bg: #dcfce7;
  --warning: #854d0e;
  --warning-bg: #fef3c7;
  --danger: #991b1b;
  --danger-bg: #fee2e2;
  --empty: #94a3b8;
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
.batch-notice {
  margin-top: 10px;
  font-size: 12.5px;
  color: var(--warning);
  background: var(--warning-bg);
  border: 1px solid #fcd34d;
  border-radius: 6px;
  padding: 8px 12px;
  display: inline-block;
}
.metrics-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-top: 16px;
}
.metric-box {
  background: var(--card-bg);
  padding: 12px 16px;
  border-radius: 8px;
  border: 1px solid var(--border);
}
.metric-val { font-size: 22px; font-weight: 700; color: var(--text); }
.metric-lbl { font-size: 12px; color: var(--muted); text-transform: uppercase; font-weight: 600; }
.controls {
  max-width: 1200px;
  margin: 20px auto 16px;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
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
.filter-chip {
  font-size: 12px;
  color: var(--muted);
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 4px 12px;
}
.container {
  max-width: 1200px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr);
  gap: 24px;
}
@media (max-width: 840px) {
  .container { grid-template-columns: 1fr; }
}
.company-list {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  max-height: 80vh;
  overflow-y: auto;
}
.company-item {
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background 0.15s ease, border-left 0.15s ease;
}
.company-item:hover { background: #eff6ff; }
.company-item.active { background: #dbeafe; border-left: 4px solid var(--primary); }
.company-item h3 { font-size: 15px; font-weight: 600; color: var(--text); margin-bottom: 2px; }
.company-item p { font-size: 13px; color: var(--muted); margin: 0; }
.empty-list {
  padding: 24px;
  color: var(--muted);
  text-align: center;
}
.detail-panel {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 24px;
  min-height: 400px;
}
.empty-state {
  padding: 48px 24px;
  color: var(--muted);
  text-align: center;
}
.section { margin-bottom: 28px; border-bottom: 1px solid var(--border); padding-bottom: 20px; }
.section:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
.section h2 { font-size: 18px; font-weight: 600; color: var(--primary); margin-bottom: 12px; }
.section h3 { font-size: 15px; font-weight: 600; color: var(--text); margin: 16px 0 8px; }
.grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.grid-3 { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
.card { background: var(--bg); padding: 14px; border-radius: 8px; border: 1px solid var(--border); }
.card-empty { background: #f1f5f9; padding: 14px; border-radius: 8px; border: 1px dashed var(--border); }
.card span { font-size: 10.5px; text-transform: uppercase; color: var(--muted); font-weight: 600; display: block; margin-bottom: 6px; }
.card strong { font-size: 15px; color: var(--text); }
.card .empty { color: var(--empty); font-style: italic; }
.badge {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 9999px;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  margin-left: 6px;
}
.badge-available { background: var(--success-bg); color: var(--success); }
.badge-not_available { background: var(--warning-bg); color: var(--warning); }
.badge-blocked { background: var(--danger-bg); color: var(--danger); }
.badge-failed { background: var(--danger-bg); color: var(--danger); }
.badge-ambiguous { background: #e0e7ff; color: #4338ca; }
.badge-not_applicable { background: #e2e8f0; color: var(--muted); }
table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 8px; }
th, td { padding: 8px 10px; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }
th { color: var(--muted); font-weight: 600; font-size: 11px; text-transform: uppercase; }
.compact-list { margin: 0; padding-left: 18px; color: var(--text); }
.compact-list li { margin-bottom: 4px; font-size: 13.5px; }
.evidence-box {
  background: #f1f5f9;
  border-left: 3px solid var(--accent);
  padding: 10px 14px;
  border-radius: 4px;
  margin-top: 10px;
  font-size: 12px;
}
.evidence-box a { color: var(--primary); text-decoration: none; word-break: break-all; }
.evidence-box code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 10.5px; color: #475569; word-break: break-all; }
.claim-evidence { font-size: 11.5px; margin-top: 6px; padding-top: 6px; border-top: 1px dashed var(--border); color: var(--muted); }
.claim-evidence a { color: var(--primary); text-decoration: underline; word-break: break-all; font-weight: 600; }
.claim-evidence a:hover { color: var(--primary-hover); }
.claim-evidence .evidence-meta { font-size: 10px; color: var(--empty); margin-top: 2px; display: block; }
.errors-box {
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 6px;
  padding: 12px 16px;
  margin-top: 12px;
  font-size: 12px;
}
.errors-box h4 { margin: 0 0 8px; color: var(--danger); font-size: 12.5px; }
.errors-box ul { margin: 0; padding-left: 18px; color: #7f1d1d; }
.errors-box li { margin-bottom: 4px; }
footer {
  max-width: 1200px;
  margin: 32px auto 0;
  padding: 20px;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: 12px;
  text-align: center;
}
</style>
</head>
<body>
<header>
  <h1>SignalScout Intelligence Laboratory</h1>
  <p class="subtitle">Verified Norwegian company intelligence from Brønnøysund Register Centre (Brreg).</p>
  <div class="batch-notice">${batch_notice}</div>
  <div class="metrics-row" id="metrics"></div>
</header>

<div class="controls">
  <input type="text" id="searchInput" class="search-input" placeholder="Search by company name or organisation number...">
  <span id="filterChip" class="filter-chip">${filtered_count} of ${total_companies} companies</span>
</div>

<div class="container">
  <div class="company-list" id="companyList"></div>
  <div class="detail-panel" id="detailPanel">
    <div class="empty-state">Select a company from the list to inspect verified intelligence.</div>
  </div>
</div>

<script>
const ENVELOPES = __DATA_PLACEHOLDER__;
let selectedOrg = ENVELOPES.length > 0 ? ENVELOPES[0].organisation_number : null;

function esc(t) {
  if (t == null) return "";
  const d = document.createElement("div");
  d.textContent = String(t);
  return d.innerHTML;
}

function getClaim(env, field) {
  return env.claims.find(c => c.field === field);
}

function claimValue(env, field) {
  const c = getClaim(env, field);
  return c ? c.value : null;
}

function claimAvail(env, field) {
  const c = getClaim(env, field);
  return c ? c.availability : "not_available";
}

function badge(avail) {
  return `<span class="badge badge-${avail}">${esc(avail)}</span>`;
}

function money(value, currency) {
  if (value == null || value === "") return '<span class="empty">Not available</span>';
  const num = Number(value);
  if (!Number.isFinite(num)) return esc(String(value));
  const curr = esc(currency || "NOK");
  return num.toLocaleString("nb-NO", { minimumFractionDigits: 0, maximumFractionDigits: 2 }) + " " + curr;
}

function listValue(value) {
  if (!value) return '<span class="empty">Not available</span>';
  if (Array.isArray(value)) {
    const items = value.filter(v => v != null && v !== "").map(v => `<li>${esc(v)}</li>`).join("");
    if (!items) return '<span class="empty">Not available</span>';
    return `<ul class="compact-list">${items}</ul>`;
  }
  return esc(String(value));
}

function formatPeriod(value) {
  if (!value) return '<span class="empty">Not reported</span>';
  if (typeof value === 'object') {
    const f = value.fraDato || value.fromDate || '';
    const t = value.tilDato || value.toDate || '';
    if (f || t) return esc(f) + ' \u2192 ' + esc(t);
    return esc(String(value));
  }
  return esc(String(value));
}

// Return evidence provenance HTML (clickable source URL + retrieval date) for a
// claim's linked evidence records, or an empty string when none exist.
function claimEvidence(env, field) {
  const c = getClaim(env, field);
  if (!c || !c.evidence_ids || c.evidence_ids.length === 0) return '';
  const parts = c.evidence_ids.map((id) => {
    const ev = env.evidence.find((e) => e.id === id);
    if (!ev) return '';
    return (
      '<div class="claim-evidence">' +
      '<a href="' + _escapeUrl(ev.source_url) + '" target="_blank" rel="noopener noreferrer">' +
      esc(ev.source_url) + '</a>' +
      '<span class="evidence-meta">• ' + esc(ev.source_class) + ' • Retrieved ' + esc(ev.retrieved_at) + '</span>' +
      '</div>'
    );
  }).filter(Boolean);
  return parts.length ? parts.join('') : '';
}

// Render a claim card: label, formatted value, availability badge, and linked
// evidence provenance so every displayed fact is traceable to its source.
function card(label, valueHtml, avail, env, field) {
  const ev = claimEvidence(env, field);
  return (
    '<div class="card">' +
    '<span>' + esc(label) + '</span>' +
    valueHtml +
    '<span class="badge badge-' + esc(avail) + '">' + esc(avail) + '</span>' +
    ev +
    '</div>'
  );
}

function renderMetrics() {
  const total = ENVELOPES.length;
  const accountsFound = ENVELOPES.filter(e => claimValue(e, 'latest_revenue') != null && claimAvail(e, 'latest_revenue') === 'available').length;
  const websitesFound = ENVELOPES.filter(e => claimValue(e, 'official_website') != null && claimAvail(e, 'official_website') === 'available').length;
  const hiringActive = ENVELOPES.filter(e => claimValue(e, 'hiring_active') === true && claimAvail(e, 'hiring_active') === 'available').length;
  const vatRegistered = ENVELOPES.filter(e => claimValue(e, 'vat_registered') === true).length;

  document.getElementById('metrics').innerHTML = `
    <div class="metric-box"><div class="metric-val">${total}</div><div class="metric-lbl">Companies Processed</div></div>
    <div class="metric-box"><div class="metric-val">${accountsFound}</div><div class="metric-lbl">Annual Accounts Verified</div></div>
    <div class="metric-box"><div class="metric-val">${websitesFound}</div><div class="metric-lbl">Verified Websites</div></div>
    <div class="metric-box"><div class="metric-val">${hiringActive}</div><div class="metric-lbl">Hiring Signals</div></div>
    <div class="metric-box"><div class="metric-val">${vatRegistered}</div><div class="metric-lbl">VAT Registered</div></div>
  `;
}

function renderList() {
  const query = document.getElementById('searchInput').value.toLowerCase().trim();
  const list = document.getElementById('companyList');
  const chip = document.getElementById('filterChip');
  list.innerHTML = '';

  const filtered = ENVELOPES.filter(e => {
    const name = (claimValue(e, 'legal_name') || '').toLowerCase();
    const org = e.organisation_number;
    const mun = (claimValue(e, 'municipality') || '').toLowerCase();
    return name.includes(query) || org.includes(query) || mun.includes(query);
  });

  chip.textContent = filtered.length + " of " + ENVELOPES.length + " companies";

  if (filtered.length === 0) {
    list.innerHTML = '<div class="empty-list">No companies match your search.</div>';
    return;
  }

  filtered.forEach(e => {
    const name = claimValue(e, 'legal_name') || 'Unnamed Entity';
    const form = claimValue(e, 'organisation_form') || '';
    const mun = claimValue(e, 'municipality') || 'Location not reported';
    const div = document.createElement('div');
    div.className = 'company-item' + (e.organisation_number === selectedOrg ? ' active' : '');
    div.innerHTML = `<h3>${esc(name)}</h3><p>${esc(e.organisation_number)} · ${esc(form)} · ${esc(mun)}</p>`;
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

  const name = claimValue(env, 'legal_name') || 'Unknown Entity';
  const org = env.organisation_number;
  const form = claimValue(env, 'organisation_form') || 'Not reported';
  const address = claimValue(env, 'registered_office') || null;
  const mun = claimValue(env, 'municipality') || null;
  const post = claimValue(env, 'postal_code') || null;
  const employees = claimValue(env, 'registered_employees') || null;
  const industry = claimValue(env, 'industry_description') || claimValue(env, 'industry_code') || null;
  const secondary = claimValue(env, 'secondary_activities');
  const regDate = claimValue(env, 'registration_date') || null;
  const mobile = claimValue(env, 'mobile_phone') || null;
  const email = claimValue(env, 'email_address') || null;
  const shareCap = claimValue(env, 'share_capital');
  const shareCurr = claimValue(env, 'share_capital_currency');
  const lastAcctYear = claimValue(env, 'last_accounts_year') || null;
  const vatReg = claimValue(env, 'vat_registered');
  const inForetaks = claimValue(env, 'registered_in_foretaksregisteret');
  const adverse = claimValue(env, 'adverse_status');

  const rev = claimValue(env, 'latest_revenue');
  const revAvail = claimAvail(env, 'latest_revenue');
  const opRes = claimValue(env, 'latest_operating_result');
  const resBeforeTax = claimValue(env, 'latest_result_before_tax');
  const annRes = claimValue(env, 'latest_annual_result');
  const assets = claimValue(env, 'latest_total_assets');
  const equity = claimValue(env, 'latest_total_equity');
  const debt = claimValue(env, 'latest_total_debt');
  const cash = claimValue(env, 'latest_cash');
  const receivables = claimValue(env, 'latest_receivables');
  const currentAssets = claimValue(env, 'latest_current_assets');
  const fixedAssets = claimValue(env, 'latest_fixed_assets');
  const shortDebt = claimValue(env, 'latest_short_term_debt');
  const longDebt = claimValue(env, 'latest_long_term_debt');
  const currency = claimValue(env, 'financial_currency') || 'NOK';
  const reportingPeriod = claimValue(env, 'latest_reporting_period') || null;

  const ceo = claimValue(env, 'managing_director') || null;
  const chair = claimValue(env, 'board_chair') || null;
  const boardMembers = claimValue(env, 'board_members');
  const workplaces = claimValue(env, 'operating_workplaces');
  const workplaceCount = claimValue(env, 'workplaces_count');

  const website = claimValue(env, 'official_website') || null;
  const websiteTitle = claimValue(env, 'website_title') || null;
  const websiteDesc = claimValue(env, 'website_description') || null;
  const contactEmail = claimValue(env, 'contact_email') || null;
  const contactPhone = claimValue(env, 'contact_phone') || null;
  const pagesCrawled = claimValue(env, 'website_pages_crawled') || null;

  const hiring = claimValue(env, 'hiring_active');
  const hiringAvail = claimAvail(env, 'hiring_active');

  const synthesis = env.profile && env.profile.synthesis && env.profile.synthesis.overview
    ? env.profile.synthesis.overview
    : null;

  let html = `
    <div class="section">
      <h2>${esc(name)}</h2>
      <p style="color: var(--muted); margin-bottom: 12px;">
        Org.nr: <strong>${esc(org)}</strong> &nbsp; ${badge('available')}
        <br>Legal Form: <strong>${esc(form)}</strong> &nbsp; Registration: <strong>${esc(regDate) || 'Not reported'}</strong>
      </p>
      ${synthesis ? `
      <div style="background: #eef2ff; border-left: 3px solid var(--primary); padding: 12px 16px; border-radius: 4px; font-size: 14px; margin-bottom: 16px;">
        <strong>Autonomous Synthesis:</strong> ${esc(synthesis)}
      </div>` : ''}
      <div class="grid-3">
        ${card('Address', address ? esc(address) : '<span class="empty">Not reported</span>', claimAvail(env, 'registered_office'), env, 'registered_office')}
        ${card('Municipality', mun ? esc(mun) : '<span class="empty">Not reported</span>', claimAvail(env, 'municipality'), env, 'municipality')}
        ${card('Postal Code', post ? esc(post) : '<span class="empty">Not reported</span>', claimAvail(env, 'postal_code'), env, 'postal_code')}
        ${card('Industry', industry ? esc(industry) : '<span class="empty">Not reported</span>', claimAvail(env, 'industry_code'), env, 'industry_code')}
        ${card('Employees', employees != null ? esc(employees) : '<span class="empty">Not reported</span>', claimAvail(env, 'registered_employees'), env, 'registered_employees')}
        <div class="card"><span>Adverse Status</span><strong>${adverse === true ? 'Yes — bankruptcy/liquidation' : 'No adverse status reported'} ${adverse === true ? '<span class="badge badge-not_available" style="background:var(--danger-bg);color:var(--danger)">⚠</span>' : ''}</strong></div>
      </div>
    </div>

    <div class="section">
      <h2>Registration &amp; Status</h2>
      <div class="grid-3">
        ${card('Share Capital', shareCap != null ? money(shareCap, shareCurr) : '<span class="empty">Not reported</span>', shareCap != null ? 'available' : 'not_available', env, 'share_capital')}
        ${card('Last Accounts Year', lastAcctYear ? esc(lastAcctYear) : '<span class="empty">Not reported</span>', lastAcctYear ? 'available' : 'not_available', env, 'last_accounts_year')}
        ${card('VAT Registered', vatReg === true ? 'Yes' : 'No', vatReg === true ? 'available' : 'not_available', env, 'vat_registered')}
        ${card('In Foretaksregisteret', inForetaks === true ? 'Yes' : 'No', inForetaks === true ? 'available' : 'not_available', env, 'registered_in_foretaksregisteret')}
        ${card('Mobile Phone', mobile ? esc(mobile) : '<span class="empty">Not reported</span>', mobile ? 'available' : 'not_available', env, 'mobile_phone')}
        ${card('Email Address', email ? esc(email) : '<span class="empty">Not reported</span>', email ? 'available' : 'not_available', env, 'email_address')}
      </div>
      ${secondary ? `
      <h3>Secondary Activities</h3>
      <div class="card-empty">${listValue(secondary)}</div>` : ''}
    </div>

    <div class="section">
      <h2>Financial Statements</h2>
      <p style="color: var(--muted); font-size: 13px; margin-bottom: 12px;">
        Reporting period: ${formatPeriod(reportingPeriod)} &nbsp; Currency: ${esc(currency)}
      </p>
      <div class="grid-3">
        ${card('Latest Revenue', money(rev, currency), revAvail, env, 'latest_revenue')}
        ${card('Operating Result', money(opRes, currency), claimAvail(env, 'latest_operating_result'), env, 'latest_operating_result')}
        ${card('Result Before Tax', money(resBeforeTax, currency), claimAvail(env, 'latest_result_before_tax'), env, 'latest_result_before_tax')}
        ${card('Annual Result', money(annRes, currency), claimAvail(env, 'latest_annual_result'), env, 'latest_annual_result')}
        ${card('Total Assets', money(assets, currency), claimAvail(env, 'latest_total_assets'), env, 'latest_total_assets')}
        ${card('Total Equity', money(equity, currency), claimAvail(env, 'latest_total_equity'), env, 'latest_total_equity')}
        ${card('Total Debt', money(debt, currency), claimAvail(env, 'latest_total_debt'), env, 'latest_total_debt')}
        ${card('Cash', money(cash, currency), claimAvail(env, 'latest_cash'), env, 'latest_cash')}
        ${card('Receivables', money(receivables, currency), claimAvail(env, 'latest_receivables'), env, 'latest_receivables')}
        ${card('Current Assets', money(currentAssets, currency), claimAvail(env, 'latest_current_assets'), env, 'latest_current_assets')}
        ${card('Fixed Assets', money(fixedAssets, currency), claimAvail(env, 'latest_fixed_assets'), env, 'latest_fixed_assets')}
        ${card('Short-Term Debt', money(shortDebt, currency), claimAvail(env, 'latest_short_term_debt'), env, 'latest_short_term_debt')}
        ${card('Long-Term Debt', money(longDebt, currency), claimAvail(env, 'latest_long_term_debt'), env, 'latest_long_term_debt')}
      </div>
      ${revAvail !== 'available' ? '<p style="color: var(--muted); font-size: 13px; margin-top: 10px;">No annual accounts were found in the official registry for this organisation.</p>' : ''}
    </div>

    <div class="section">
      <h2>Leadership &amp; Governance</h2>
      <div class="grid-3">
        ${card('Managing Director / CEO', ceo ? esc(ceo) : '<span class="empty">Not reported</span>', ceo ? 'available' : 'not_available', env, 'managing_director')}
        ${card('Board Chair', chair ? esc(chair) : '<span class="empty">Not reported</span>', chair ? 'available' : 'not_available', env, 'board_chair')}
        <div class="card"><span>Board Members</span>${boardMembers ? listValue(boardMembers) : '<span class="empty">Not reported</span>'}</div>
      </div>
    </div>

    <div class="section">
      <h2>Workplaces &amp; Group</h2>
      <div class="grid-2">
        ${card('Operating Workplaces', workplaceCount != null ? esc(workplaceCount) : '<span class="empty">Not reported</span>', workplaceCount != null ? 'available' : 'not_available', env, 'workplaces_count')}
        <div class="card"><span>Workplace Details</span>${workplaces ? listValue(workplaces) : '<span class="empty">Not reported</span>'}</div>
      </div>
    </div>

    <div class="section">
      <h2>Website &amp; Digital Footprint</h2>
      <div class="grid-2">
        <div class="card"><span>Official Website</span>
          ${website ? `<a href="${esc(website)}" target="_blank" rel="noopener noreferrer" style="color:var(--primary); font-weight:600; text-decoration:underline;">${esc(website)} ↗</a>` : '<span class="empty">No official domain verified</span>'}
        </div>
        ${card('Pages Crawled', pagesCrawled != null ? esc(pagesCrawled) : '<span class="empty">Not checked</span>', pagesCrawled != null ? 'available' : 'not_available', env, 'website_pages_crawled')}
        ${card('Website Title', websiteTitle ? esc(websiteTitle) : '<span class="empty">Not available</span>', websiteTitle ? 'available' : 'not_available', env, 'website_title')}
        ${card('Website Description', websiteDesc ? esc(websiteDesc) : '<span class="empty">Not available</span>', websiteDesc ? 'available' : 'not_available', env, 'website_description')}
        ${card('Contact Email', contactEmail ? esc(contactEmail) : '<span class="empty">Not available</span>', contactEmail ? 'available' : 'not_available', env, 'contact_email')}
        ${card('Contact Phone', contactPhone ? esc(contactPhone) : '<span class="empty">Not available</span>', contactPhone ? 'available' : 'not_available', env, 'contact_phone')}
      </div>
      <p style="color: var(--muted); font-size: 13px; margin-top: 10px;">
        Hiring signal: ${hiring === true ? 'Active' : hiring === false ? 'Not detected' : 'Not checked'}
        ${badge(hiringAvail)}
      </p>
    </div>

    <div class="section">
      <h2>Evidence &amp; Provenance (${env.evidence.length} records)</h2>
      ${env.evidence.length === 0 ? '<p style="color: var(--muted);">No evidence records.</p>' : ''}
      ${env.evidence.map(ev => `
        <div class="evidence-box">
          <div><strong>Source URL:</strong> <a href="${_escapeUrl(ev.source_url)}" target="_blank" rel="noopener noreferrer">${esc(ev.source_url)}</a></div>
          <div><strong>Class:</strong> ${esc(ev.source_class)} &nbsp; <strong>Retrieved:</strong> ${esc(ev.retrieved_at)}</div>
          <div><strong>Citation Span:</strong> <em>"${esc(ev.claim_span)}"</em></div>
          <div><strong>SHA-256:</strong> <code>${esc(ev.content_sha256)}</code></div>
        </div>
      `).join('')}
    </div>

    ${env.errors && env.errors.length > 0 ? `
    <div class="section">
      <h2>Errors &amp; Warnings</h2>
      <div class="errors-box">
        <h4>${env.errors.length} issue(s)</h4>
        <ul>${env.errors.map(err => `<li><strong>${esc(err.code)}:</strong> ${esc(err.message)}</li>`).join('')}</ul>
      </div>
    </div>` : ''}
  `;

  panel.innerHTML = html;
}

function _escapeUrl(url) {
  // Only http/https URLs are rendered as links; everything else is plain text.
  if (!url) return "#";
  try {
    const u = new URL(url);
    if (u.protocol !== "http:" && u.protocol !== "https:") return "#";
    return esc(url);
  } catch {
    return "#";
  }
}

document.getElementById('searchInput').addEventListener('input', renderList);
renderMetrics();
renderList();
renderDetail();
</script>
</body>
</html>
"""


def generate_dashboard_html(
    envelopes: List[TerminalEnvelope],
    output_path: str | Path,
    live_mode: bool = False,
) -> None:
    """Export a standalone, interactive HTML dashboard containing verified evidence.

    When ``live_mode`` is true the banner describes an on-demand live lookup
    rather than a saved batch report, so the UI never misrepresents cached data
    as a fresh lookup.
    """
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    envelopes_data: list[dict[str, Any]] = []
    for e in envelopes:
        if hasattr(e, "model_dump"):
            envelopes_data.append(e.model_dump(mode="json"))  # TerminalEnvelope
        else:
            envelopes_data.append(dict(e))  # already a contract dict
    data_json = json.dumps(envelopes_data, ensure_ascii=False)
    # Escape </script> inside JSON data so it cannot break out of the
    # surrounding <script> tag in the HTML document. This is a valid JSON
    # escape (optional solidus escaping) and prevents XSS via data values.
    data_json = data_json.replace("</script>", "<\\/script>")

    first = envelopes[0] if envelopes else {}
    if hasattr(first, "run"):
        completed_at = first.run.completed_at
        run_id = first.run.run_id
    else:
        completed_at = (first.get("run") or {}).get("completed_at", "unknown")
        run_id = (first.get("run") or {}).get("run_id", "unknown")

    if live_mode:
        batch_notice = (
            '<strong>Live company lookup.</strong> Enter a Norwegian organisation '
            'number above to run a fresh, evidence-backed lookup against the '
            'official Brønnøysund registries. Previously viewed companies remain '
            'in the list so you can switch between profiles within this session.'
        )
    else:
        batch_notice = (
            '<strong>Saved batch report — not a live lookup.</strong> This page '
            'displays data for ' + str(len(envelopes)) + ' companies captured '
            'during run <em>' + _escape(run_id) + '</em> at ' + _escape(completed_at) +
            '. No live queries are performed.'
        )

    html_content = DASHBOARD_TEMPLATE
    html_content = html_content.replace("__DATA_PLACEHOLDER__", data_json)
    html_content = html_content.replace("${total_companies}", str(len(envelopes)))
    html_content = html_content.replace("${run_id}", _escape(run_id))
    html_content = html_content.replace("${completed_at}", _escape(completed_at))
    html_content = html_content.replace("${batch_notice}", batch_notice)
    html_content = html_content.replace("${filtered_count}", str(len(envelopes)))

    target.write_text(html_content, encoding="utf-8")
