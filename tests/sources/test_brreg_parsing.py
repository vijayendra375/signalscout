"""Tests for robust Brreg payload parsing (JSON + XML fallback) and financials."""

from app.fetching.http_client import FetchResult
from app.sources.brreg import parse_brreg_payload, _xml_to_python
from app.extraction.financials import extract_financials
from app.output.models import AvailabilityState
import json
import xml.etree.ElementTree as ET


def _result(text: str) -> FetchResult:
    return FetchResult(
        url="https://data.brreg.no/x",
        status_code=200,
        content=text.encode("utf-8"),
        text=text,
        content_type="application/xml",
        elapsed_ms=1.0,
        bytes_received=len(text),
    )


def test_parse_json_payload():
    payload = [{"id": 1, "valuta": "NOK"}]
    parsed = parse_brreg_payload(_result(json.dumps(payload)))
    assert parsed == payload


def test_parse_xml_arraylist_fallback():
    # This is the shape the Regnskapsregisteret endpoint returns when XML wins
    # content negotiation. It must still be parsed rather than silently dropped.
    xml = (
        "<ArrayList><item>"
        "<id>4804647</id><valuta>NOK</valuta>"
        "<resultatregnskapResultat><aarsresultat>524792.0</aarsresultat></resultatregnskapResultat>"
        "</item></ArrayList>"
    )
    parsed = parse_brreg_payload(_result(xml))
    assert isinstance(parsed, list) and len(parsed) == 1
    assert parsed[0]["id"] == "4804647"
    assert parsed[0]["valuta"] == "NOK"


def test_parse_empty_returns_none():
    assert parse_brreg_payload(_result("")) is None
    assert parse_brreg_payload(_result("   ")) is None


def test_xml_nested_object_collapse():
    xml = "<root><a>1</a><a>2</a><b><c>3</c></b></root>"
    result = _xml_to_python(ET.fromstring(xml))
    assert result["a"] == ["1", "2"]
    assert result["b"]["c"] == "3"


def test_financials_from_xml_parsed_record_have_provenance():
    # A real-ish annual-account record parsed from XML must produce a numeric
    # claim linked to the supplied evidence id.
    xml = (
        "<ArrayList><item>"
        "<aar>2024</aar><valuta>NOK</valuta>"
        "<regnskapsperiode><fraDato>2024-01-01</fraDato><tilDato>2024-12-31</tilDato></regnskapsperiode>"
        "<resultatregnskapResultat>"
        "<driftsresultat><driftsinntekter><sumDriftsinntekter>1000.0</sumDriftsinntekter></driftsinntekter>"
        "<driftsresultat>250.0</driftsresultat></driftsresultat>"
        "<aarsresultat>200.0</aarsresultat>"
        "</resultatregnskapResultat>"
        "</item></ArrayList>"
    )
    records = parse_brreg_payload(_result(xml))
    claims = extract_financials(records, "ev-fin-1")
    by_field = {c.field: c for c in claims}
    assert by_field["latest_revenue"].value == 1000.0
    assert by_field["latest_revenue"].availability == AvailabilityState.AVAILABLE
    assert by_field["latest_revenue"].evidence_ids == ["ev-fin-1"]
    assert by_field["latest_operating_result"].value == 250.0
    assert by_field["latest_annual_result"].value == 200.0
