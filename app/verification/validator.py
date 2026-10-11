"""Fact validation and normalization rules."""

from __future__ import annotations

from typing import Any, Optional
from app.output.models import AvailabilityState, Claim


def normalize_metric(val: Any) -> Optional[float]:
    """Convert metric to float safely, returning None if absent or invalid."""
    if val is None or val == "":
        return None
    try:
        f = float(val)
        return f
    except (ValueError, TypeError):
        return None


def create_claim_record(
    field: str,
    value: Any,
    evidence_ids: list[str],
    confidence: float = 1.0,
    forced_availability: Optional[AvailabilityState] = None,
    observed: bool = False,
) -> Claim:
    """
    Construct a validated Claim record adhering strictly to the non-zero and availability rules.
    Never converts missing values to zero.

    ``observed=True`` marks a claim as coming from a source that *was* checked. In
    that case an explicitly empty collection (e.g. zero job postings on a verified
    careers page) is published as ``available`` with an empty value, which the
    output contract distinguishes from a source that was never checked.
    """
    if forced_availability:
        availability = forced_availability
    elif value is not None and value != "" and (value != [] or observed):
        availability = AvailabilityState.AVAILABLE
    else:
        availability = AvailabilityState.NOT_AVAILABLE
        
    return Claim(
        field=field,
        value=value if availability == AvailabilityState.AVAILABLE else None,
        availability=availability,
        confidence=confidence if availability == AvailabilityState.AVAILABLE else 0.0,
        evidence_ids=evidence_ids if availability == AvailabilityState.AVAILABLE else [],
    )
