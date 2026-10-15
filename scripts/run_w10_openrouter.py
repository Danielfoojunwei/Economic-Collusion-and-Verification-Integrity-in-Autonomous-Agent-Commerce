#!/usr/bin/env python3
"""Dry run or explicitly execute one protected-receipt OpenRouter world."""

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

from agent_economic_trust.w10_remote import ProtectedPlan, execute, preflight  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--project-cap-usd", type=Decimal, required=True)
    parser.add_argument("--world", choices=("good", "bad"), required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--max-input-bytes", type=int, default=32768)
    parser.add_argument("--execute", action="store_true",
                        help="Permit one bounded paid world; default is read-only dry run.")
    args = parser.parse_args()
    output = args.output_dir or (
        PROJECT_ROOT / "artifacts" / "gates" / "W10_PILOT" / f"real-{args.world}-001"
    )
    plan = ProtectedPlan(
        model_id=args.model_id, world=args.world, output_dir=output,
        cap_usd=args.project_cap_usd,
        max_output_tokens=args.max_output_tokens,
        max_input_bytes=args.max_input_bytes,
    )
    try:
        forecast = preflight(plan)
        if not args.execute:
            print(json.dumps(forecast, indent=2, sort_keys=True))
            return
        print(json.dumps({"mode": "execute", "preflight": forecast}, indent=2, sort_keys=True))
        result = execute(plan, pricing=forecast["pricing"])
        print(json.dumps({"mode": "complete", **result}, indent=2, sort_keys=True))
    except Exception as exc:
        # Provider exception messages can include request data or credentials.
        print(f"W10 pilot stopped: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
