#!/usr/bin/env python3
"""Read-only verification of one terminal BILATERAL030 local native archive."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for local in (ROOT, ROOT / "scripts", ROOT / "src"):
    if str(local) not in sys.path:
        sys.path.insert(0, str(local))

from agent_economic_trust.bilateral030_native_verifier import verify_file  # noqa: E402
from agent_economic_trust.bilateral030_plan import Bilateral030Row  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path, help="saved native-evidence.json")
    parser.add_argument("--row", required=True, type=Path,
                        help="separately trusted single assigned row JSON")
    args = parser.parse_args()
    assigned = Bilateral030Row(**json.loads(args.row.read_text()))
    result = verify_file(args.evidence, assigned)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
