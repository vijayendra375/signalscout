"""People/locations extraction, including the real Brreg 'etternavn' field."""

from app.extraction.people_locations import extract_people_and_locations
from app.documents.html_parser import parse_html_document


def test_etternavn_field_is_used_for_surnames():
    # The live Brreg API uses "etternavn"; using "slektsnavn" silently drops it.
    raw_roles = [
        {
            "type": {"kode": "DAGL", "beskrivelse": "Daglig leder"},
            "roller": [
                {"type": {"kode": "DAGL", "beskrivelse": "Daglig leder"},
                 "person": {"navn": {"fornavn": "Anders", "etternavn": "Opedal"}}},
            ],
        },
        {
            "type": {"kode": "STYR", "beskrivelse": "Styre"},
            "roller": [
                {"type": {"kode": "LEDE", "beskrivelse": "Styrets leder"},
                 "person": {"navn": {"fornavn": "Jon Erik", "etternavn": "Reinhardsen"}}},
            ],
        },
    ]
    claims = extract_people_and_locations(raw_roles, "ev-r", [], "ev-s")
    by = {c.field: c.value for c in claims}
    assert by["managing_director"] == "Anders Opedal"
    assert by["board_chair"] == "Jon Erik Reinhardsen"


def test_slektsnavn_fallback_still_works():
    raw_roles = [
        {"type": {"kode": "DAGL"}, "roller": [
            {"type": {"kode": "DAGL"}, "person": {"navn": {"fornavn": "Kari", "slektsnavn": "Nordmann"}}},
        ]},
    ]
    claims = extract_people_and_locations(raw_roles, "ev-r", [], "ev-s")
    by = {c.field: c.value for c in claims}
    assert by["managing_director"] == "Kari Nordmann"


def test_avregistrert_role_is_treated_as_inactive():
    # Brreg marks a past role holder with "avregistrert": true; they must not be
    # presented as a current office holder.
    raw_roles = [
        {"type": {"kode": "DAGL", "beskrivelse": "Daglig leder"}, "roller": [
            {"type": {"kode": "DAGL", "beskrivelse": "Daglig leder"},
             "person": {"navn": {"fornavn": "Gamle", "etternavn": "Ledelsen"}},
             "avregistrert": True},
            {"type": {"kode": "DAGL", "beskrivelse": "Daglig leder"},
             "person": {"navn": {"fornavn": "Ny", "etternavn": "Ledelsen"}},
             "avregistrert": False},
        ]},
    ]
    claims = extract_people_and_locations(raw_roles, "ev-r", [], "ev-s")
    by = {c.field: c.value for c in claims}
    assert by["managing_director"] == "Ny Ledelsen"
    roles = by["all_roles"]
    assert any(r["name"] == "Gamle Ledelsen" and r["inactive"] for r in roles)
    assert any(r["name"] == "Ny Ledelsen" and not r["inactive"] for r in roles)


def test_html_parser_extracts_contact_details():
    html = (
        "<html><body>"
        "<a href='mailto:post@example.no'>Mail</a>"
        "<a href='tel:+47 22 33 44 55'>Call</a>"
        "</body></html>"
    )
    parsed = parse_html_document("https://example.no/", html)
    assert "post@example.no" in parsed.emails
    assert any("22 33 44 55" in p for p in parsed.phones)
