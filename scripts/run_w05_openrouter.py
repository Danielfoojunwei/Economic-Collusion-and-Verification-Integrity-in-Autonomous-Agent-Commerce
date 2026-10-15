#!/usr/bin/env python3
"""Prepare or explicitly execute a bounded real-model ORBIT pilot.

Default mode is a read-only dry run. --init-ledger creates the project-wide
spend ledger with an explicit opening balance. --execute may incur OpenRouter
charges and is separately gated by the project environment variables.
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
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from agent_economic_trust.remote import RemotePlan, execute, preflight  # noqa: E402
from agent_economic_trust.remote_budget import create_ledger  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--project-cap-usd", type=Decimal, required=True)
    parser.add_argument("--sample-id", action="append", default=[])
    parser.add_argument("--output-dir", type=Path,
                        default=PROJECT_ROOT / "artifacts" / "gates" / "W05" / "real-run-001")
    parser.add_argument("--ledger", type=Path,
                        default=PROJECT_ROOT / "artifacts" / "budget" / "openrouter-ledger.jsonl")
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--max-input-bytes", type=int, default=32768)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="Permit bounded paid inference.")
    mode.add_argument("--init-ledger", action="store_true",
                      help="Create durable project-wide spend ledger; no inference.")
    parser.add_argument("--opening-spent-usd", type=Decimal,
                        help="Required with --init-ledger; include all prior project API charges.")
    args = parser.parse_args()
    plan = RemotePlan(
        model_id=args.model_id, sample_ids=tuple(args.sample_id or ["reconcile-001"]),
        output_dir=args.output_dir, ledger_path=args.ledger,
        cap_usd=args.project_cap_usd,
        max_output_tokens=args.max_output_tokens,
        max_input_bytes=args.max_input_bytes,
    )
    try:
        plan.validate()
        if args.init_ledger:
            if args.opening_spent_usd is None:
                parser.error("--init-ledger requires --opening-spent-usd")
            result = create_ledger(args.ledger, args.project_cap_usd, args.opening_spent_usd)
            print(json.dumps({"mode": "init-ledger", "ledger": result.snapshot()}, indent=2))
        else:
            if args.opening_spent_usd is not None:
                parser.error("--opening-spent-usd is valid only with --init-ledger")
            forecast = preflight(plan)
            if args.execute:
                print(json.dumps({"mode": "execute", "preflight": forecast}, indent=2))
                result = execute(plan, pricing=forecast["pricing"])
                print(json.dumps({"mode": "complete", **result}, indent=2))
            else:
                print(json.dumps({"mode": "dry-run", **forecast}, indent=2))
    except Exception as exc:
        # Error type only: provider exceptions can include replayable request data.
        print(f"W05 stopped: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
