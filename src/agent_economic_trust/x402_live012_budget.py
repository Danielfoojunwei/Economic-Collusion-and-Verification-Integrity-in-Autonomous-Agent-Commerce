"""Exact predecessor holds for an unfrozen x402 012 block.

MPP011 has sequencing priority. A later clearance must bind any MPP011
contingent run to its frozen collection; this module never releases a hold.
"""

from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from .mpp005_plan import canonical_project_root
from .mpp008_budget import MPP006_STOPPED_RUN_ID
from .x402_live011_budget import (FEE_HOLD_RUN_ID, FEE_HOLD_USD,
                                  FEE_ORIGINAL_RUN_ID, fee011_failed_request_hold)


X402011_RUN_ID = "x402011-ea4c997ba6f3-x402011-19587c1ddccc97900b2deddd"
X402011_HOLD_USD = Decimal("4.407296")
X402011_EVIDENCE_SHA256 = "84dbe734ba49a992def4aeee3b77645a80ee8b9fd2d89a5b59a1dbbe4d7d9559"
X402011_EVIDENCE_PATH = (canonical_project_root() /
    "artifacts/budget/x402011-first-stop-contingent-001/evidence.json")
BASE_HOLDS_USD = Decimal("6.30784") + FEE_HOLD_USD + X402011_HOLD_USD


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("x402011 contingent evidence path is missing or symlinked")
    return sha256(path.read_bytes()).hexdigest()


def _x402011_evidence() -> dict:
    """Bind the provisional assessment and all six frozen sources."""
    if _sha(X402011_EVIDENCE_PATH) != X402011_EVIDENCE_SHA256:
        raise ValueError("x402011 contingent sidecar bytes differ")
    record = json.loads(X402011_EVIDENCE_PATH.read_bytes())
    if (record.get("schema") != "x402011-first-stop-contingent-billing-v1"
            or record.get("run_id") != X402011_RUN_ID
            or record.get("result") != "MODEL_CHARGE_UNATTRIBUTED_AS_OF_LOCAL_ACCOUNT_SNAPSHOT"
            or record.get("contingent_budget_exposure_usd") != str(X402011_HOLD_USD)
            or record.get("actual_final_provider_charge_usd", "MISSING") is not None
            or record.get("per_request_billing_available") is not False
            or record.get("model_events") != 6
            or record.get("saved_model_event_errors") != 0
            or record.get("stopped_native_receipt_claim") !=
               "GOOD_CHECKED_ACCEPT_AND_VALID_LOCAL_PAYOUT"
            or record.get("boundary_failure") !=
               "PROVIDER_CLAIM_IN_UNTRUSTED_ORBIT_CHANNEL_INBOX_MISCLASSIFIED_AS_PRIVATE_SYSTEM_TRUTH"
            or record.get("ledger_prestate", {}).get("seq") != 154):
        raise ValueError("x402011 contingent sidecar facts differ")
    root = canonical_project_root()
    paths, hashes = record.get("evidence_paths"), record.get("evidence_sha256")
    if (not isinstance(paths, dict) or not isinstance(hashes, dict)
            or len(paths) != 6 or set(paths) != set(hashes)):
        raise ValueError("x402011 contingent source inventory differs")
    for relative in paths.values():
        if (not isinstance(relative, str) or Path(relative).is_absolute()
                or not (root / relative).resolve().is_relative_to(root.resolve())):
            raise ValueError("x402011 contingent source path escapes repository")
    for name, relative in paths.items():
        if _sha(root / relative) != hashes[name]:
            raise ValueError("x402011 contingent source bytes differ")
    return record


def prior_billing_holds(snapshot: Mapping[str, Any], *,
                        active_x402012_run_id: str | None = None,
                        active_reservation_usd: Decimal = Decimal(0)) -> dict:
    """Retain all three old holds and only reviewed MPP011 contingent exposure.

    An MPP011 final collection/clearance is still required before freezing;
    prefix-only MPP011 acceptance here is never a standalone spend gate.
    """
    if (not isinstance(active_reservation_usd, Decimal)
            or not active_reservation_usd.is_finite()
            or active_reservation_usd < 0):
        raise ValueError("x402012 active reservation differs")
    runs = snapshot.get("runs")
    if not isinstance(runs, Mapping):
        raise ValueError("canonical ledger runs missing")
    prior = {name: runs.get(name) for name in
             (MPP006_STOPPED_RUN_ID, FEE_ORIGINAL_RUN_ID, FEE_HOLD_RUN_ID)}
    if any(not isinstance(value, Mapping) for value in prior.values()):
        raise ValueError("old billing run missing")
    projection = {"runs": prior, "reserved_usd": "9.687004",
                  "contingent_run_ids": [MPP006_STOPPED_RUN_ID]}
    fee011_failed_request_hold(projection)
    _x402011_evidence()
    old = runs.get(X402011_RUN_ID)
    if (not isinstance(old, Mapping) or old.get("status") != "CONTINGENT"
            or old.get("reserved_usd") != str(X402011_HOLD_USD)
            or old.get("evidence_ref") != "sha256:" + X402011_EVIDENCE_SHA256
            or old.get("contingent_evidence_ref") !=
               "sha256:" + X402011_EVIDENCE_SHA256
            or "actual_usd" in old):
        raise ValueError("x402011 full contingent run differs")
    if snapshot.get("unknown_run_ids") or snapshot.get("blocked"):
        raise ValueError("unknown canonical charge blocks x402012")
    mpp011 = {name: item for name, item in runs.items()
              if name.startswith("mpp011-") and item.get("status") in
              {"RESERVED", "CONTINGENT", "UNKNOWN"}}
    if len(mpp011) > 1 or any(item.get("status") != "CONTINGENT" for item in mpp011.values()):
        raise ValueError("MPP011 open run lacks one reviewed contingent disposition")
    for item in mpp011.values():
        amount = Decimal(item.get("reserved_usd", "-1"))
        if (not amount.is_finite() or amount <= 0
                or not str(item.get("evidence_ref", "")).startswith("sha256:")
                or item.get("evidence_ref") != item.get("contingent_evidence_ref")
                or "actual_usd" in item):
            raise ValueError("MPP011 contingent run evidence or amount differs")
    open_ids = {name for name, item in runs.items()
                if item.get("status") in {"RESERVED", "CONTINGENT", "UNKNOWN"}}
    expected = {MPP006_STOPPED_RUN_ID, FEE_HOLD_RUN_ID, X402011_RUN_ID, *mpp011}
    if active_reservation_usd:
        if (not isinstance(active_x402012_run_id, str)
                or not active_x402012_run_id.startswith("x402012-")):
            raise ValueError("active x402012 run ID missing")
        active = runs.get(active_x402012_run_id)
        if (not isinstance(active, Mapping) or active.get("status") != "RESERVED"
                or Decimal(active.get("reserved_usd", "-1")) !=
                   active_reservation_usd):
            raise ValueError("active x402012 reservation differs")
        expected.add(active_x402012_run_id)
    elif active_x402012_run_id is not None:
        raise ValueError("active x402012 run ID without reservation")
    if open_ids != expected:
        raise ValueError("unreviewed open ledger run differs")
    expected_contingent = sorted({MPP006_STOPPED_RUN_ID, X402011_RUN_ID, *mpp011})
    if snapshot.get("contingent_run_ids") != expected_contingent:
        raise ValueError("prior contingent run list differs")
    total = BASE_HOLDS_USD + sum(
        (Decimal(item["reserved_usd"]) for item in mpp011.values()),
        Decimal(0)) + active_reservation_usd
    if Decimal(snapshot.get("reserved_usd", "-1")) != total:
        raise ValueError("prior holds do not add to canonical reserve")
    return {"x402011_run_id": X402011_RUN_ID,
            "x402011_contingent_usd": str(X402011_HOLD_USD),
            "x402011_evidence_sha256": X402011_EVIDENCE_SHA256,
            "mpp011_contingent_run_ids": sorted(mpp011),
            "total_reserved_usd": str(total)}
