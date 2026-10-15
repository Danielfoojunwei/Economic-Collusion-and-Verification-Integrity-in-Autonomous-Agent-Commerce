#!/usr/bin/env python3
"""Reverify all completed W11 episodes and retain every assigned denominator."""

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

from agent_economic_trust.w11_market_analysis import collect_market_itt  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = collect_market_itt(args.plan, args.runs)
        if args.output.exists():
            raise FileExistsError("refusing to overwrite an ITT analysis")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, sort_keys=True) + "\n")
    except Exception as exc:
        print(f"W11 ITT collection stopped: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps({"markets": result["planned_markets"],
                      "episodes": result["planned_episodes"],
                      "completed_episodes": result["completed_episodes"],
                      "inference_tier": result["inference_tier"]}, sort_keys=True))


if __name__ == "__main__":
    main()
