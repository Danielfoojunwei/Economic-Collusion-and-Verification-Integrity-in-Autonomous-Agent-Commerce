#!/usr/bin/env python3
"""Prepare, inspect, execute, or verify the zero-price AP2 mandate study."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from agent_economic_trust import ap2_free_mandate_study as study  # noqa: E402
from agent_economic_trust import ap2_free_mandate_execute as runner  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--prepare", type=Path, metavar="NEW_ASSIGNMENT_JSON",
                         help="Sign and freeze 140 local AP2 mandates; no model calls")
    actions.add_argument("--verify-assignment", type=Path, metavar="ASSIGNMENT_JSON")
    actions.add_argument("--dry-run", action="store_true",
                         help="Verify frozen scope, assignment, and prompts; no model calls")
    actions.add_argument("--execute", type=Path, metavar="NEW_OUTPUT_DIR",
                         help="Run once with free exact model routes and explicit env gate")
    actions.add_argument("--verify", type=Path, metavar="RUN_OUTPUT_DIR")
    parser.add_argument("--assignment", type=Path, default=runner.ASSIGNMENT_PATH)
    args = parser.parse_args()
    try:
        if args.prepare is not None:
            result = study.prepare_assignment(args.prepare)
        elif args.verify_assignment is not None:
            result = study.verify_assignment(args.verify_assignment)
        elif args.dry_run:
            result = runner.dry_run(args.assignment)
        elif args.execute is not None:
            result = runner.execute(args.execute, assignment_path=args.assignment)
        else:
            result = runner.verify_execution(args.verify)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 1 if result.get("status") == "STOPPED" else 0
    except Exception as exc:
        # Never print raw model replies, mandate JWTs, URLs, or credentials.
        print("AP2 mandate study failed: " + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
