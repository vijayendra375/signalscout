"""Batch controller with thread-pool concurrency, checkpointing, and fault isolation."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, List, Optional

from app.budget.request_budget import RequestBudget
from app.budget.tracker import BudgetTracker
from app.config.settings import settings
from app.evidence.store import utc_now
from app.fetching.http_client import SafeHttpClient
from app.identity.validator import validate_org_number
from app.output.models import TerminalEnvelope, ErrorRecord, RunMetadata, Operations
from app.output.serializer import validate_batch_envelopes, write_jsonl
from app.storage.db import StorageDB
from .pipeline import CompanyPipeline

# Sentinel for malformed JSONL records. Contains zero digits so that
# normalize_org_number() returns "" and validate_org_number() always rejects
# it. Malformed JSONL can never be converted into a valid organisation number.
INVALID_JSONL_SENTINEL = "__INVALID_JSONL_RECORD__"


def load_input_organisations(path: str | Path) -> List[str]:
    """Read organisation numbers from JSON, JSONL, or text file.

    Raw input values are preserved (no normalization, deduplication, or
    dropping) so that malformed records survive into ``run_batch`` diagnostics
    instead of silently disappearing. Valid organisation numbers are still
    validated and deduplicated by ``run_batch``.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")

    raw_values: List[str] = []
    if p.suffix == ".json":
        data = json.loads(text)
        items = data if isinstance(data, list) else data.get("organisation_numbers", [])
        for item in items:
            raw = item.get("organisation_number") if isinstance(item, dict) else item
            raw_values.append("" if raw is None else str(raw))
    elif p.suffix == ".jsonl":
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            # Lines that look like JSON objects/arrays must parse as JSON.
            # Malformed JSON is rejected outright — never fall back to extracting
            # digits from a malformed JSON object or array.
            if line.startswith("{") or line.startswith("["):
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    # Malformed JSON must be impossible to validate as an
                    # organisation number. Use a zero-digit sentinel so that
                    # normalize_org_number() returns "" and validation fails.
                    # Never embed the raw line, which may contain digits that
                    # the validator could extract and accept.
                    raw_values.append(INVALID_JSONL_SENTINEL)
                    continue
                raw = item.get("organisation_number") if isinstance(item, dict) else ""
                raw_values.append("" if raw is None else str(raw))
            elif any(c in line for c in "{}[]"):
                # Line contains JSON structural content but does not start with
                # a JSON delimiter (e.g. 'junk {"organisation_number":"..."}').
                # This is JSON-like content that is not a clean record — reject
                # it outright rather than extracting digits from surrounding text.
                raw_values.append(INVALID_JSONL_SENTINEL)
                continue
            else:
                # Plain-text line: only accept an entire line that is an
                # organisation number with allowed formatting (spaces, hyphens).
                # Never extract an organisation number from arbitrary
                # surrounding text.
                allowed_chars = set("0123456789 -")
                if not all(c in allowed_chars for c in line):
                    raw_values.append(INVALID_JSONL_SENTINEL)
                    continue
                digits_only = line.replace(" ", "").replace("-", "")
                if len(digits_only) != 9:
                    raw_values.append(INVALID_JSONL_SENTINEL)
                    continue
                raw_values.append(line)
    else:
        for line in text.splitlines():
            raw_values.append(line.strip())

    return raw_values


def count_startable_orgs(orgs: List[str]) -> int:
    """Count organisations that pass validation and will enter the lifecycle.

    Invalid organisation numbers are rejected before envelope creation and must
    not reserve a fair-share slot or enter the published dataset.
    """
    count = 0
    for org in orgs:
        try:
            validate_org_number(org)
        except Exception:
            continue
        count += 1
    return count


class BatchRunner:
    """Orchestrates parallel research across an input batch of companies."""

    def __init__(
        self,
        max_workers: Optional[int] = None,
        db_path: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> None:
        self.max_workers = max_workers or settings.max_workers
        self.budget = BudgetTracker()
        self.request_budget = RequestBudget(
            global_limit=settings.global_request_budget,
            per_company_limit=settings.max_requests_per_company,
            deadline_seconds=settings.run_deadline_seconds,
        )
        self.http_client = SafeHttpClient(budget_tracker=self.budget, request_budget=self.request_budget)
        self.db = StorageDB(db_path)
        self.pipeline = CompanyPipeline(
            http_client=self.http_client,
            db=self.db,
            budget_tracker=self.budget,
            request_budget=self.request_budget,
        )
        self.progress_callback = progress_callback
        self.valid_orgs: List[str] = []
        self.invalid_inputs: List[dict[str, str]] = []

    def run_batch(
        self,
        orgs: List[str],
        output_path: str | Path,
        run_id: str = "batch-1",
        resume: bool = False,
    ) -> List[TerminalEnvelope]:
        output_file = Path(output_path)

        # 1. Reject malformed identifiers before any profile/submission output
        #    exists. Diagnostics are retained separately and never become
        #    company envelopes, evidence, changes, or published dataset rows.
        valid_orgs: List[str] = []
        invalid_inputs: List[dict[str, str]] = []
        seen_valid: set[str] = set()
        for raw in orgs:
            try:
                org = validate_org_number(raw)
            except ValueError as exc:
                invalid_inputs.append({"input": str(raw), "reason": str(exc)})
                continue
            if org not in seen_valid:
                seen_valid.add(org)
                valid_orgs.append(org)

        self.valid_orgs = valid_orgs
        self.invalid_inputs = invalid_inputs

        existing_envelopes: dict[str, TerminalEnvelope] = {}

        # 2. Resume existing envelopes if requested, but only for valid inputs.
        if resume and output_file.exists():
            try:
                for line in output_file.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        item = json.loads(line)
                        env = TerminalEnvelope.model_validate(item)
                        if env.organisation_number in seen_valid:
                            existing_envelopes[env.organisation_number] = env
            except Exception:
                pass

        pending_orgs = [org for org in valid_orgs if org not in existing_envelopes]
        results_by_org: dict[str, TerminalEnvelope] = dict(existing_envelopes)

        total = len(valid_orgs)
        completed_count = len(existing_envelopes)

        # Set total company count for fair request budget allocation. Invalid
        # identifiers never enter this count or the completion lifecycle.
        self.request_budget.set_total_companies(len(pending_orgs))

        def worker(target_org: str) -> tuple[str, TerminalEnvelope]:
            try:
                env = self.pipeline.research_company(target_org, run_id=run_id)
                return target_org, env
            except Exception as exc:
                # Fault isolation for an otherwise valid company. The target is
                # already a validated identifier, so no placeholder is needed.
                failed_at = utc_now()
                err_env = TerminalEnvelope(
                    organisation_number=target_org,
                    run=RunMetadata(
                        run_id=run_id,
                        started_at=failed_at,
                        completed_at=utc_now(),
                        terminal_status="failed",
                    ),
                    claims=[],
                    evidence=[],
                    changes=[],
                    errors=[ErrorRecord(code="PIPELINE_EXCEPTION", message=str(exc))],
                    operations=Operations(requests=0, runtime_ms=0),
                )
                return target_org, err_env

        if pending_orgs:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {executor.submit(worker, org): org for org in pending_orgs}
                for future in as_completed(futures):
                    org, env = future.result()
                    results_by_org[org] = env
                    completed_count += 1
                    
                    if self.progress_callback:
                        self.progress_callback(completed_count, total, org)

                    # Periodic checkpointing
                    if completed_count % settings.checkpoint_every == 0 or completed_count == total:
                        current_ordered = [
                            results_by_org[o].to_contract_dict()
                            for o in valid_orgs
                            if o in results_by_org
                        ]
                        write_jsonl(output_file, current_ordered)

        # Final ordered write: only validated company profiles are published.
        final_envelopes = [results_by_org[org] for org in valid_orgs if org in results_by_org]
        contract_dicts = [e.to_contract_dict() for e in final_envelopes]
        write_jsonl(output_file, contract_dicts)

        return final_envelopes
