"""Atomic file serialization and batch integrity verification."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List
from .models import TerminalEnvelope, AvailabilityState


def write_jsonl(path: Path | str, items: List[dict[str, Any]]) -> None:
    """Atomically write a list of dictionaries to a JSONL file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
    temp.replace(target)


def validate_batch_envelopes(envelopes: List[TerminalEnvelope], expected_count: int) -> dict[str, Any]:
    """Verify that every batch invariant required by the official evaluation contract holds."""
    orgs = [e.organisation_number for e in envelopes]
    unique_orgs = set(orgs)
    
    # Check claim validity
    invalid_claims = []
    missing_evidence = []
    for e in envelopes:
        ev_ids = {ev.id for ev in e.evidence}
        for c in e.claims:
            if c.availability not in AvailabilityState:
                invalid_claims.append({"org": e.organisation_number, "field": c.field, "availability": c.availability})
            if c.availability == AvailabilityState.AVAILABLE and not c.evidence_ids:
                missing_evidence.append({"org": e.organisation_number, "field": c.field})
            for eid in c.evidence_ids:
                if eid not in ev_ids:
                    missing_evidence.append({"org": e.organisation_number, "field": c.field, "missing_eid": eid})
                    
    checks = {
        "exact_expected_count": len(envelopes) == expected_count,
        "unique_organisation_numbers": len(orgs) == len(unique_orgs),
        "zero_silent_drops": len(envelopes) == expected_count and len(orgs) == len(unique_orgs),
        "all_terminal_statuses_valid": all(e.run.terminal_status in {"completed", "failed", "partial"} for e in envelopes),
        "zero_unlinked_available_claims": len(missing_evidence) == 0,
        "all_claims_have_valid_state": len(invalid_claims) == 0,
    }
    
    passed = all(checks.values())
    return {
        "passed": passed,
        "checks": checks,
        "total_envelopes": len(envelopes),
        "expected_count": expected_count,
        "missing_evidence_count": len(missing_evidence),
        "invalid_claims": invalid_claims,
    }
