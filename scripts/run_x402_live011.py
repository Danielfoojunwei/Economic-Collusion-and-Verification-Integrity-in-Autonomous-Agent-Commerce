#!/usr/bin/env python3
"""Default read-only x402 011 preflight; explicit `run` attempts one frozen row."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from agent_economic_trust.x402_live011_remote import (  # noqa: E402
    execute_one, preflight)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "run"),
                        nargs="?", default="preflight")
    args = parser.parse_args()
    result = preflight() if args.command == "preflight" else execute_one()
    print(json.dumps(result, sort_keys=True))
