"""Local web server for SignalScout live company lookup.

A minimal standard-library HTTP server bound to 127.0.0.1 that:

* Serves the improved dashboard UI with an embedded live-lookup form.
* Accepts a Norwegian organisation number, validates it (Modulus 11),
  and runs the existing ``CompanyPipeline.research_company`` pipeline.
* Returns the resulting TerminalEnvelope as JSON with all evidence,
  availability states, and errors preserved.
* Shares a single ``RequestBudget`` across all lookups so concurrent
  requests cannot exceed the global 2,000-request limit or per-company cap.
* Binds to 127.0.0.1 only — never exposes to the network.
* Never logs, prints, or returns API keys or environment variables.
* Escapes all company-controlled data before HTML insertion.

This is a local development/lab tool, not a production web application.
"""

from __future__ import annotations

import html as _html
import json
import tempfile
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from app.budget.request_budget import RequestBudget
from app.budget.tracker import BudgetTracker
from app.config.settings import settings
from app.fetching.http_client import SafeHttpClient
from app.identity.validator import validate_org_number
from app.orchestrator.pipeline import CompanyPipeline
from app.output.models import TerminalEnvelope
from app.storage.db import StorageDB
from app.ui.dashboard import generate_dashboard_html


class LookupServer:
    """HTTP server providing live SignalScout company lookup on localhost."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host = host
        self.port = port
        # Shared budget across ALL lookups — prevents concurrent lookups
        # from exceeding the global 2,000-request limit.
        self.budget = RequestBudget(
            global_limit=settings.global_request_budget,
            per_company_limit=settings.max_requests_per_company,
            deadline_seconds=settings.run_deadline_seconds,
        )
        self.tracker = BudgetTracker()
        self.http_client = SafeHttpClient(
            budget_tracker=self.tracker, request_budget=self.budget
        )
        self.db = StorageDB()
        self.pipeline = CompanyPipeline(
            http_client=self.http_client,
            db=self.db,
            budget_tracker=self.tracker,
            request_budget=self.budget,
        )
        self._lock = threading.Lock()
        # Looked-up companies in this session, keyed by organisation number.
        self.looked_up: Dict[str, TerminalEnvelope] = {}
        self._server: Optional[HTTPServer] = None

    # ------------------------------------------------------------------
    # Pipeline execution
    # ------------------------------------------------------------------
    def lookup(self, org_input: str) -> TerminalEnvelope:
        """Validate the organisation number and run a single lookup.

        Raises ValueError for invalid organisation numbers. All pipeline
        errors (network failures, budget exhaustion, missing entity) are
        captured inside the returned TerminalEnvelope — never raised.
        """
        org = validate_org_number(org_input)  # raises ValueError if invalid
        with self._lock:
            try:
                env = self.pipeline.research_company(org, run_id="live-lookup")
            except Exception as exc:  # noqa: BLE001
                from app.output.models import ErrorRecord, Operations, RunMetadata
                from app.evidence.store import utc_now

                now = utc_now()
                env = TerminalEnvelope(
                    organisation_number=org,
                    run=RunMetadata(
                        run_id="live-lookup",
                        started_at=now,
                        completed_at=now,
                        terminal_status="failed",
                    ),
                    claims=[],
                    evidence=[],
                    changes=[],
                    errors=[
                        ErrorRecord(
                            code="PIPELINE_EXCEPTION",
                            message=str(exc),
                            timestamp=now,
                        )
                    ],
                    operations=Operations(requests=0, runtime_ms=0),
                )
            self.looked_up[org] = env
        return env

    def budget_status(self) -> Dict[str, Any]:
        """Return the shared request budget snapshot."""
        return self.budget.snapshot().as_dict()

    def companies(self) -> Dict[str, Any]:
        """Return all looked-up envelopes as contract dicts."""
        with self._lock:
            return {
                org: env.to_contract_dict() for org, env in self.looked_up.items()
            }

    # ------------------------------------------------------------------
    # HTTP server lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Start the blocking HTTP server on 127.0.0.1."""
        handler = self._make_handler()
        self._server = HTTPServer((self.host, self.port), handler)
        print(f"[*] SignalScout live lookup server on http://{self.host}:{self.port}")
        print(f"[*] Global budget: {settings.global_request_budget} requests")
        print(f"[*] Per-company cap: {settings.max_requests_per_company} requests")
        print(f"[*] Run deadline: {settings.run_deadline_seconds} seconds")
        print("[*] Bound to 127.0.0.1 only — not exposed to the network.")
        self._server.serve_forever()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()

    # ------------------------------------------------------------------
    # Request handler factory
    # ------------------------------------------------------------------
    def _make_handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            """Per-request handler for the lookup server."""

            def log_message(self, format, *args):  # noqa: ANN001
                # Suppress default request logging to avoid leaking URLs/queries.
                pass

            def _send_json(self, status: int, data: Dict[str, Any]) -> None:
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_body(self) -> bytes:
                length = int(self.headers.get("Content-Length", 0))
                return self.rfile.read(length) if length > 0 else b""

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/") or "/"

                if path == "/":
                    self._serve_dashboard()
                elif path == "/api/status":
                    self._send_json(200, server.budget_status())
                elif path == "/api/companies":
                    self._send_json(200, server.companies())
                elif path.startswith("/api/company/"):
                    org = path[len("/api/company/") :]
                    with server._lock:
                        env = server.looked_up.get(org)
                    if env is None:
                        self._send_json(
                            404,
                            {"error": "not_found", "message": f"Company {org} not looked up yet."},
                        )
                    else:
                        self._send_json(200, env.to_contract_dict())
                else:
                    self._send_json(404, {"error": "not_found", "message": "Unknown endpoint."})

            def do_POST(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/") or "/"

                if path == "/api/lookup":
                    self._handle_lookup()
                else:
                    self._send_json(404, {"error": "not_found", "message": "Unknown endpoint."})

            # -- internal handlers ---------------------------------------
            def _serve_dashboard(self) -> None:
                """Render the dashboard HTML with embedded looked-up envelopes
                and an embedded live-lookup form."""
                envelopes = list(server.companies().values())
                # Use a unique temp file per request to avoid collisions
                # under concurrent access.
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".html", delete=False, encoding="utf-8"
                ) as tmp:
                    tmp_path = Path(tmp.name)
                try:
                    generate_dashboard_html(envelopes, tmp_path, live_mode=True)
                    html = tmp_path.read_text(encoding="utf-8")
                finally:
                    try:
                        tmp_path.unlink(missing_ok=True)  # type: ignore[attr-defined]
                    except OSError:
                        pass
                # Inject the live-lookup form before the closing </body>.
                lookup_form = self._lookup_form_html()
                html = html.replace("</body>", lookup_form + "</body>")
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _handle_lookup(self) -> None:
                """Validate org number, run pipeline, return envelope JSON."""
                try:
                    body = self._read_body()
                    data = json.loads(body.decode("utf-8")) if body else {}
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self._send_json(
                        400,
                        {
                            "error": "invalid_request",
                            "message": "Request body must be valid JSON.",
                        },
                    )
                    return

                org_input = data.get("organisation_number", "")
                if not org_input or not str(org_input).strip():
                    self._send_json(
                        400,
                        {
                            "error": "validation_error",
                            "message": "Organisation number is required.",
                        },
                    )
                    return

                try:
                    env = server.lookup(str(org_input).strip())
                except ValueError as exc:
                    self._send_json(
                        400,
                        {
                            "error": "validation_error",
                            "message": str(exc),
                        },
                    )
                    return
                except Exception as exc:  # noqa: BLE001
                    # Pipeline-level failure — return as a failed envelope
                    # rather than crashing the server.
                    from app.output.models import (
                        ErrorRecord,
                        Operations,
                        RunMetadata,
                    )
                    from app.evidence.store import utc_now

                    now = utc_now()
                    env = TerminalEnvelope(
                        organisation_number=str(org_input).strip(),
                        run=RunMetadata(
                            run_id="live-lookup",
                            started_at=now,
                            completed_at=now,
                            terminal_status="failed",
                        ),
                        claims=[],
                        evidence=[],
                        changes=[],
                        errors=[
                            ErrorRecord(
                                code="PIPELINE_EXCEPTION",
                                message=str(exc),
                                timestamp=now,
                            )
                        ],
                        operations=Operations(requests=0, runtime_ms=0),
                    )
                    with server._lock:
                        server.looked_up[str(org_input).strip()] = env

                self._send_json(200, env.to_contract_dict())

            def _lookup_form_html(self) -> str:
                """HTML for the embedded live-lookup form."""
                return """
<div class="controls" style="margin-top: 24px;">
  <form id="lookupForm" style="display:flex;gap:8px;flex-wrap:wrap; align-items:center;">
    <input
      type="text"
      id="lookupInput"
      class="search-input"
      placeholder="Norwegian organisation number (9 digits)"
      maxlength="9"
      pattern="[0-9]{9}"
      required
      style="flex:1;min-width:260px;"
    />
    <button type="submit" id="lookupBtn" style="
      background:var(--primary);color:#fff;border:none;
      padding:10px 20px;border-radius:8px;font-size:14px;
      cursor:pointer;font-weight:600;">
      Look up
    </button>
    <span id="lookupStatus" style="font-size:13px;color:var(--muted);margin-left:8px;"></span>
  </form>
  <p id="lookupError" style="color:var(--danger);font-size:13px;margin-top:8px;display:none;"></p>
</div>

<script>
(function() {
  const form = document.getElementById('lookupForm');
  const input = document.getElementById('lookupInput');
  const btn = document.getElementById('lookupBtn');
  const status = document.getElementById('lookupStatus');
  const error = document.getElementById('lookupError');

  if (!form) return;

  function validateOrg(org) {
    return /^[0-9]{9}$/.test(org);
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const org = input.value.trim();
    error.style.display = 'none';
    status.textContent = '';
    if (!org) {
      error.textContent = 'Please enter an organisation number.';
      error.style.display = 'block';
      return;
    }
    if (!validateOrg(org)) {
      error.textContent = 'Enter a valid 9-digit Norwegian organisation number.';
      error.style.display = 'block';
      return;
    }
    status.textContent = 'Looking up ' + org + '...';
    btn.disabled = true;
    btn.textContent = 'Working…';

    try {
      const res = await fetch('/api/lookup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ organisation_number: org }),
      });
      const data = await res.json();

      if (!res.ok) {
        error.textContent = data.message || 'Lookup failed.';
        error.style.display = 'block';
        status.textContent = '';
        return;
      }

      if (data.terminal_status === 'failed') {
        error.textContent = (data.errors && data.errors[0] && data.errors[0].message)
          ? data.errors[0].message
          : 'Lookup failed.';
        error.style.display = 'block';
        status.textContent = '';
        return;
      }

      status.textContent = 'Lookup complete — ' + data.organisation_number;
      // Reload the page to show the new company in the dashboard list.
      window.location.href = window.location.pathname + '?selected=' + org;
    } catch (err) {
      error.textContent = 'Network error: unable to reach the lookup server.';
      error.style.display = 'block';
      status.textContent = '';
    } finally {
      btn.disabled = false;
      btn.textContent = 'Look up';
    }
  });
})();
</script>
"""
        return Handler
