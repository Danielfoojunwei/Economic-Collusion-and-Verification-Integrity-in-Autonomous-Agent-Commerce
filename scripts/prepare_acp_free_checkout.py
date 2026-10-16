#!/usr/bin/env python3
"""Freeze or verify the prospective retail ACP mock-checkout agent study."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from agent_economic_trust.acp_free_checkout_study import (  # noqa: E402
    SEED_HEX, freeze_manifest, prospective_manifest, verify_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Check sources and schedule; no model calls")
    mode.add_argument("--freeze", type=Path, metavar="NEW_OUTPUT_DIR")
    mode.add_argument("--verify", type=Path, metavar="ASSIGNMENT_JSON")
    parser.add_argument("--seed-hex", default=SEED_HEX,
                        help="Use a prospectively selected 32-byte lowercase hex seed")
    args = parser.parse_args()
    try:
        if args.dry_run:
            manifest = prospective_manifest(args.seed_hex)
            result = {"status": "SOURCE_READY_NO_CALLS", "planned_rows": manifest["planned_rows"],
                      "rows_per_cell": manifest["rows_per_cell"], "model_calls": 0,
                      "new_checkout_calls": 0, "new_psp_captures": 0,
                      "new_native_transactions": 0}
        elif args.freeze is not None:
            path = freeze_manifest(args.freeze, args.seed_hex)
            result = {"assignment_path": str(path), **verify_manifest(path)}
        else:
            result = verify_manifest(args.verify)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except Exception as exc:
        print("ACP source preparation failed: " + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
