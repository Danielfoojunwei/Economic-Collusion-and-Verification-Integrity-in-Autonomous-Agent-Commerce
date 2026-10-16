#!/usr/bin/env python3
"""Recompute the compact service/payment-term manifest from saved raw evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_economic_trust.service_terms_suite import collect_bundle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    expected = json.loads((args.directory / "suite.json").read_text(encoding="utf-8"))
    commands = expected.pop("commands", None)
    actual = collect_bundle(args.directory)
    if actual != expected:
        raise ValueError("suite.json differs from independently recomputed raw evidence")
    print(json.dumps({"status": actual["status"], "service_cases": actual["service_case_count"],
                      "protocols": sorted(actual["protocols"]),
                      "saved_commands": len(commands or [])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

