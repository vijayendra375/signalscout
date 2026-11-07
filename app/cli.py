"""SignalScout Command Line Interface."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from app.budget.tracker import BudgetTracker
from app.config.settings import settings
from app.orchestrator.batch import BatchRunner, load_input_organisations
from app.output.serializer import validate_batch_envelopes
from app.ui.dashboard import generate_dashboard_html


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SignalScout — Autonomous, evidence-backed Norwegian company intelligence agent."
    )
    parser.add_argument("--input", "-i", required=True, help="Path to input organisation numbers file (JSON, JSONL, TXT)")
    parser.add_argument("--output", "-o", default="out/envelopes.jsonl", help="Path to output envelopes JSONL")
    parser.add_argument("--report", "-r", default="out/report.json", help="Path to machine-readable run report JSON")
    parser.add_argument("--dashboard", "-d", default="out/dashboard.html", help="Path to interactive HTML dashboard")
    parser.add_argument("--workers", "-w", type=int, default=settings.max_workers, help="Concurrent worker threads")
    parser.add_argument("--run-id", default="run-signalscout-1", help="Unique identifier for the research run")
    parser.add_argument("--expected-count", type=int, default=None, help="Expected number of companies in input")
    parser.add_argument("--resume", action="store_true", help="Resume partially completed batch from output file")
    
    args = parser.parse_args()
    start_time = time.time()

    print(f"[*] SignalScout starting run '{args.run_id}'...")
    print(f"[*] Reading inputs from: {args.input}")
    
    orgs = load_input_organisations(args.input)
    print(f"[*] Loaded {len(orgs)} unique organisation numbers.")
    
    if args.expected_count is not None and len(orgs) != args.expected_count:
        print(f"[!] Warning: Loaded {len(orgs)} organisations, but expected {args.expected_count}.", file=sys.stderr)

    def on_progress(done: int, total: int, current_org: str) -> None:
        pct = (done / total) * 100
        print(f"[{done}/{total}] ({pct:.1f}%) Completed: {current_org}", end="\r", flush=True)

    runner = BatchRunner(
        max_workers=args.workers,
        progress_callback=on_progress,
    )
    
    envelopes = runner.run_batch(
        orgs=orgs,
        output_path=args.output,
        run_id=args.run_id,
        resume=args.resume,
    )
    print()

    if runner.invalid_inputs:
        print(
            f"[!] Rejected {len(runner.invalid_inputs)} malformed organisation number(s); "
            "they were not published as company profiles.",
            file=sys.stderr,
        )

    # Validate output contract invariants against validated inputs.
    validation = validate_batch_envelopes(envelopes, expected_count=len(runner.valid_orgs))
    
    # Generate dashboard
    if args.dashboard:
        generate_dashboard_html(envelopes, args.dashboard)
        print(f"[*] Evidence dashboard saved to: {args.dashboard}")

    # Build report
    elapsed_ms = int((time.time() - start_time) * 1000)
    report_data = {
        "agent": "SignalScout",
        "version": "1.0.0",
        "run_id": args.run_id,
        "input_count": len(orgs),
        "emitted_envelopes": len(envelopes),
        "elapsed_ms": elapsed_ms,
        "validation": validation,
        "budget": runner.budget.summary(),
        "output_file": str(args.output),
    }

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    
    print(f"[*] Run report written to: {args.report}")
    print(f"[*] Batch validation passed: {validation['passed']}")
    
    if not validation["passed"]:
        print("[!] Validation errors:", validation.get("checks"), file=sys.stderr)
        sys.exit(1)
        
    print("[+] SignalScout run completed successfully.")


if __name__ == "__main__":
    main()
