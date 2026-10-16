#!/usr/bin/env python3
"""Preview the MPP neutral replication offline; execution requires explicit gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agent_economic_trust import mpp_neutral_replication_execute as execution  # noqa: E402
from agent_economic_trust import mpp_neutral_replication_plan as plan  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-hex", help="Required explicit fresh seed for --execute")
    parser.add_argument("--output-dir", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Network-free preview (default)")
    mode.add_argument("--execute", action="store_true", help="Run exact zero-price model routes")
    mode.add_argument("--verify", action="store_true", help="Verify saved run without network")
    args = parser.parse_args()
    try:
        if args.verify:
            if args.output_dir is None:
                parser.error("--verify requires --output-dir")
            result = execution.verify_run(args.output_dir)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.execute:
            if args.output_dir is None or args.seed_hex is None:
                parser.error("--execute requires --output-dir and an explicitly frozen --seed-hex")
            result = execution.run(args.output_dir, args.seed_hex)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result["status"] in {"COMPLETE", "COMPLETE_WITH_MISSING"} else 1
        result = plan.preview(args.seed_hex or "12" * 32)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print("MPP neutral replication stopped: " + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
