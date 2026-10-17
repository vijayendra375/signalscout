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
    _emp_reg_raw = raw_entity.get("harRegistrertAntallAnsatte")
    claims.append(create_claim_record("employees_registered", bool(_emp_reg_raw) if _emp_reg_raw is not None else None, eids))

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
    # Use the key-presence check so that a missing Brreg key yields not_available
    # rather than fabricating a "verified negative" (False). Rule #6: missing
    # information must never be interpreted as a verified negative.
    _vat_raw = raw_entity.get("registrertIMvaregisteret")
    _foretaks_raw = raw_entity.get("registrertIForetaksregisteret")
    _frivillig_raw = raw_entity.get("registrertIFrivillighetsregisteret")
    claims.append(create_claim_record("vat_registered", bool(_vat_raw) if _vat_raw is not None else None, eids))
    claims.append(create_claim_record("registered_in_foretaksregisteret", bool(_foretaks_raw) if _foretaks_raw is not None else None, eids))
    claims.append(create_claim_record("registered_in_voluntary_register", bool(_frivillig_raw) if _frivillig_raw is not None else None, eids))

    # 11. Adverse Status (bankruptcy, liquidation, dissolution)
    # Use key-presence checks so a missing Brreg key yields not_available
    # rather than fabricating a verified negative.
    _konkurs_raw = raw_entity.get("konkurs")
    _avvikling_raw = raw_entity.get("underAvvikling")
    _tvangs_raw = raw_entity.get("underTvangsavviklingEllerTvangsopplosning")
    is_bankrupt = bool(_konkurs_raw) if _konkurs_raw is not None else None
    is_liquidating = bool(_avvikling_raw) if _avvikling_raw is not None else None
    is_dissolving = bool(_tvangs_raw) if _tvangs_raw is not None else None
    # Adverse is available only if at least one status is observed; otherwise not_available.
    if is_bankrupt is None and is_liquidating is None and is_dissolving is None:
        adverse = None
    else:
        adverse = bool(is_bankrupt or is_liquidating or is_dissolving)
    claims.append(create_claim_record("adverse_status", adverse, eids))

    # 12. Secondary activities (additional NACE classifications beyond naeringskode1).
    # Brreg returns aktivitet as a list of description strings.
    aktivitet = raw_entity.get("aktivitet") or []
    secondary_activities = [str(a) for a in aktivitet if a]
    claims.append(create_claim_record("secondary_activities", secondary_activities or None, eids))

    return claims
