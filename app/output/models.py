"""Pydantic data models defining the official Signalpost output contract."""

from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional
from pydantic import BaseModel, Field


class AvailabilityState(str, Enum):
    AVAILABLE = "available"
    NOT_AVAILABLE = "not_available"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"


class SourceClass(str, Enum):
    OFFICIAL_REGISTRY = "official_registry"
    COMPANY_OWNED = "company_owned"
    LICENSED_EXTERNAL = "licensed_external"
    PUBLIC_WEB = "public_web"


class Claim(BaseModel):
    field: str
    value: Any = None
    availability: AvailabilityState
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_ids: List[str] = Field(default_factory=list)


class Evidence(BaseModel):
    id: str
    source_url: str
    source_class: SourceClass
    retrieved_at: str
    content_sha256: str
    claim_span: str


class Change(BaseModel):
    field: str
    old_value: Any
    new_value: Any
    detected_at: str
    materiality: Optional[str] = None


class ErrorRecord(BaseModel):
    code: str
    message: str
    timestamp: Optional[str] = None


class Operations(BaseModel):
    requests: int = Field(default=0, ge=0)
    runtime_ms: int = Field(default=0, ge=0)
    third_party_cost_usd: float = Field(default=0.0, ge=0.0)


class RunMetadata(BaseModel):
    run_id: str
    started_at: str
    completed_at: str
    terminal_status: str = Field(default="completed", description="Terminal status: completed, partial, or failed")


class TerminalEnvelope(BaseModel):
    organisation_number: str = Field(..., pattern=r"^\d{9}$")
    run: RunMetadata
    claims: List[Claim] = Field(default_factory=list)
    evidence: List[Evidence] = Field(default_factory=list)
    changes: List[Change] = Field(default_factory=list)
    errors: List[ErrorRecord] = Field(default_factory=list)
    operations: Operations = Field(default_factory=Operations)
    
    # Internal profile dictionary preserved for UI rendering and diagnostics
    profile: Optional[dict[str, Any]] = None
    
    def to_contract_dict(self) -> dict[str, Any]:
        """Serialize exactly according to the official OUTPUT_CONTRACT.md schema."""
        d = self.model_dump(mode="json", exclude={"profile"})
        # Ensure enum values are serialized as plain strings
        return d
