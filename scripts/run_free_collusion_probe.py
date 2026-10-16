#!/usr/bin/env python3
"""Frozen, zero-price exploratory two-agent ERC-8183 or MPP text probe.

Default is a network-free dry run. --execute is the only mode that contacts
OpenRouter. It requires an explicit output directory that does not exist.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agent_economic_trust.free_collusion_probe import (  # noqa: E402
    DEFAULT_SEED, ERC8183, MPP, ProbeError, make_schedule, run, verify_run,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=(ERC8183, MPP), default=ERC8183)
    parser.add_argument("--seed-hex", default=DEFAULT_SEED,
                        help="32-byte lowercase hex assignment seed")
    parser.add_argument("--output-dir", type=Path,
                        help="New directory for --execute, existing directory for --verify")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="Run bounded zero-price OpenRouter calls")
    mode.add_argument("--verify", action="store_true", help="Verify a saved run without network")
    mode.add_argument("--dry-run", action="store_true", help="Validate schedule without network (default)")
    args = parser.parse_args()
    try:
        if args.execute:
            if args.output_dir is None:
                parser.error("--execute requires --output-dir")
            result = run(args.output_dir, args.seed_hex, scenario=args.scenario)
            print(json.dumps(result, sort_keys=True, indent=2))
            return 0 if result["status"] in {"COMPLETE", "COMPLETE_WITH_MISSING"} else 1
        if args.verify:
            if args.output_dir is None:
                parser.error("--verify requires --output-dir")
            result = verify_run(args.output_dir)
            print(json.dumps(result, sort_keys=True, indent=2))
            return 0
        rows = make_schedule(args.seed_hex, args.scenario)
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["arm"]] = counts.get(row["arm"], 0) + 1
        print(json.dumps({"mode": "dry-run", "network_calls": 0,
                          "scenario": args.scenario, "seed_hex": args.seed_hex,
                          "assigned_rows": len(rows), "arm_counts": counts,
                          "provider_model_id": rows[0]["provider_model_id"],
                          "auditor_model_id": rows[0]["auditor_model_id"],
                          "preview_only": True}, sort_keys=True, indent=2))
        return 0
    except (ProbeError, ValueError, FileExistsError, OSError, KeyError) as exc:
        # Exception text from an HTTP request could contain credentials or model content.
        print("Free probe stopped: " + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
