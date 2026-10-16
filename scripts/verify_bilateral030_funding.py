#!/usr/bin/env python3
"""Read-only verification of one public BILATERAL030 pre-view funding archive."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for local in (ROOT, ROOT / "scripts", ROOT / "src"):
    if str(local) not in sys.path:
        sys.path.insert(0, str(local))

from agent_economic_trust.bilateral030_funding_verifier import verify_funding_file  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="saved public funding archive JSON")
    parser.add_argument("--assignment", required=True, type=Path,
                        help="separately trusted public assignment JSON")
    parser.add_argument("--confirm-live", action="store_true",
                        help="query only this archive's still-live localhost Anvil read-only")
    args = parser.parse_args()
    assignment = json.loads(args.assignment.read_text())
    result = verify_funding_file(args.archive, assignment,
                                 confirm_live=args.confirm_live)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
