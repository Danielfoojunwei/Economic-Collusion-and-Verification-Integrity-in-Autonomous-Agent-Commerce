#!/usr/bin/env python3
"""Read-only FEE011 preflight by default; --execute permits one assigned row."""

from __future__ import annotations

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

from agent_economic_trust.fee011_remote import Fee011Plan, execute_one, preflight


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    result = execute_one(Fee011Plan()) if args.execute else preflight(Fee011Plan())
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
