#!/usr/bin/env python3
"""Read saved OPEN006 evidence and write one new ITT collection."""
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
from agent_economic_trust.open006_reporting import collect_open006
from agent_economic_trust.open006_remote import ASSIGNMENT_DIR, RUNS_DIR
from agent_economic_trust.open006_plan import CANONICAL_LEDGER_PATH as PROJECT_LEDGER_PATH


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    report = collect_open006(ASSIGNMENT_DIR, RUNS_DIR, PROJECT_LEDGER_PATH)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(report, f, sort_keys=True, separators=(",", ":"), allow_nan=False)
        f.write("\n")
    print(json.dumps({k: report[k] for k in ("study_id", "planned_episodes", "completed_episodes")}))


if __name__ == "__main__":
    main()
