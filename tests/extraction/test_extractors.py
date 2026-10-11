"""Unit tests for category-specific extractors and non-zero rule enforcement."""

from app.extraction.company_record import extract_company_record
from app.extraction.financials import extract_financials
from app.extraction.people_locations import extract_people_and_locations
from app.output.models import AvailabilityState


def test_company_record_extraction():
    raw_entity = {
        "organisasjonsnummer": "923609016",
        "navn": "EQUINOR ASA",
        "organisasjonsform": {"kode": "ASA", "beskrivelse": "Allment aksjeselskap"},
        "forretningsadresse": {"adresse": ["Forusbeen 50"], "postnummer": "4035", "kommune": "STAVANGER"},
        "naeringskode1": {"kode": "06.100", "beskrivelse": "Utvinning av råolje"},
        "antallAnsatte": 21000,
        "registreringsdatoEnhetsregisteret": "1972-09-18",
        "konkurs": False,
    }
    claims = extract_company_record(raw_entity, "ev-1")
    claim_dict = {c.field: c.value for c in claims}
    
    assert claim_dict["legal_name"] == "EQUINOR ASA"
    assert claim_dict["organisation_form"] == "ASA"
    assert claim_dict["registered_office"] == "Forusbeen 50"
    assert claim_dict["municipality"] == "STAVANGER"
    assert claim_dict["industry_code"] == "06.100"
    assert claim_dict["registered_employees"] == 21000
    assert claim_dict["adverse_status"] is False


def test_financials_extraction_with_data():
    raw_accounts = [
        {
            "id": 1,
            "aar": 2024,
            "valuta": "NOK",
            "regnskapsperiode": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"},
            "resultatregnskapResultat": {
                "driftsresultat": {
                    "driftsinntekter": {"sumDriftsinntekter": 1200000000},
                    "driftsresultat": 350000000,
                },
                "aarsresultat": 250000000,
            },
            "eiendeler": {"sumEiendeler": 5000000000},
            "egenkapitalGjeld": {
                "egenkapital": {"sumEgenkapital": 2000000000},
                "gjeldOversikt": {"sumGjeld": 3000000000},
            },
        }
    ]
    claims = extract_financials(raw_accounts, "ev-fin-1")
    claim_dict = {c.field: c.value for c in claims}
    avail_dict = {c.field: c.availability for c in claims}

    assert claim_dict["latest_revenue"] == 1200000000.0
    assert avail_dict["latest_revenue"] == AvailabilityState.AVAILABLE
    assert claim_dict["latest_operating_result"] == 350000000.0
    assert claim_dict["latest_annual_result"] == 250000000.0
    assert claim_dict["latest_total_assets"] == 5000000000.0
    assert claim_dict["financial_currency"] == "NOK"


def test_financials_non_zero_rule_enforcement():
    # Crucial test: missing financial values MUST NOT be converted to numeric zero!
    claims = extract_financials(None, None)
    for c in claims:
        assert c.value is None
        assert c.availability == AvailabilityState.NOT_AVAILABLE
        # Value must never be 0.0 or 0
        assert c.value != 0


def test_people_and_locations_extraction():
    raw_roles = [
        {
            "type": {"kode": "DAGL", "beskrivelse": "Daglig leder"},
            "roller": [
                {
                    "type": {"kode": "DAGL", "beskrivelse": "Daglig leder"},
                    "person": {"navn": {"fornavn": "Anders", "slektsnavn": "Opedal"}},
                }
            ],
        },
        {
            "type": {"kode": "STYR", "beskrivelse": "Styre"},
            "roller": [
                {
                    "type": {"kode": "LEDE", "beskrivelse": "Styrets leder"},
                    "person": {"navn": {"fornavn": "Jon Erik", "slektsnavn": "Reinhardsen"}},
                },
                {
                    "type": {"kode": "MEDL", "beskrivelse": "Styremedlem"},
                    "person": {"navn": {"fornavn": "Anne", "slektsnavn": "Drinkwater"}},
                },
            ],
        },
    ]
    raw_subunits = [
        {
            "organisasjonsnummer": "973123456",
            "navn": "EQUINOR ASA AVD STAVANGER",
            "forretningsadresse": {"kommune": "STAVANGER", "poststed": "STAVANGER"},
            "antallAnsatte": 5000,
        }
    ]
    claims = extract_people_and_locations(raw_roles, "ev-r-1", raw_subunits, "ev-sub-1")
    claim_dict = {c.field: c.value for c in claims}

    assert claim_dict["managing_director"] == "Anders Opedal"
    assert claim_dict["board_chair"] == "Jon Erik Reinhardsen"
    assert "Anne Drinkwater" in claim_dict["board_members"]
    assert claim_dict["workplaces_count"] == 1
    assert len(claim_dict["operating_workplaces"]) == 1
