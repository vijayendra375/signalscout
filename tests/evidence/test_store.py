"""Unit tests for EvidenceStore and content hashing."""

from app.evidence.store import EvidenceStore, sha256_hexdigest
from app.output.models import SourceClass


def test_sha256_hexdigest():
    text = "SignalScout verified evidence"
    h1 = sha256_hexdigest(text)
    h2 = sha256_hexdigest(text.encode("utf-8"))
    assert h1 == h2
    assert len(h1) == 64


def test_evidence_store_addition_and_retrieval():
    store = EvidenceStore()
    ev1 = store.add(
        source_url="https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
        source_class=SourceClass.OFFICIAL_REGISTRY,
        content=b'{"navn": "EQUINOR ASA"}',
        claim_span="EQUINOR ASA (923609016)",
    )
    assert ev1.id == "ev-1"
    assert ev1.source_class == SourceClass.OFFICIAL_REGISTRY
    assert len(ev1.content_sha256) == 64
    assert ev1.claim_span == "EQUINOR ASA (923609016)"
    
    # Retrieve
    found = store.get("ev-1")
    assert found is not None
    assert found.id == "ev-1"
    
    # Second addition has unique sequential ID
    ev2 = store.add(
        source_url="https://www.equinor.com",
        source_class=SourceClass.COMPANY_OWNED,
        content=b"<html>Homepage</html>",
        claim_span="Homepage span",
    )
    assert ev2.id == "ev-2"
    assert len(store.all()) == 2
