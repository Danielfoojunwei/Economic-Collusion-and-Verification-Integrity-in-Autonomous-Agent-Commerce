#!/usr/bin/env python3
"""Read-only preflight by default; explicit opt-in executes one frozen MPP009 row."""
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

from agent_economic_trust.mpp009_remote import Mpp009Plan, execute_one, preflight


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        result = execute_one(Mpp009Plan()) if args.execute else preflight(Mpp009Plan())
    except Exception as exc:
        print(f"MPP009 stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
