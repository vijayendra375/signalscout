#!/usr/bin/env python3
"""Compute material changes between two envelope snapshots (offline, deterministic).

Accepts a previous-snapshot JSONL and a current JSONL and emits the field-level
changes per organisation number, reusing the same ChangeDetector the live
pipeline uses. Missing/blocked data is never reported as a change.

Usage:
    python scripts/diff_snapshots.py \
        --previous out/smoke_100_envelopes.jsonl \
        --current  out/smoke_100_envelopes.jsonl \
        --output   out/changes.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.output.models import AvailabilityState, Claim
from app.temporal.change_detector import ChangeDetector


def _load(path: Path) -> dict:
    by_org: dict = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        env = json.loads(line)
        by_org[env["organisation_number"]] = {
            c["field"]: c for c in env.get("claims", [])
        }
    return by_org


def main() -> None:
    parser = argparse.ArgumentParser(description="Diff two SignalScout envelope snapshots")
    parser.add_argument("--previous", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    previous = _load(Path(args.previous))
    current = _load(Path(args.current))

    report = {"organisations": [], "total_changes": 0}
    for org, current_claims in current.items():
        prior = previous.get(org)
        if prior is None:
            continue
        prior_values = {
            field: claim.get("value")
            for field, claim in prior.items()
            if claim.get("availability") == AvailabilityState.AVAILABLE.value
        }
        claims = [
            Claim(
                field=c["field"],
                value=c.get("value"),
                availability=AvailabilityState(c["availability"]),
            )
            for c in current_claims.values()
        ]
        changes = ChangeDetector.detect_changes(prior_values, claims)
        if changes:
            report["total_changes"] += len(changes)
            report["organisations"].append({
                "organisation_number": org,
                "changes": [c.model_dump(mode="json") for c in changes],
            })

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Detected {report['total_changes']} material change(s); wrote {out}")


if __name__ == "__main__":
    main()
