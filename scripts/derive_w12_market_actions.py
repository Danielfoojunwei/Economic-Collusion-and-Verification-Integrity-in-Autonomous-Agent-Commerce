#!/usr/bin/env python3
"""Derive read-only W12 financial actions from one verified saved W11 episode."""

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

from agent_economic_trust.w12_market_actions import export_market_actions  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", type=Path, required=True,
                        help="Saved W11 episode directory with events, Inspect log, and native receipts")
    parser.add_argument("--plan", type=Path, required=True,
                        help="Matching frozen W11 assignment directory")
    parser.add_argument("--output", type=Path, required=True,
                        help="New directory outside the W11 episode")
    args = parser.parse_args()
    try:
        result = export_market_actions(args.episode, args.plan, args.output)
    except Exception as exc:
        print(f"W12 action derivation stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    action = result["financial_actions"]
    print(json.dumps({"episode_id": action["episode_id"],
                      "oracle_status": action["oracle_status"],
                      "verdict": action["verdict"],
                      "transfers": len(action["transfers"]),
                      "inference_tier": result["provenance"]["inference_tier"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
