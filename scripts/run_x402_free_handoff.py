#!/usr/bin/env python3
"""Dry-run, execute, or verify the frozen zero-price x402 A-to-B text study."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agent_economic_trust.x402_free_handoff_execute import (  # noqa: E402
    ASSIGNMENT_PATH, dry_run, execute, verify_execution,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Validate assignment and evidence; no network")
    mode.add_argument("--execute", type=Path, metavar="NEW_OUTPUT_DIR",
                      help="Attempt the frozen 60 pairs once; requires explicit environment gate")
    mode.add_argument("--verify", type=Path, metavar="RUN_OUTPUT_DIR",
                      help="Verify a completed or stopped run without model calls")
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
        # No raw provider text, exception body, URL, or key enters the console.
        print("x402 free handoff stopped: " + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
