#!/usr/bin/env python3
"""Frozen neutral-duty MPP text probe; dry-run is the default and uses no network."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agent_economic_trust.free_mpp_neutral_probe import (  # noqa: E402
    ARMS, SEED_HEX, make_schedule, run, verify_run,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-hex", default=SEED_HEX)
    parser.add_argument("--output-dir", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Validate assignments only (default)")
    mode.add_argument("--execute", action="store_true", help="Use exact zero-price OpenRouter routes")
    mode.add_argument("--verify", action="store_true", help="Check saved evidence without network")
    args = parser.parse_args()
    try:
        if args.execute:
            if args.output_dir is None:
                parser.error("--execute requires --output-dir")
            result = run(args.output_dir, args.seed_hex)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result["status"] in {"COMPLETE", "COMPLETE_WITH_MISSING"} else 1
        if args.verify:
            if args.output_dir is None:
                parser.error("--verify requires --output-dir")
            print(json.dumps(verify_run(args.output_dir), indent=2, sort_keys=True))
            return 0
        rows = make_schedule(args.seed_hex)
        counts = Counter((row["arm"], row["truth"]) for row in rows)
        print(json.dumps({
            "mode": "dry-run", "network_calls": 0, "planned_rows": len(rows),
            "seed_hex": args.seed_hex, "provider_model_id": rows[0]["provider_model_id"],
            "auditor_model_id": rows[0]["auditor_model_id"],
            "counts_by_arm": {arm: {truth: counts[(arm, truth)] for truth in ("BAD", "GOOD")}
                              for arm in ARMS}, "preview_only": True,
        }, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print("Neutral MPP probe stopped: " + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
