#!/usr/bin/env python3
"""Collect the frozen mixed-model denominator from raw archives and receipts."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = str(ROOT.parent / ".local/share")
os.environ["XDG_CACHE_HOME"] = str(ROOT.parent / ".cache")
os.environ["XDG_CONFIG_HOME"] = str(ROOT.parent / ".config")
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from agent_economic_trust.mpp008_remote import ASSIGNMENT, RUNS
from agent_economic_trust.mpp008_reporting import collect
from agent_economic_trust.mpp008_plan import CANONICAL_LEDGER_PATH


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = collect(ASSIGNMENT, RUNS, CANONICAL_LEDGER_PATH)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
        stream.write("\n")
    print(json.dumps({"study_id": report["study_id"],
                      "planned_episodes": report["planned_episodes"],
                      "completed_episodes": report["completed_episodes"]}))


if __name__ == "__main__":
    main()
