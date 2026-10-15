#!/usr/bin/env python3
"""Preflight or execute one frozen AP2 LIVE episode (never loops/retries)."""

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

from agent_economic_trust.ap2_live_remote import (  # noqa: E402
    Ap2LivePlan, execute_one, preflight)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    result = execute_one(Ap2LivePlan()) if args.execute else preflight(Ap2LivePlan())
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
