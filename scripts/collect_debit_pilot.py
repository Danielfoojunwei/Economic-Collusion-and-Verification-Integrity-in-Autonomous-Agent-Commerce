#!/usr/bin/env python3
"""Reopen saved pilot 003 evidence; write one new descriptive ITT collection."""

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

from agent_economic_trust.debit_pilot_reporting import collect_debit_pilot  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assignment", type=Path,
                        default=ROOT / "artifacts/gates/MECHANISM_PILOT/assignment-003")
    parser.add_argument("--runs", type=Path,
                        default=ROOT / "artifacts/gates/MECHANISM_PILOT/runs-003")
    parser.add_argument("--ledger", type=Path,
                        default=ROOT / "artifacts/budget/openrouter-ledger.jsonl")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("refusing to overwrite an existing collection")
    try:
        report = collect_debit_pilot(args.assignment, args.runs, args.ledger)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)
            stream.write("\n")
    except Exception as exc:
        print(f"debit pilot collection stopped: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps({
        "pilot_id": report["pilot_id"],
        "planned_episodes": report["planned_episodes"],
        "completed_episodes": report["completed_episodes"],
        "inference_tier": report["inference_tier"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
