"""People (leadership/board) and operating locations/workplaces extractor."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from app.output.models import Claim
from app.verification.validator import create_claim_record


def extract_people_and_locations(
    raw_roles: Optional[list[dict[str, Any]]],
    roles_evidence_id: Optional[str],
    raw_subunits: Optional[list[dict[str, Any]]],
    subunits_evidence_id: Optional[str],
    raw_group: Optional[dict[str, Any]] = None,
    group_evidence_id: Optional[str] = None,
) -> List[Claim]:
    """Extract claims for People, Locations, and Group Structure."""
    claims: List[Claim] = []
    
    # 1. Leadership and Roles
    roles_eids = [roles_evidence_id] if roles_evidence_id else []
    extracted_roles = []
    managing_director = None
    board_chair = None
    board_members = []
    
    if raw_roles:
        for group in raw_roles:
            group_type_obj = group.get("type") if isinstance(group.get("type"), dict) else {}
            group_type = group_type_obj.get("kode") or ""
            group_desc = group_type_obj.get("beskrivelse") or ""
            roller = group.get("roller", [])
            for r in roller:
                person = r.get("person") or {}
                navn_obj = person.get("navn") or {}
                # Brreg uses "etternavn"; older/alternate payloads use "slektsnavn".
                last = navn_obj.get("etternavn") or navn_obj.get("slektsnavn") or ""
                middle = navn_obj.get("mellomnavn") or ""
                first = navn_obj.get("fornavn") or ""
                full = " ".join(part for part in (first, middle, last) if part).strip()
                name = full or navn_obj.get("navn") or r.get("enhet", {}).get("navn") or "Unnamed"
                role_type_obj = r.get("type") if isinstance(r.get("type"), dict) else {}
                role_code = role_type_obj.get("kode") or ""
                role_desc = role_type_obj.get("beskrivelse") or ""

                record = {
                    "name": name,
                    "role_code": role_code or group_type,
                    "role_description": role_desc or group_desc,
                    # Brreg marks a role as ended with ``avregistrert``; some
                    # payloads use the older ``fratrådt`` key. Treat either as
                    # inactive so former role holders are not presented as current.
                    "inactive": bool(r.get("avregistrert") or r.get("fratrådt")),
                }
                extracted_roles.append(record)

                # Check for CEO / Managing Director
                if (role_code == "DAGL" or "daglig leder" in role_desc.lower()) and not record["inactive"]:
                    if not managing_director:
                        managing_director = name
                # Check for Board Chair
                if (role_code == "LEDE" or "styrets leder" in role_desc.lower()) and not record["inactive"]:
                    if not board_chair:
                        board_chair = name
                # Check for Board Member
                if (role_code == "MEDL" or "styremedlem" in role_desc.lower()) and not record["inactive"]:
                    board_members.append(name)

    roles_checked = raw_roles is not None
    claims.append(create_claim_record("managing_director", managing_director, roles_eids))
    claims.append(create_claim_record("board_chair", board_chair, roles_eids))
    claims.append(create_claim_record("board_members", board_members, roles_eids, observed=roles_checked))
    claims.append(create_claim_record("all_roles", extracted_roles, roles_eids, observed=roles_checked))

    # 2. Operating Locations / Workplaces (Subunits)
    subunits_eids = [subunits_evidence_id] if subunits_evidence_id else []
    extracted_locations = []
    if raw_subunits:
        for sub in raw_subunits:
            name = sub.get("navn")
            sub_org = sub.get("organisasjonsnummer")
            addr_obj = sub.get("forretningsadresse") or sub.get("postadresse") or {}
            mun = addr_obj.get("kommune")
            poststed = addr_obj.get("poststed")
            emp = sub.get("antallAnsatte")
            extracted_locations.append({
                "organisation_number": sub_org,
                "name": name,
                "municipality": mun,
                "poststed": poststed,
                "employees": emp,
            })

    workplaces_checked = raw_subunits is not None
    claims.append(create_claim_record("workplaces_count", len(extracted_locations) if workplaces_checked else None, subunits_eids, observed=workplaces_checked))
    claims.append(create_claim_record("operating_workplaces", extracted_locations, subunits_eids, observed=workplaces_checked))

    # 3. Group Structure
    group_eids = [group_evidence_id] if group_evidence_id else []
    parent_entity = None
    if raw_group:
        parent = raw_group.get("overordnetEnhet") or raw_group.get("morselskap")
        if parent:
            parent_entity = {
                "organisation_number": parent.get("organisasjonsnummer"),
                "name": parent.get("navn"),
            }
    claims.append(create_claim_record("parent_entity", parent_entity, group_eids))

    return claims
