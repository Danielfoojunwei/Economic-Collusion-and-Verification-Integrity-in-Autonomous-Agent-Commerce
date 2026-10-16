#!/usr/bin/env python3
"""Reverify eight scripted FEE012 native controls for XHIGH017 without model calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from agent_economic_trust.xhigh017_offline import ARCHIVE, run, verify  # noqa: E402


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "verify"), nargs="?", default="verify")
    args = parser.parse_args()
    print(json.dumps(run() if args.command == "run" else verify(), sort_keys=True))
