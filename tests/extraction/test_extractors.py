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
        "forretningsadresse": {"adresse": ["Forusbeen 50"], "postnummer": "4035", "kommune": "STAVANGER",
                               "poststed": "STAVANGER", "kommunenummer": "4203", "landkode": "NO"},
        "naeringskode1": {"kode": "06.100", "beskrivelse": "Utvinning av råolje"},
        "naeringskode2": {"kode": "20.100", "beskrivelse": "Kjemikalier"},
        "naeringskode3": None,
        "antallAnsatte": 21000,
        "harRegistrertAntallAnsatte": True,
        "registreringsdatoEnhetsregisteret": "1972-09-18",
        "stiftelsesdato": "1972-06-01",
        "mobil": None,
        "epostadresse": None,
        "kapital": {"belop": 500000.0, "valuta": "NOK"},
        "sisteInnsendteAarsregnskap": 2023,
        "registrertIMvaregisteret": True,
        "registrertIForetaksregisteret": True,
        "registrertIFrivillighetsregisteret": False,
        "konkurs": False,
        "underAvvikling": False,
        "underTvangsavviklingEllerTvangsopplosning": False,
    }
    claims = extract_company_record(raw_entity, "ev-1")
    claim_dict = {c.field: c.value for c in claims}
    avail_dict = {c.field: c.availability for c in claims}

    assert claim_dict["legal_name"] == "EQUINOR ASA"
    assert claim_dict["organisation_form"] == "ASA"
    assert claim_dict["organisation_form_description"] == "Allment aksjeselskap"
    assert claim_dict["registered_office"] == "Forusbeen 50"
    assert claim_dict["postal_code"] == "4035"
    assert claim_dict["post_town"] == "STAVANGER"
    assert claim_dict["municipality"] == "STAVANGER"
    assert claim_dict["municipality_number"] == "4203"
    assert claim_dict["country"] == "NO"
    assert claim_dict["industry_code"] == "06.100"
    assert claim_dict["naeringskode_2"] == "20.100"
    assert claim_dict["naeringskode_3"] is None
    assert avail_dict["naeringskode_2"] == "available"
    assert avail_dict["naeringskode_3"] == "not_available"
    assert claim_dict["registered_employees"] == 21000
    assert claim_dict["employees_registered"] is True
    assert claim_dict["founding_date"] == "1972-06-01"
    assert claim_dict["registration_date"] == "1972-09-18"
    assert claim_dict["share_capital"] == 500000.0
    assert claim_dict["share_capital_currency"] == "NOK"
    assert claim_dict["last_accounts_year"] == 2023
    assert claim_dict["vat_registered"] is True
    assert claim_dict["registered_in_foretaksregisteret"] is True
    assert claim_dict["registered_in_voluntary_register"] is False
    assert claim_dict["adverse_status"] is False


def test_company_record_missing_entity_is_not_available():
    claims = extract_company_record(None, None)
    by = {c.field: c.availability for c in claims}
    for f in ["legal_name", "industry_code", "share_capital", "vat_registered", "adverse_status"]:
        assert by[f] == "not_available", f"{f} should be not_available when entity is missing"


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
                "ordinaertResultatFoerSkattekostnad": 300000000,
            },
            "eiendeler": {"sumEiendeler": 5000000000, "sumBankinnskuddOgKontanter": 100000000,
                          "sumFordringer": 200000000, "omloepsmidler": {"sumOmloepsmidler": 400000000},
                          "anleggsmidler": {"sumAnleggsmidler": 4600000000}},
            "egenkapitalGjeld": {
                "egenkapital": {"sumEgenkapital": 2000000000},
                "gjeldOversikt": {"sumGjeld": 3000000000, "kortsiktigGjeld": {"sumKortsiktigGjeld": 800000000},
                                  "langsiktigGjeld": {"sumLangsiktigGjeld": 2200000000}},
            },
        }
    ]
    claims = extract_financials(raw_accounts, "ev-fin-1")
    claim_dict = {c.field: c.value for c in claims}
    avail_dict = {c.field: c.availability for c in claims}

    assert claim_dict["latest_revenue"] == 1200000000.0
    assert claim_dict["latest_operating_result"] == 350000000.0
    assert claim_dict["latest_result_before_tax"] == 300000000.0
    assert claim_dict["latest_annual_result"] == 250000000.0
    assert claim_dict["latest_total_assets"] == 5000000000.0
    assert claim_dict["latest_total_equity"] == 2000000000.0
    assert claim_dict["latest_total_debt"] == 3000000000.0
    assert claim_dict["latest_cash"] == 100000000.0
    assert claim_dict["latest_receivables"] == 200000000.0
    assert claim_dict["latest_current_assets"] == 400000000.0
    assert claim_dict["latest_fixed_assets"] == 4600000000.0
    assert claim_dict["latest_short_term_debt"] == 800000000.0
    assert claim_dict["latest_long_term_debt"] == 2200000000.0
    assert claim_dict["financial_currency"] == "NOK"
    assert claim_dict["financial_records"] is not None
    assert avail_dict["financial_currency"] == "available"
    assert claim_dict["latest_reporting_period"] == {"fraDato": "2024-01-01", "tilDato": "2024-12-31"}

    # Reporting year preserved on each record.
    years = [r["year"] for r in claim_dict["financial_records"]]
    assert years[0] == 2024


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
