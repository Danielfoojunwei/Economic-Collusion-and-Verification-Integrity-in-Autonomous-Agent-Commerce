#!/usr/bin/env python3
"""Write or independently verify the append-only first-run W05 supplement."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_economic_trust.w05_supplement import verify_supplement, write_supplement


DEFAULT_DIR = Path("artifacts/gates/W05/real-run-001/reconcile-002")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("write", "verify"))
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args()
    result = write_supplement(args.evidence_dir) if args.action == "write" else verify_supplement(args.evidence_dir)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
