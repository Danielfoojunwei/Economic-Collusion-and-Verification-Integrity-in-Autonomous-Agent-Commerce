#!/usr/bin/env python3
"""Preflight or explicitly execute one ORBIT Meeting Scheduling held-out pilot."""

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

from agent_economic_trust.w18_meeting_remote import MeetingPlan, execute, preflight  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", default="openai/gpt-5.6-sol")
    parser.add_argument("--project-cap-usd", type=Decimal, default=Decimal("20"))
    parser.add_argument("--output-dir", type=Path, default=(
        PROJECT_ROOT / "artifacts" / "gates" / "G7" / "W18" / "live-heldout-pilot-001"
    ))
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--max-input-bytes", type=int, default=32768)
    parser.add_argument("--execute", action="store_true",
                        help="Run one bounded paid exploratory trial; default is dry-run.")
    args = parser.parse_args()
    plan = MeetingPlan(
        model_id=args.model_id, output_dir=args.output_dir,
        cap_usd=args.project_cap_usd,
        max_output_tokens=args.max_output_tokens,
        max_input_bytes=args.max_input_bytes,
    )
    try:
        forecast = preflight(plan)
        if not args.execute:
            print(json.dumps(forecast, indent=2, sort_keys=True))
            return
        if not forecast["ready_to_execute"]:
            raise RuntimeError("shared ledger cannot cover the worst-case reservation")
        print(json.dumps({"mode": "execute", "preflight": forecast}, indent=2, sort_keys=True))
        result = execute(plan)
        print(json.dumps({"mode": "complete", "result": result}, indent=2, sort_keys=True))
    except Exception as exc:
        # An upstream exception can include request content or credentials.
        print(f"W18 meeting pilot stopped: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
