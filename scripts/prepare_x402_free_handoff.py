#!/usr/bin/env python3
"""Dry-run or freeze the x402 A-to-B source-only free-model study.

There is intentionally no --execute option. This script does not call a model,
charge x402, or start a local ERC-8183 chain.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agent_economic_trust.x402_free_handoff_study import (  # noqa: E402
    SEED_HEX, freeze_manifest, prospective_manifest, verify_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-hex", default=SEED_HEX)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Read and replay source evidence; no write")
    mode.add_argument("--freeze", type=Path, metavar="NEW_OUTPUT_DIR",
                      help="Write one source-only frozen assignment manifest")
    mode.add_argument("--verify", type=Path, metavar="ASSIGNMENT_MANIFEST",
                      help="Independently check saved source-only assignment")
    args = parser.parse_args()
    try:
        if args.verify is not None:
            result = verify_manifest(args.verify)
        elif args.freeze is not None:
            path = freeze_manifest(args.freeze, args.seed_hex)
            result = {"status": "SOURCE_FROZEN_NO_MODEL_CALL", "manifest": str(path),
                      "verification": verify_manifest(path)}
        else:
            manifest = prospective_manifest(args.seed_hex)
            result = {"status": manifest["status"], "planned_rows": manifest["planned_rows"],
                      "rows_per_arm": manifest["rows_per_arm"],
                      "model_ids_by_role": manifest["model_ids_by_role"],
                      "source_obligation_A": manifest["evidence_seal"]["source_obligation_id"],
                      "target_obligation_B": manifest["evidence_seal"]["target_obligation_id"],
                      "paid_receipt_digest": manifest["evidence_seal"]["report_digest"],
                      "hypothetical_ACCEPT_dispatch_by_policy": {
                          key: item["dispatched_verdict"] for key, item in
                          manifest["offline_accept_preview"]["policies"].items()},
                      "model_calls": 0, "new_native_payments": 0}
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except Exception as exc:
        # Error details from raw evidence should not enter terminal transcripts.
        print("x402 source preparation stopped: " + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
