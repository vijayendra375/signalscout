#!/usr/bin/env python3
"""Offline preflight audit for a SignalScout submission manifest and run output.

This tool validates local artifacts only. It does not contact Brreg or websites,
and it never treats a successful structural audit as proof of information recall.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.identity.validator import validate_org_number
from app.orchestrator.batch import load_input_organisations
from app.output.models import AvailabilityState, TerminalEnvelope
from app.output.serializer import validate_batch_envelopes

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def audit_manifest(path: str | Path, expected_count: int | None = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    try:
        raw = load_input_organisations(path)
    except Exception as exc:
        return [], [f"Could not read input manifest: {exc}"]

    valid: list[str] = []
    for index, value in enumerate(raw, start=1):
        try:
            valid.append(validate_org_number(value))
        except ValueError as exc:
            errors.append(f"Input record {index} is invalid: {exc}")

    if len(valid) != len(set(valid)):
        errors.append("Input manifest contains duplicate organisation numbers.")
    if expected_count is not None and len(valid) != expected_count:
        errors.append(f"Expected {expected_count} valid organisations; found {len(valid)}.")
    if not valid:
        errors.append("Input manifest contains no valid organisation numbers.")
    return valid, errors


def _valid_timestamp(value: str) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)
    except ValueError:
        return False


def audit_output(input_ids: list[str], output_path: str | Path) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    envelopes: list[TerminalEnvelope] = []
    path = Path(output_path)
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception as exc:
        return {}, [f"Could not read output JSONL: {exc}"]

    for line_no, line in enumerate(lines, start=1):
        try:
            item = json.loads(line)
            envelopes.append(TerminalEnvelope.model_validate(item))
        except Exception as exc:
            errors.append(f"Output line {line_no} is not a valid terminal envelope: {exc}")

    if len(envelopes) != len(input_ids):
        errors.append(f"Output has {len(envelopes)} envelopes for {len(input_ids)} valid inputs.")
    actual_ids = [env.organisation_number for env in envelopes]
    if actual_ids != input_ids:
        errors.append("Output organisation numbers do not exactly match the validated input order.")

    contract = validate_batch_envelopes(envelopes, expected_count=len(input_ids))
    if not contract["passed"]:
        errors.append("Output failed the batch contract checks.")

    evidence_errors = 0
    for env in envelopes:
        evidence_by_id = {ev.id: ev for ev in env.evidence}
        if len(evidence_by_id) != len(env.evidence):
            evidence_errors += 1
        if not _valid_timestamp(env.run.started_at) or not _valid_timestamp(env.run.completed_at):
            evidence_errors += 1
        for ev in env.evidence:
            parsed_url = urlparse(ev.source_url)
            if parsed_url.scheme not in {"https", "http"} or not parsed_url.hostname:
                evidence_errors += 1
            if not _valid_timestamp(ev.retrieved_at):
                evidence_errors += 1
            if not SHA256_RE.fullmatch(ev.content_sha256 or ""):
                evidence_errors += 1
            if not ev.claim_span.strip():
                evidence_errors += 1
        for claim in env.claims:
            if claim.availability == AvailabilityState.AVAILABLE and claim.value is None:
                evidence_errors += 1
            if any(eid not in evidence_by_id for eid in claim.evidence_ids):
                evidence_errors += 1

    if evidence_errors:
        errors.append(f"Found {evidence_errors} evidence/claim integrity issue(s).")

    summary = {
        "envelope_count": len(envelopes),
        "expected_envelope_count": len(input_ids),
        "batch_contract": contract,
        "evidence_integrity_issues": evidence_errors,
    }
    return summary, errors


def audit_run_report(
    report_path: str | Path,
    max_requests: int,
    max_runtime_seconds: float,
    max_cost_usd: float,
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    try:
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
        budget = report.get("budget") or {}
        requests = int(budget.get("requests", 0))
        elapsed_ms = int(report.get("elapsed_ms", budget.get("runtime_ms", 0)))
        cost = float(budget.get("third_party_cost_usd", 0.0))
        if report.get("validation", {}).get("passed") is not True:
            errors.append("Run report does not record a passing batch validation.")
        if report.get("emitted_envelopes") != report.get("input_count"):
            errors.append("Run report input_count and emitted_envelopes do not match.")
        if not math.isfinite(cost) or cost < 0:
            errors.append("Run report contains an invalid third-party cost.")
        if requests < 0 or elapsed_ms < 0:
            errors.append("Run report contains a negative request count or runtime.")
        if requests > max_requests:
            errors.append(f"Request budget exceeded: {requests} > {max_requests}.")
        if elapsed_ms > max_runtime_seconds * 1000:
            errors.append(f"Runtime budget exceeded: {elapsed_ms / 1000:.2f}s > {max_runtime_seconds:.2f}s.")
        if cost > max_cost_usd:
            errors.append(f"Third-party cost exceeded: ${cost:.4f} > ${max_cost_usd:.4f}.")
        return {
            "input_count": report.get("input_count"),
            "emitted_envelopes": report.get("emitted_envelopes"),
            "requests": requests,
            "elapsed_ms": elapsed_ms,
            "third_party_cost_usd": cost,
            "limits": {
                "max_requests": max_requests,
                "max_runtime_seconds": max_runtime_seconds,
                "max_cost_usd": max_cost_usd,
            },
        }, errors
    except Exception as exc:
        return {}, [f"Could not audit run report: {exc}"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline SignalScout submission preflight audit")
    parser.add_argument("--input", required=True, help="JSON, JSONL, or text organisation-number manifest")
    parser.add_argument("--expected-count", type=int, default=None, help="Require exactly this many valid unique IDs")
    parser.add_argument("--output", help="Optional terminal-envelope JSONL to audit")
    parser.add_argument("--report", help="Optional machine run report JSON to audit")
    parser.add_argument("--max-requests", type=int, default=2000)
    parser.add_argument("--max-runtime-seconds", type=float, default=2700.0)
    parser.add_argument("--max-cost-usd", type=float, default=10.0)
    args = parser.parse_args()

    input_ids, errors = audit_manifest(args.input, args.expected_count)
    result: dict[str, Any] = {
        "passed": False,
        "manifest": {"valid_unique_organisation_count": len(input_ids)},
    }
    if args.output:
        output_summary, output_errors = audit_output(input_ids, args.output)
        result["output"] = output_summary
        errors.extend(output_errors)
    if args.report:
        report_summary, report_errors = audit_run_report(
            args.report, args.max_requests, args.max_runtime_seconds, args.max_cost_usd
        )
        result["run_report"] = report_summary
        errors.extend(report_errors)
        if report_summary.get("input_count") != len(input_ids):
            errors.append("Run report input_count does not match the validated input manifest.")
        if report_summary.get("emitted_envelopes") != len(input_ids):
            errors.append("Run report emitted_envelopes does not match the validated input manifest.")

    result["errors"] = errors
    result["passed"] = not errors
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
