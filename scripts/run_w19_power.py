#!/usr/bin/env python3
"""Read-only W19 prospective power scenarios from independently verified G4 data."""

from __future__ import annotations

import argparse
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402
from agent_economic_trust.w19_power import PilotCalibration, simulate_power  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs-per-cell-truth-block", type=int, required=True)
    parser.add_argument("--tasks-per-pair", type=int, default=1)
    parser.add_argument("--task-families", type=int, required=True)
    parser.add_argument("--model-versions", type=int, required=True)
    parser.add_argument("--rho", type=float, required=True)
    parser.add_argument("--repetitions", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20261015)
    args = parser.parse_args()

    if args.output.exists():
        raise FileExistsError("power output already exists; preserve prior scenarios")
    pilot_bytes = args.pilot.read_bytes()
    pilot = PilotCalibration.parse(json.loads(pilot_bytes))
    manifest_sha = sha256(args.source_manifest.read_bytes()).hexdigest()
    if manifest_sha != pilot.source_run_sha256:
        raise ValueError("pilot source manifest SHA-256 does not match calibration")
    ledger_path = ROOT / "artifacts" / "budget" / "openrouter-ledger.jsonl"
    snapshot = BudgetLedger(ledger_path).snapshot()
    if snapshot["cap_usd"] != "20" or snapshot["blocked"]:
        raise ValueError("project-wide USD 20 budget ledger unavailable or blocked")
    output = simulate_power(
        pilot,
        pairs_per_cell_truth_block=args.pairs_per_cell_truth_block,
        tasks_per_pair=args.tasks_per_pair,
        task_families=args.task_families,
        model_versions=args.model_versions,
        rho=args.rho, repetitions=args.repetitions, seed=args.seed,
        remaining_authorized_usd=Decimal(snapshot["available_usd"]),
    )
    output["pilot_calibration_sha256"] = sha256(pilot_bytes).hexdigest()
    output["source_manifest_sha256"] = manifest_sha
    output["budget_ledger_last_hash"] = snapshot["last_hash"]
    output["source_code_sha256"] = {
        path: sha256((ROOT / path).read_bytes()).hexdigest()
        for path in (
            "src/agent_economic_trust/w19_analysis.py",
            "src/agent_economic_trust/w19_power.py",
            "scripts/run_w19_power.py",
        )
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(args.output),
        "status": output["status"],
        "pairs": output["pairs"],
        "projected_model_spend_usd": output["projected_model_spend_usd"],
        "within_current_authorized_spend": output["within_current_authorized_spend"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
