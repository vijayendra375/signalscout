"""Financial statement extractor for filed annual accounts."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from app.output.models import Claim
from app.verification.validator import create_claim_record, normalize_metric


def _get_nested(data: Any, *keys: str) -> Any:
    for k in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(k)
    return data


def extract_financials(raw_accounts: Optional[list[dict[str, Any]]], evidence_id: Optional[str]) -> List[Claim]:
    """Extract claims belonging to the Financials category."""
    claims: List[Claim] = []
    eids = [evidence_id] if evidence_id else []

    if not raw_accounts:
        fields = [
            "financial_records", "latest_revenue", "latest_operating_result",
            "latest_annual_result", "latest_total_assets", "latest_total_equity",
            "latest_total_debt", "financial_currency", "latest_reporting_period"
        ]
        for f in fields:
            claims.append(create_claim_record(f, None, []))
        return claims

    # Sort records chronologically descending by reporting period tilDato or year
    sorted_records = sorted(
        raw_accounts,
        key=lambda item: _get_nested(item, "regnskapsperiode", "tilDato") or str(item.get("aar") or ""),
        reverse=True,
    )
    
    normalized_list = []
    for item in sorted_records[:5]:
        period = item.get("regnskapsperiode") or {}
        currency = item.get("valuta") or "NOK"
        
        # Revenue
        rev = (
            _get_nested(item, "resultatregnskapResultat", "driftsresultat", "driftsinntekter", "sumDriftsinntekter")
            or _get_nested(item, "resultatregnskapResultat", "driftsresultat", "driftsinntekter", "salgsinntekter")
        )
        op_res = _get_nested(item, "resultatregnskapResultat", "driftsresultat", "driftsresultat")
        ann_res = _get_nested(item, "resultatregnskapResultat", "aarsresultat")
        assets = _get_nested(item, "eiendeler", "sumEiendeler")
        equity = _get_nested(item, "egenkapitalGjeld", "egenkapital", "sumEgenkapital")
        debt = _get_nested(item, "egenkapitalGjeld", "gjeldOversikt", "sumGjeld")
        
        normalized_list.append({
            "year": item.get("aar") or (period.get("tilDato", "")[:4] if period.get("tilDato") else None),
            "period": period,
            "currency": currency,
            "revenue": normalize_metric(rev),
            "operating_result": normalize_metric(op_res),
            "annual_result": normalize_metric(ann_res),
            "total_assets": normalize_metric(assets),
            "total_equity": normalize_metric(equity),
            "total_debt": normalize_metric(debt),
        })

    # Summary claims from latest statement
    latest = normalized_list[0] if normalized_list else {}
    claims.append(create_claim_record("financial_records", normalized_list, eids))
    claims.append(create_claim_record("latest_revenue", latest.get("revenue"), eids))
    claims.append(create_claim_record("latest_operating_result", latest.get("operating_result"), eids))
    claims.append(create_claim_record("latest_annual_result", latest.get("annual_result"), eids))
    claims.append(create_claim_record("latest_total_assets", latest.get("total_assets"), eids))
    claims.append(create_claim_record("latest_total_equity", latest.get("total_equity"), eids))
    claims.append(create_claim_record("latest_total_debt", latest.get("total_debt"), eids))
    claims.append(create_claim_record("financial_currency", latest.get("currency") or "NOK", eids))
    claims.append(create_claim_record("latest_reporting_period", latest.get("period") or None, eids))

    return claims
