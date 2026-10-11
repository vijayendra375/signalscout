"""Batch controller with thread-pool concurrency, checkpointing, and fault isolation."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, List, Optional

from app.budget.tracker import BudgetTracker
from app.config.settings import settings
from app.fetching.http_client import SafeHttpClient
from app.identity.validator import normalize_org_number
from app.output.models import TerminalEnvelope, ErrorRecord, RunMetadata, Operations
from app.output.serializer import validate_batch_envelopes, write_jsonl
from app.storage.db import StorageDB
from .pipeline import CompanyPipeline


def load_input_organisations(path: str | Path) -> List[str]:
    """Read organisation numbers from JSON, JSONL, or text file."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    
    orgs = []
    if p.suffix == ".json":
        data = json.loads(text)
        items = data if isinstance(data, list) else data.get("organisation_numbers", [])
        for item in items:
            raw = item.get("organisation_number") if isinstance(item, dict) else item
            orgs.append(normalize_org_number(raw))
    elif p.suffix == ".jsonl":
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            raw = item.get("organisation_number") if isinstance(item, dict) else item
            orgs.append(normalize_org_number(raw))
    else:
        for line in text.splitlines():
            line = line.strip()
            if line:
                orgs.append(normalize_org_number(line))
                
    # Deduplicate while preserving order
    seen = set()
    unique_orgs = []
    for org in orgs:
        if org and org not in seen:
            seen.add(org)
            unique_orgs.append(org)
            
    return unique_orgs


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
        self.http_client = SafeHttpClient(budget_tracker=self.budget)
        self.db = StorageDB(db_path)
        self.pipeline = CompanyPipeline(
            http_client=self.http_client,
            db=self.db,
            budget_tracker=self.budget,
        )
        self.progress_callback = progress_callback

    def run_batch(
        self,
        orgs: List[str],
        output_path: str | Path,
        run_id: str = "batch-1",
        resume: bool = False,
    ) -> List[TerminalEnvelope]:
        output_file = Path(output_path)
        existing_envelopes: dict[str, TerminalEnvelope] = {}
        
        # 1. Resume existing envelopes if requested
        if resume and output_file.exists():
            try:
                for line in output_file.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        item = json.loads(line)
                        env = TerminalEnvelope.model_validate(item)
                        existing_envelopes[env.organisation_number] = env
            except Exception:
                pass

        pending_orgs = [org for org in orgs if org not in existing_envelopes]
        results_by_org: dict[str, TerminalEnvelope] = dict(existing_envelopes)

        total = len(orgs)
        completed_count = len(existing_envelopes)

        def worker(target_org: str) -> tuple[str, TerminalEnvelope]:
            try:
                env = self.pipeline.research_company(target_org, run_id=run_id)
                return target_org, env
            except Exception as exc:
                # Fault isolation: produce a failed envelope rather than breaking batch
                err_env = TerminalEnvelope(
                    organisation_number=target_org,
                    run=RunMetadata(run_id=run_id, started_at="", completed_at="", terminal_status="failed"),
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
                            for o in orgs
                            if o in results_by_org
                        ]
                        write_jsonl(output_file, current_ordered)

        # Final ordered write
        final_envelopes = [results_by_org[org] for org in orgs]
        contract_dicts = [e.to_contract_dict() for e in final_envelopes]
        write_jsonl(output_file, contract_dicts)

        return final_envelopes
