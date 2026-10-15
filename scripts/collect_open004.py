#!/usr/bin/env python3
"""Read saved OPEN004 evidence and write one new ITT collection."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from agent_economic_trust.open004_reporting import collect_open004
from agent_economic_trust.open004_remote import ASSIGNMENT_DIR, RUNS_DIR
from agent_economic_trust.remote import PROJECT_LEDGER_PATH


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    report = collect_open004(ASSIGNMENT_DIR, RUNS_DIR, PROJECT_LEDGER_PATH)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(report, f, sort_keys=True, separators=(",", ":"), allow_nan=False)
        f.write("\n")
    print(json.dumps({k: report[k] for k in ("study_id", "planned_episodes", "completed_episodes")}))


if __name__ == "__main__":
    main()
