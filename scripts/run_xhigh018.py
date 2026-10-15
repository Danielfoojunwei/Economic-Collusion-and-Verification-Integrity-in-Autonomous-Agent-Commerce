#!/usr/bin/env python3
"""Default read-only XHIGH018 preflight; explicit `run` attempts one frozen row."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from agent_economic_trust.xhigh018_remote import execute_one, preflight  # noqa: E402


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "run"),
                        nargs="?", default="preflight")
    args = parser.parse_args()
    result = preflight() if args.command == "preflight" else execute_one()
    print(json.dumps(result, sort_keys=True))
