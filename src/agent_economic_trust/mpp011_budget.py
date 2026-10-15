"""Prospective MPP011 headroom with three retained prior billing holds.

The canonical ledger already subtracts MPP006 and x402011 CONTINGENT runs
and the separate FEE011 RESERVED failed-request hold. Verify each exactly;
never subtract a prior reservation twice or treat an unknown charge as zero.
"""
from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from .mpp008_budget import (UNATTRIBUTED_KEY_EXPORT_RESIDUAL_USD,
    MPP006_STOPPED_RUN_ID, mpp006_contingent_exposure)
from .mpp011_plan import CONTINGENCY_USD
from .mpp011_plan import CANONICAL_LEDGER_PATH


FEE011_HOLD_RUN_ID = (
    "fee011-c36239cdcfd4-fee010-b0125916b5cd2e63f69109b5-failed-request-hold")
FEE011_HOLD_USD = Decimal("3.379164")
FEE011_HOLD_EVIDENCE = (CANONICAL_LEDGER_PATH.parent /
    "fee011-failed-request-hold-001/evidence.json")
FEE011_HOLD_SHA256 = "87f7817ae03d0fbfb7f0fd2063fc7401012180cbd204959337da084f3499e50b"
X402011_HOLD_RUN_ID = "x402011-ea4c997ba6f3-x402011-19587c1ddccc97900b2deddd"
X402011_HOLD_USD = Decimal("4.407296")
X402011_HOLD_EVIDENCE = (CANONICAL_LEDGER_PATH.parent /
    "x402011-first-stop-contingent-001/evidence.json")
X402011_HOLD_SHA256 = "84dbe734ba49a992def4aeee3b77645a80ee8b9fd2d89a5b59a1dbbe4d7d9559"
X402011_COLLECTION_SHA256 = "49e3d3bb707700a55f89156c0423bd28f9d474344dfab8be4b676c065b5c281b"


def x402_contingent_hold(snapshot: Mapping[str, Any]) -> dict[str, str]:
    """Bind the reviewed stopped x402 row without treating its charge as zero."""
    root = CANONICAL_LEDGER_PATH.parents[2]
    path = Path(X402011_HOLD_EVIDENCE)
    if (path.is_symlink() or not path.is_file()
            or sha256(path.read_bytes()).hexdigest() != X402011_HOLD_SHA256):
        raise ValueError("x402011 contingent forensic evidence differs")
    evidence = json.loads(path.read_bytes())
    if (evidence.get("schema") != "x402011-first-stop-contingent-billing-v1"
            or evidence.get("run_id") != X402011_HOLD_RUN_ID
            or evidence.get("contingent_budget_exposure_usd") != str(X402011_HOLD_USD)
            or evidence.get("actual_final_provider_charge_usd", "MISSING") is not None
            or evidence.get("settlement_requires_independent_review") is not True
            or evidence.get("evidence_sha256", {}).get("collection") != X402011_COLLECTION_SHA256):
        raise ValueError("x402011 contingent forensic facts differ")
    for key, relative in evidence["evidence_paths"].items():
        source = root / relative
        if (source.is_symlink() or not source.is_file()
                or not source.resolve().is_relative_to(root.resolve())
                or sha256(source.read_bytes()).hexdigest() != evidence["evidence_sha256"][key]):
            raise ValueError("x402011 contingent source evidence differs")
    run = snapshot.get("runs", {}).get(X402011_HOLD_RUN_ID)
    reference = "sha256:" + X402011_HOLD_SHA256
    if (not isinstance(run, Mapping) or run.get("status") != "CONTINGENT"
            or run.get("reserved_usd") != str(X402011_HOLD_USD)
            or "actual_usd" in run or run.get("evidence_ref") != reference
            or run.get("contingent_evidence_ref") != reference
            or run.get("prior_unknown_reason") != "RemoteBoundaryError"
            or run.get("metadata") != {
                "assignment_sha": evidence["evidence_sha256"]["assignment_manifest"],
                "auditor_model_id": "anthropic/claude-sonnet-5.5",
                "episode_id": "x402011-19587c1ddccc97900b2deddd",
                "provider_model_id": "openai/gpt-5.6-sol"}
            or snapshot.get("contingent_run_ids") != sorted(
                (MPP006_STOPPED_RUN_ID, X402011_HOLD_RUN_ID))):
        raise ValueError("x402011 full contingent reservation is missing or changed")
    return {"run_id": X402011_HOLD_RUN_ID, "reserved_usd": str(X402011_HOLD_USD),
            "status": "CONTINGENT", "evidence_ref": reference,
            "evidence_sha256": X402011_HOLD_SHA256,
            "collection_sha256": X402011_COLLECTION_SHA256,
            "final_provider_charge_usd": "UNKNOWN"}


def mpp006_with_x402(snapshot: Mapping[str, Any], *,
                     additional_reservation_usd: Decimal = Decimal(0)) -> dict[str, str]:
    """Apply the older single-contingent check after subtracting verified x402 once."""
    x402_contingent_hold(snapshot)
    normalized = dict(snapshot)
    normalized["contingent_run_ids"] = [MPP006_STOPPED_RUN_ID]
    normalized["reserved_usd"] = format(
        (Decimal(snapshot["reserved_usd"]) - X402011_HOLD_USD).normalize(), "f")
    return mpp006_contingent_exposure(normalized,
        additional_reservation_usd=additional_reservation_usd)


def fee011_hold(snapshot: Mapping[str, Any]) -> dict[str, str]:
    """Keep the separately reviewed failed-request hold reserved exactly once."""
    path = Path(FEE011_HOLD_EVIDENCE)
    if (path.is_symlink() or not path.is_file()
            or sha256(path.read_bytes()).hexdigest() != FEE011_HOLD_SHA256):
        raise ValueError("FEE011 failed-request hold forensic evidence differs")
    run = snapshot.get("runs", {}).get(FEE011_HOLD_RUN_ID)
    if (not isinstance(run, Mapping) or run.get("status") != "RESERVED"
            or Decimal(run.get("reserved_usd", "-1")) != FEE011_HOLD_USD
            or "actual_usd" in run
            or run.get("metadata") != {
                "study": "ERC8183_FEE011",
                "reason": "HTTP400_FINAL_PROVIDER_CHARGE_UNATTRIBUTED",
                "evidence_sha256": FEE011_HOLD_SHA256}):
        raise ValueError("FEE011 failed-request hold is missing or changed")
    return {"run_id": FEE011_HOLD_RUN_ID, "reserved_usd": str(FEE011_HOLD_USD),
            "evidence_sha256": FEE011_HOLD_SHA256}


def required_headroom(reserves: Mapping[str, Decimal]) -> Decimal:
    if len(reserves) != 5 or any(not isinstance(value, Decimal)
                                   or not value.is_finite() or value <= 0
                                   for value in reserves.values()):
        raise ValueError("MPP011 requires five positive assigned row reservations")
    return (sum(reserves.values(), Decimal(0)) + CONTINGENCY_USD
            + UNATTRIBUTED_KEY_EXPORT_RESIDUAL_USD)


def budget_preflight(snapshot: Mapping[str, Any], reserves: Mapping[str, Decimal]) -> dict[str, str]:
    """Fail closed while MPP006 is unknown/settled or another row is reserved."""
    held = fee011_hold(snapshot)
    x402 = x402_contingent_hold(snapshot)
    exposure = mpp006_with_x402(snapshot,
        additional_reservation_usd=FEE011_HOLD_USD)
    if (snapshot.get("cap_usd") != "50" or snapshot.get("blocked") is not False
            or snapshot.get("unknown_run_ids") != []):
        raise ValueError("canonical lifetime ledger blocks MPP011")
    full = required_headroom(reserves)
    available = Decimal(snapshot["available_usd"])
    if not available.is_finite() or full > available:
        raise ValueError("full MPP011 block plus ordinary contingency exceeds available USD50 budget")
    return {"required_headroom_usd": str(full),
            "full_block_reserve_usd": str(sum(reserves.values(), Decimal(0))),
            "available_usd": str(available),
            "prior_mpp006_status": exposure["status"],
            "prior_mpp006_reserved_once_usd": exposure["prior_reservation_usd"],
            "prior_fee011_hold_run_id": held["run_id"],
            "prior_fee011_reserved_once_usd": held["reserved_usd"],
            "prior_x402_hold_run_id": x402["run_id"],
            "prior_x402_reserved_once_usd": x402["reserved_usd"]}
