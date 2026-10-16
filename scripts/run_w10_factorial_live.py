#!/usr/bin/env python3
"""Dry run or explicitly execute one frozen W10 factorial trial.

The default path reads public model pricing and the shared USD 20 ledger. It
does not start Anvil, call the model, or send a payment. ``--execute`` requires
one trial ID and a new output directory; the runner enforces the native fee,
paid-call limits, saved Inspect audit, and native task settlement.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = str(WORKSPACE_ROOT / ".local" / "share")
os.environ["XDG_CACHE_HOME"] = str(WORKSPACE_ROOT / ".cache")
os.environ["XDG_CONFIG_HOME"] = str(WORKSPACE_ROOT / ".config")
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from agent_economic_trust.w10_factorial_remote import (  # noqa: E402
    FactorialTrialPlan, execute, preflight,
)


DEFAULT_ASSIGNMENT_DIR = (
    PROJECT_ROOT / "artifacts" / "gates" / "W10_DESIGN" / "assignment-003"
)


def _forecast_summary(forecast: dict, plan: FactorialTrialPlan, *, mode: str) -> dict:
    ledger = forecast["ledger"]
    return {
        "mode": mode,
        "trial_id": forecast["trial_id"],
        "pair_id": forecast["pair_id"],
        "assignment_manifest_sha256": forecast["assignment_manifest_sha256"],
        "R": forecast["R"], "S": forecast["S"], "P": forecast["P"],
        "model_id": forecast["model_id"],
        "reasoning_effort": forecast["reasoning_effort"],
        "project_cap_usd": forecast["project_cap_usd"],
        "max_provider_calls": forecast["max_provider_calls"],
        "worst_case_reservation_usd": forecast["worst_case_reservation_usd"],
        "ledger_available_usd": ledger["available_usd"],
        "ledger_blocked": ledger["blocked"],
        "ready_to_execute": forecast["ready_to_execute"],
        "output_dir": str(plan.output_dir.resolve()),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", required=True,
                        help="Explicit approved model: openai/gpt-5.6-sol")
    parser.add_argument("--project-cap-usd", required=True,
                        help="Explicit total project cap: 20")
    parser.add_argument("--assignment-dir", type=Path, default=DEFAULT_ASSIGNMENT_DIR)
    parser.add_argument("--trial-id", required=True,
                        help="Exactly one ID from the frozen assignment")
    parser.add_argument("--output-dir", type=Path,
                        help="Fresh per-trial evidence directory; required for --execute")
    parser.add_argument("--execute", action="store_true",
                        help="Execute one bounded paid trial; default is read-only dry run")
    args = parser.parse_args(argv)

    try:
        if args.execute and args.output_dir is None:
            raise ValueError("--execute requires --output-dir")
        output_dir = args.output_dir or (
            PROJECT_ROOT / "artifacts" / "gates" / "G4" / "live-trials"
            / args.trial_id
        )
        plan = FactorialTrialPlan(
            model_id=args.model_id, trial_id=args.trial_id,
            assignment_dir=args.assignment_dir, output_dir=output_dir,
            cap_usd=Decimal(args.project_cap_usd),
        )
        forecast = preflight(plan)
        mode = "execute_preflight" if args.execute else "dry-run"
        print(json.dumps(_forecast_summary(forecast, plan, mode=mode), sort_keys=True),
              flush=True)
        if not args.execute:
            return
        if not forecast["ready_to_execute"]:
            raise RuntimeError("budget or run ID is not ready")
        result = execute(plan)
        record = result["record"]
        print(json.dumps({
            "mode": "complete", "trial_id": record["trial_id"],
            "status": record["status"], "verdict": record["verdict"],
            "checked": record["checked"],
            "payment_status": record["payment_status"],
            "model_calls": record["model_calls"],
            "model_cost_usd_estimate": record["model_cost_usd_estimate"],
            "run_manifest_sha256": result["manifest_sha256"],
            "output_dir": str(plan.output_dir.resolve()),
        }, sort_keys=True))
    except Exception as exc:
        # Provider exceptions can contain request payloads or credentials.
        print(f"W10 factorial stopped: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
