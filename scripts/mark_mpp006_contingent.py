#!/usr/bin/env python3
"""Guarded, one-time MPP006 contingent hold transition.

Default invocation is read-only. --apply appends one contingent ledger event
while retaining the original USD 6.307840 reservation. It never settles a
charge or changes the sealed research episode.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agent_economic_trust.remote_budget import BudgetLedger, read_ledger  # noqa: E402
from verify_mpp006_conditional_zero import verify as verify_offline_evidence  # noqa: E402

CANONICAL_LEDGER = ROOT / "artifacts/budget/openrouter-ledger.jsonl"
EVIDENCE = ROOT / "artifacts/budget/provider-reconciliation-mpp006-001/conditional-zero-asof-001/evidence.json"
RUN_ID = "mpp006-0e11d0595056-mpp006-bc092a2baae1584874c4f308"
EVIDENCE_SHA256 = "1b06d264b6a60bdfcff4e4a6de5bfe26c0fdf6e3d5aa61483b45cf4d5ddc8fc3"
LEDGER_SHA256 = "e5067415a2abfd589cfa9c3073e8dedcc0cbc25ce2af4635978fea7c3486b440"
ANCHOR_SHA256 = "c77675a2510594e4c9eac42becd5abc6c01e135cfad2f313e39969f0aa1067b7"
STOPPED_SHA256 = "afe3648e287db7cc3f05a87417ea6852969ae222dd043b26493854b983746745"
COLLECTION_SHA256 = "e6a323ac4c49382c96860693e43c954a6ddd251d4421db75496eeca561670f52"
EXPECTED_RESERVE = "6.30784"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _anchor(path: Path) -> Path:
    return path.with_name(path.name + ".anchor")


def validate_prestate(ledger_path: Path) -> dict:
    """Read all archived inputs and require the original canonical UNKNOWN state."""
    regenerated = verify_offline_evidence()
    saved = EVIDENCE.read_bytes()
    if _sha(EVIDENCE) != EVIDENCE_SHA256:
        raise ValueError("saved conditional evidence SHA-256 differs")
    if saved != (json.dumps(regenerated, sort_keys=True, indent=2) + "\n").encode():
        raise ValueError("saved conditional evidence no longer reproduces")
    if (regenerated["result"] != "CONDITIONAL_ZERO_MODEL_INFERENCE_AS_OF_OBSERVATION_NOT_INVOICED"
            or regenerated["actual_final_total_failed_request_usd"] is not None
            or regenerated["contingent_budget_exposure_usd"] != EXPECTED_RESERVE):
        raise ValueError("conditional evidence has changed meaning")

    stopped = ROOT / "artifacts/gates/MPP006/runs-mixed-001/episodes/mpp006-bc092a2baae1584874c4f308/STOPPED.json"
    collection = ROOT / "artifacts/gates/MPP006/collection-mixed-001-after-first-stop.json"
    if _sha(stopped) != STOPPED_SHA256 or _sha(collection) != COLLECTION_SHA256:
        raise ValueError("frozen STOPPED or collection bytes differ")
    if _sha(ledger_path) != LEDGER_SHA256 or _sha(_anchor(ledger_path)) != ANCHOR_SHA256:
        raise ValueError("ledger is not the original UNKNOWN prestate")
    before = read_ledger(ledger_path)
    run = before["runs"][RUN_ID]
    if (before["seq"] != 132 or before["cap_usd"] != "50"
            or before["settled_spent_usd"] != "5.31322"
            or before["reserved_usd"] != EXPECTED_RESERVE
            or before["unknown_run_ids"] != [RUN_ID]
            or before["blocked"] is not True
            or run["status"] != "UNKNOWN"
            or run["reserved_usd"] != EXPECTED_RESERVE):
        raise ValueError("ledger accounting prestate differs")
    return before


def run(*, ledger_path: Path = CANONICAL_LEDGER, apply: bool = False) -> dict:
    """Validate first, then optionally make the one allowed contingent event."""
    ledger_path = Path(ledger_path)
    before = validate_prestate(ledger_path)
    result = {
        "run_id": RUN_ID,
        "evidence_ref": "sha256:" + EVIDENCE_SHA256,
        "prior_ledger_seq": before["seq"],
        "retained_reservation_usd": EXPECTED_RESERVE,
        "actual_final_total_usd": None,
        "applied": False,
    }
    if not apply:
        return result
    # BudgetLedger rechecks UNKNOWN under its own write lock. The source
    # preflight above pins the original bytes; an intervening settlement fails.
    after = BudgetLedger(ledger_path).mark_contingent(RUN_ID, result["evidence_ref"])
    run_after = after["runs"][RUN_ID]
    if (after["seq"] != before["seq"] + 1
            or after["reserved_usd"] != EXPECTED_RESERVE
            or after["settled_spent_usd"] != before["settled_spent_usd"]
            or after["unknown_run_ids"]
            or after["contingent_run_ids"] != [RUN_ID]
            or after["blocked"] is not False
            or run_after["status"] != "CONTINGENT"
            or run_after["reserved_usd"] != EXPECTED_RESERVE
            or run_after["contingent_evidence_ref"] != result["evidence_ref"]):
        raise ValueError("contingent ledger mutation did not retain the hold")
    result.update({"applied": True, "new_ledger_seq": after["seq"],
                   "status": run_after["status"], "blocked": after["blocked"]})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="append the one contingent event; default is read-only")
    args = parser.parse_args()
    print(json.dumps(run(apply=args.apply), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
