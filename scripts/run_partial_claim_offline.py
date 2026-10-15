#!/usr/bin/env python3
"""Run or replay scripted local ERC-8183 partial-claim controls; zero model calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_economic_trust.partial_claim_offline import ARCHIVE, run, verify


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "verify"))
    parser.add_argument("--path", type=Path, default=ARCHIVE)
    args = parser.parse_args()
    result = run(args.path) if args.command == "run" else verify(args.path)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
