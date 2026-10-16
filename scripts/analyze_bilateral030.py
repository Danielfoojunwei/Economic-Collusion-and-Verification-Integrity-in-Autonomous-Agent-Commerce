#!/usr/bin/env python3
"""Summarize a frozen BILATERAL030 assignment from independent row reviews.

This is a read-only command. It cannot run ORBIT, call a model, or transact.
Hashes must come from the separately sealed freeze/review inventory.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_economic_trust.bilateral030_analysis import analyze_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--assignment-path", required=True)
    parser.add_argument("--assignment-sha256", required=True)
    parser.add_argument("--reviews-path", required=True)
    parser.add_argument("--reviews-sha256", required=True)
    args = parser.parse_args()
    result = analyze_artifacts(
        args.evidence_root,
        {"path": args.assignment_path, "sha256": args.assignment_sha256},
        {"path": args.reviews_path, "sha256": args.reviews_sha256},
    )
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
