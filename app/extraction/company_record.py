"""Company record extractor for official registry fields."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from app.output.models import Claim
from app.verification.validator import create_claim_record


def extract_company_record(raw_entity: Optional[dict[str, Any]], evidence_id: Optional[str]) -> List[Claim]:
    """Extract claims belonging to the official Company Record category."""
    claims: List[Claim] = []
    eids = [evidence_id] if evidence_id else []
    
    if not raw_entity:
        fields = [
            "legal_name", "organisation_form", "organisation_form_description",
            "registered_office", "postal_code", "post_town", "municipality",
            "municipality_number", "country", "industry_code", "industry_description",
            "naeringskode_2", "naeringskode_3", "registered_employees",
            "employees_registered", "registration_date", "founding_date",
            "mobile_phone", "email_address", "share_capital",
            "share_capital_currency", "last_accounts_year", "vat_registered",
            "registered_in_foretaksregisteret", "registered_in_voluntary_register",
            "adverse_status",
        ]
        for f in fields:
            claims.append(create_claim_record(f, None, []))
        return claims

    # 1. Legal Name
    legal_name = raw_entity.get("navn")
    claims.append(create_claim_record("legal_name", legal_name, eids))

    # 2. Organisation Form
    form_obj = raw_entity.get("organisasjonsform") or {}
    form_code = form_obj.get("kode")
    claims.append(create_claim_record("organisation_form", form_code, eids))
    claims.append(create_claim_record("organisation_form_description", form_obj.get("beskrivelse"), eids))

    # 3. Registered Office & Address
    addr_obj = raw_entity.get("forretningsadresse") or raw_entity.get("postadresse") or {}
    address_lines = addr_obj.get("adresse", [])
    full_address = ", ".join(address_lines) if address_lines else addr_obj.get("kommune")
    claims.append(create_claim_record("registered_office", full_address or None, eids))
    claims.append(create_claim_record("municipality", addr_obj.get("kommune"), eids))
    claims.append(create_claim_record("postal_code", addr_obj.get("postnummer"), eids))
    claims.append(create_claim_record("post_town", addr_obj.get("poststed"), eids))
    claims.append(create_claim_record("municipality_number", addr_obj.get("kommunenummer"), eids))
    claims.append(create_claim_record("country", addr_obj.get("landkode"), eids))

    # 4. Industry / NACE
    nace_obj = raw_entity.get("naeringskode1") or {}
    claims.append(create_claim_record("industry_code", nace_obj.get("kode"), eids))
    claims.append(create_claim_record("industry_description", nace_obj.get("beskrivelse"), eids))

    # 4b. Secondary industry codes (naeringskode2 / naeringskode3) when present.
    for idx in (2, 3):
        nace = raw_entity.get(f"naeringskode{idx}") or {}
        claims.append(create_claim_record(f"naeringskode_{idx}", nace.get("kode"), eids))
        claims.append(create_claim_record(f"naeringskode_{idx}_description", nace.get("beskrivelse"), eids))

    # 5. Employees
    employees = raw_entity.get("antallAnsatte")
    claims.append(create_claim_record("registered_employees", employees, eids))
    claims.append(create_claim_record("employees_registered", bool(raw_entity.get("harRegistrertAntallAnsatte")), eids))

    # 6. Registration Date
    reg_date = raw_entity.get("registreringsdatoEnhetsregisteret") or raw_entity.get("stiftelsesdato")
    claims.append(create_claim_record("registration_date", reg_date, eids))
    claims.append(create_claim_record("founding_date", raw_entity.get("stiftelsesdato"), eids))

    # 7. Contact details (mobile phone, email) — from Brreg entity record.
    claims.append(create_claim_record("mobile_phone", raw_entity.get("mobil"), eids))
    claims.append(create_claim_record("email_address", raw_entity.get("epostadresse"), eids))

    # 8. Share capital (for AS/ASA and other capital-company forms).
    kapital_obj = raw_entity.get("kapital") or {}
    claims.append(create_claim_record("share_capital", kapital_obj.get("belop"), eids))
    claims.append(create_claim_record("share_capital_currency", kapital_obj.get("valuta"), eids))

    # 9. Last submitted annual accounts year (useful even when detailed accounts unavailable).
    claims.append(create_claim_record("last_accounts_year", raw_entity.get("sisteInnsendteAarsregnskap"), eids))

    # 10. Registration statuses.
    claims.append(create_claim_record("vat_registered", bool(raw_entity.get("registrertIMvaregisteret")), eids))
    claims.append(create_claim_record("registered_in_foretaksregisteret", bool(raw_entity.get("registrertIForetaksregisteret")), eids))
    claims.append(create_claim_record("registered_in_voluntary_register", bool(raw_entity.get("registrertIFrivillighetsregisteret")), eids))

    # 11. Adverse Status (bankruptcy, liquidation, dissolution)
    is_bankrupt = bool(raw_entity.get("konkurs"))
    is_liquidating = bool(raw_entity.get("underAvvikling"))
    is_dissolving = bool(raw_entity.get("underTvangsavviklingEllerTvangsopplosning"))
    adverse = is_bankrupt or is_liquidating or is_dissolving
    claims.append(create_claim_record("adverse_status", adverse, eids))

    # 12. Secondary activities (additional NACE classifications beyond naeringskode1).
    # Brreg returns aktivitet as a list of description strings.
    aktivitet = raw_entity.get("aktivitet") or []
    secondary_activities = [str(a) for a in aktivitet if a]
    claims.append(create_claim_record("secondary_activities", secondary_activities or None, eids))

    return claims
