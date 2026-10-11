"""Deterministic temporal change detection and idempotent diff calculation."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional
from app.output.models import AvailabilityState, Change, Claim


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


class ChangeDetector:
    """Computes field-level diffs and classifies change materiality."""

    @classmethod
    def detect_changes(
        cls,
        prior_claims: Dict[str, Any],
        current_claims: List[Claim],
        timestamp: Optional[str] = None,
    ) -> List[Change]:
        detected_at = timestamp or utc_now()
        changes: List[Change] = []
        
        for curr in current_claims:
            # Never treat an unobserved value as a change. A source that is
            # missing, blocked or ambiguous this run is not evidence that the
            # previously reported fact changed.
            if curr.availability != AvailabilityState.AVAILABLE:
                continue

            field = curr.field
            new_val = curr.value
            
            if field not in prior_claims:
                continue
                
            old_val = prior_claims[field]

            # Skip when either side has no observed value or when they are equivalent.
            if old_val is None or new_val is None:
                continue
            if old_val == new_val:
                continue
                
            # Classify materiality
            materiality = "minor"
            if "revenue" in field or "operating_result" in field:
                materiality = "material_financial"
            elif "managing_director" in field or "board_chair" in field:
                materiality = "leadership_transition"
            elif "adverse_status" in field:
                materiality = "critical_status"
            elif "official_website" in field:
                materiality = "digital_rebranding"
            elif "operating_workplaces" in field:
                materiality = "workforce_expansion"
                
            changes.append(Change(
                field=field,
                old_value=old_val,
                new_value=new_val,
                detected_at=detected_at,
                materiality=materiality,
            ))
            
        return changes
