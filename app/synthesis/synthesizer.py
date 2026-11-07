"""Factual profile synthesis strictly bounded by validated evidence."""

from __future__ import annotations

from typing import Any, List, Optional

from app.output.models import Claim, Change


class Synthesizer:
    """Synthesizes readable profiles without inventing missing values."""

    @staticmethod
    def _format_amount(value: Any) -> str:
        if value is None:
            return "not reported"
        try:
            return f"{float(value):,.0f}"
        except (TypeError, ValueError):
            return str(value)

    @classmethod
    def synthesize_overview(
        cls,
        claims: List[Claim],
        changes: List[Change],
        provider: Optional[Any] = None,
    ) -> dict[str, Any]:
        claim_map = {c.field: c.value for c in claims}

        name = claim_map.get("legal_name") or "Entity"
        form = claim_map.get("organisation_form") or "unspecified form"
        municipality = claim_map.get("municipality") or "unspecified municipality"
        employees = claim_map.get("registered_employees")
        industry = claim_map.get("industry_description") or claim_map.get("industry_code")

        emp_str = (
            f"{employees} registered employees"
            if employees is not None
            else "employee count not reported"
        )
        ind_str = f"operating in {industry}" if industry else "industry not reported"
        overview_text = (
            f"{name} is a Norwegian company ({form}) registered in {municipality}, "
            f"{ind_str}, with {emp_str}."
        )

        revenue = claim_map.get("latest_revenue")
        operating_result = claim_map.get("latest_operating_result")
        currency = claim_map.get("financial_currency") or "NOK"
        period = claim_map.get("latest_reporting_period") or {}

        if revenue is not None:
            fin_text = (
                f"Latest annual accounts report revenue of "
                f"{cls._format_amount(revenue)} {currency}"
            )
            if operating_result is not None:
                fin_text += (
                    f" and operating result of "
                    f"{cls._format_amount(operating_result)} {currency}"
                )
            else:
                fin_text += " and no operating-result figure was reported"
            if isinstance(period, dict) and period.get("tilDato"):
                fin_text += f" for period ending {period['tilDato']}."
            else:
                fin_text += "."
        else:
            fin_text = "No normalized annual accounts returned in registry."

        ceo = claim_map.get("managing_director")
        chair = claim_map.get("board_chair")
        lead_parts = []
        if ceo:
            lead_parts.append(f"Managing Director: {ceo}")
        if chair:
            lead_parts.append(f"Board Chair: {chair}")
        leadership_text = (
            "; ".join(lead_parts) if lead_parts else "Leadership roles not observed."
        )

        website = claim_map.get("official_website")
        is_hiring = claim_map.get("hiring_active")
        jobs = claim_map.get("job_postings") or []

        web_parts = []
        if website:
            web_parts.append(f"Official website: {website}")
        if is_hiring is True:
            web_parts.append(f"Active hiring signal observed ({len(jobs)} postings captured)")
        elif is_hiring is False:
            web_parts.append("No active hiring signal observed on checked pages")
        else:
            web_parts.append("Hiring status not verified")
        digital_text = "; ".join(web_parts) if web_parts else "No digital presence verified."

        unknowns = []
        if revenue is None:
            unknowns.append("annual_accounts")
        if not website:
            unknowns.append("official_website")
        if not ceo:
            unknowns.append("managing_director")
        if is_hiring is None:
            unknowns.append("hiring_signals")

        result: dict[str, Any] = {
            "headline": f"{name} ({form})",
            "overview": overview_text,
            "financial_summary": fin_text,
            "leadership_summary": leadership_text,
            "digital_summary": digital_text,
            "explicit_unknowns": unknowns,
            "recent_changes_count": len(changes),
        }

        narrative = cls._optional_narrative(provider, result)
        if narrative:
            result["narrative"] = narrative

        return result

    @classmethod
    def _optional_narrative(
        cls, provider: Optional[Any], deterministic: dict[str, Any]
    ) -> Optional[str]:
        """Rephrase validated facts only, and only if every number stays grounded."""
        if provider is None or not getattr(provider, "enabled", False):
            return None
        if not getattr(provider, "available", lambda: False)():
            return None

        from app.llm.provider import is_grounded

        source_text = " ".join(
            str(deterministic.get(k) or "")
            for k in (
                "headline",
                "overview",
                "financial_summary",
                "leadership_summary",
                "digital_summary",
            )
        )
        system = (
            "You rewrite already-verified company facts into one short, neutral sentence. "
            "Do not add, change, or infer any fact or number. If unsure, repeat the facts verbatim."
        )
        candidate = provider.complete(system, source_text, max_tokens=160)
        if not candidate:
            return None
        candidate = candidate.strip()
        if not candidate or not is_grounded(candidate, source_text):
            return None
        return candidate
