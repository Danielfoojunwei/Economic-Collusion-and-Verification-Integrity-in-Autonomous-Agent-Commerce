#!/usr/bin/env python3
"""Preflight or run exactly one supervised paid W11 market episode."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = str(WORKSPACE / ".local" / "share")
os.environ["XDG_CACHE_HOME"] = str(WORKSPACE / ".cache")
os.environ["XDG_CONFIG_HOME"] = str(WORKSPACE / ".config")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from agent_economic_trust.w11_market_remote import (  # noqa: E402
    MarketEpisodePlan, execute_one, preflight,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "execute-one"))
    parser.add_argument("--assignment-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--market-id", required=True)
    args = parser.parse_args()
    plan = MarketEpisodePlan(args.assignment_dir, args.output_dir, args.market_id)
    try:
        result = preflight(plan) if args.mode == "preflight" else execute_one(plan)
    except Exception as exc:
        # Provider/API errors can contain sensitive material; avoid printing it.
        print(f"W11 market stopped: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
