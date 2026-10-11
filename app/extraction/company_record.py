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
            "legal_name", "organisation_form", "registered_office", "municipality",
            "postal_code", "industry_code", "industry_description", "registered_employees",
            "registration_date", "adverse_status"
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

    # 3. Registered Office & Address
    addr_obj = raw_entity.get("forretningsadresse") or raw_entity.get("postadresse") or {}
    address_lines = addr_obj.get("adresse", [])
    full_address = ", ".join(address_lines) if address_lines else addr_obj.get("kommune")
    claims.append(create_claim_record("registered_office", full_address or None, eids))
    claims.append(create_claim_record("municipality", addr_obj.get("kommune"), eids))
    claims.append(create_claim_record("postal_code", addr_obj.get("postnummer"), eids))

    # 4. Industry / NACE
    nace_obj = raw_entity.get("naeringskode1") or {}
    claims.append(create_claim_record("industry_code", nace_obj.get("kode"), eids))
    claims.append(create_claim_record("industry_description", nace_obj.get("beskrivelse"), eids))

    # 5. Employees
    employees = raw_entity.get("antallAnsatte")
    claims.append(create_claim_record("registered_employees", employees, eids))

    # 6. Registration Date
    reg_date = raw_entity.get("registreringsdatoEnhetsregisteret") or raw_entity.get("stiftelsesdato")
    claims.append(create_claim_record("registration_date", reg_date, eids))

    # 7. Adverse Status (bankruptcy, liquidation, dissolution)
    is_bankrupt = bool(raw_entity.get("konkurs"))
    is_liquidating = bool(raw_entity.get("underAvvikling"))
    is_dissolving = bool(raw_entity.get("underTvangsavviklingEllerTvangsopplosning"))
    adverse = is_bankrupt or is_liquidating or is_dissolving
    claims.append(create_claim_record("adverse_status", adverse, eids))

    return claims
