#!/usr/bin/env python3
"""Dry-run, execute, or verify the frozen retail ACP mock-checkout study."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from agent_economic_trust.acp_free_checkout_execute import (  # noqa: E402
    ASSIGNMENT_PATH, dry_run, execute, verify_execution,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Validate source and prompts; no network")
    mode.add_argument("--execute", type=Path, metavar="NEW_OUTPUT_DIR",
                      help="Attempt frozen model pairs once; requires opt-in environment gates")
    mode.add_argument("--verify", type=Path, metavar="RUN_OUTPUT_DIR",
                      help="Replay a complete or stopped run without model calls")
    parser.add_argument("--assignment", type=Path, default=ASSIGNMENT_PATH,
                        help="Path to byte-identical prospectively frozen assignment")
    args = parser.parse_args()
    try:
        if args.dry_run:
            result = dry_run(args.assignment)
        elif args.verify is not None:
            result = verify_execution(args.verify)
        else:
            result = execute(args.execute, assignment_path=args.assignment)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0 if result["status"] != "STOPPED" else 1
    except Exception as exc:
        print("ACP free checkout study stopped: " + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
