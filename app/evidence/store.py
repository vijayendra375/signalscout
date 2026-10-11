"""Immutable evidence store and SHA-256 content provenance tracking."""

from __future__ import annotations

import datetime
import hashlib
from typing import Dict, List, Optional
from app.output.models import Evidence, SourceClass


def utc_now() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_hexdigest(content: bytes | str) -> str:
    """Calculate the SHA-256 hexadecimal hash of byte or string content."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


class EvidenceStore:
    """In-memory immutable evidence store for a company research run."""

    def __init__(self) -> None:
        self._evidence_by_id: Dict[str, Evidence] = {}
        self._counter: int = 1

    def add(
        self,
        source_url: str,
        source_class: SourceClass | str,
        content: bytes | str,
        claim_span: str,
        retrieved_at: Optional[str] = None,
        custom_id: Optional[str] = None,
    ) -> Evidence:
        """Register a new immutable piece of evidence and return the created record."""
        retrieved_at = retrieved_at or utc_now()
        content_hash = sha256_hexdigest(content)
        
        ev_id = custom_id or f"ev-{self._counter}"
        self._counter += 1
        
        # Ensure SourceClass enum instance
        s_class = SourceClass(source_class) if isinstance(source_class, str) else source_class

        record = Evidence(
            id=ev_id,
            source_url=source_url,
            source_class=s_class,
            retrieved_at=retrieved_at,
            content_sha256=content_hash,
            claim_span=claim_span.strip(),
        )
        self._evidence_by_id[record.id] = record
        return record

    def get(self, evidence_id: str) -> Optional[Evidence]:
        return self._evidence_by_id.get(evidence_id)

    def all(self) -> List[Evidence]:
        return list(self._evidence_by_id.values())
