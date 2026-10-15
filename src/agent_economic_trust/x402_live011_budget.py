"""Exact prior billing holds required before prospective x402 model spending."""

from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from .mpp005_plan import canonical_project_root
from .mpp008_budget import MPP006_STOPPED_RUN_ID, mpp006_contingent_exposure


FEE_ORIGINAL_RUN_ID = "fee011-c36239cdcfd4-fee010-b0125916b5cd2e63f69109b5"
FEE_HOLD_RUN_ID = FEE_ORIGINAL_RUN_ID + "-failed-request-hold"
FEE_HOLD_USD = Decimal("3.379164")
FEE_HOLD_EVIDENCE_SHA256 = "87f7817ae03d0fbfb7f0fd2063fc7401012180cbd204959337da084f3499e50b"
FEE_HOLD_EVIDENCE_PATH = (canonical_project_root() /
    "artifacts/budget/fee011-failed-request-hold-001/evidence.json")
FEE_HOLD_METADATA = {
    "study": "ERC8183_FEE011",
    "reason": "HTTP400_FINAL_PROVIDER_CHARGE_UNATTRIBUTED",
    "evidence_sha256": FEE_HOLD_EVIDENCE_SHA256,
}


def _sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("FEE011 failed-request hold evidence file missing/symlinked")
    return sha256(path.read_bytes()).hexdigest()


def fee011_failed_request_hold(snapshot: Mapping[str, Any], *,
                               additional_reservation_usd: Decimal = Decimal(0),
                               active_x402_run_id: str | None = None) -> dict:
    """Bind the new append-only buffer without editing FEE011's settled run.

    The account has no attributable per-call charge for the HTTP 400. Keep the
    full unused first-row reserve as a separate RESERVED run until billing is
    reconciled; neither the estimated settlement nor this buffer is an invoice.
    """
    if (not isinstance(additional_reservation_usd, Decimal)
            or not additional_reservation_usd.is_finite()
            or additional_reservation_usd < 0):
        raise ValueError("x402 additional reservation is invalid")
    if _sha(FEE_HOLD_EVIDENCE_PATH) != FEE_HOLD_EVIDENCE_SHA256:
        raise ValueError("FEE011 failed-request hold sidecar bytes differ")
    evidence = json.loads(FEE_HOLD_EVIDENCE_PATH.read_bytes())
    if (evidence.get("schema") != "fee011-failed-request-billing-buffer-v1"
            or evidence.get("buffer_run_id") != FEE_HOLD_RUN_ID
            or evidence.get("original_ledger_run_id") != FEE_ORIGINAL_RUN_ID
            or evidence.get("additional_reserved_buffer_usd") != str(FEE_HOLD_USD)
            or evidence.get("settled_usage_estimate_usd") != "0.061476"
            or evidence.get("combined_maximum_exposure_usd") != "3.44064"
            or evidence.get("failed_model_events") != 1
            or evidence.get("successful_model_events") != 7
            or evidence.get("sample_model_events") != 8
            or evidence.get("final_failed_request_charge_usd", "MISSING") is not None
            or evidence.get("per_call_billing_available") is not False
            or evidence.get("reason") != FEE_HOLD_METADATA["reason"]):
        raise ValueError("FEE011 failed-request buffer facts differ")
    root = canonical_project_root()
    paths = evidence.get("evidence_paths")
    hashes = evidence.get("evidence_sha256")
    if not isinstance(paths, dict) or not isinstance(hashes, dict) or set(paths) != set(hashes):
        raise ValueError("FEE011 failed-request source inventory differs")
    for key, relative in paths.items():
        if (not isinstance(relative, str) or Path(relative).is_absolute()
                or not (root / relative).resolve().is_relative_to(root.resolve())
                or _sha(root / relative) != hashes[key]):
            raise ValueError("FEE011 failed-request source bytes differ")
    runs = snapshot.get("runs")
    original = runs.get(FEE_ORIGINAL_RUN_ID) if isinstance(runs, Mapping) else None
    hold = runs.get(FEE_HOLD_RUN_ID) if isinstance(runs, Mapping) else None
    if (not isinstance(original, Mapping) or original.get("status") != "SETTLED"
            or original.get("actual_usd") != "0.061476"
            or not isinstance(hold, Mapping) or hold.get("status") != "RESERVED"
            or hold.get("reserved_usd") != str(FEE_HOLD_USD)
            or hold.get("metadata") != FEE_HOLD_METADATA
            or "actual_usd" in hold or "evidence_ref" in hold):
        raise ValueError("FEE011 failed-request ledger buffer differs")
    open_ids = {ident for ident, item in runs.items()
                if item.get("status") in {"RESERVED", "CONTINGENT", "UNKNOWN"}}
    expected_open = {MPP006_STOPPED_RUN_ID, FEE_HOLD_RUN_ID}
    if additional_reservation_usd:
        if (not isinstance(active_x402_run_id, str)
                or not active_x402_run_id.startswith("x402011-")):
            raise ValueError("active x402 reservation ID missing")
        current = runs.get(active_x402_run_id)
        if (not isinstance(current, Mapping) or current.get("status") != "RESERVED"
                or Decimal(current.get("reserved_usd", "-1")) !=
                   additional_reservation_usd):
            raise ValueError("active x402 reservation differs")
        expected_open.add(active_x402_run_id)
    elif active_x402_run_id is not None:
        raise ValueError("x402 reservation ID without amount")
    if open_ids != expected_open:
        raise ValueError("prior billing open run IDs differ")
    expected = Decimal("6.30784") + FEE_HOLD_USD + additional_reservation_usd
    if Decimal(snapshot.get("reserved_usd", "-1")) != expected:
        raise ValueError("x402 prior billing reserves include a different run")
    mpp006_contingent_exposure(snapshot, additional_reservation_usd=(
        FEE_HOLD_USD + additional_reservation_usd))
    return {"run_id": FEE_HOLD_RUN_ID, "status": "RESERVED",
            "reserved_usd": str(FEE_HOLD_USD),
            "evidence_sha256": FEE_HOLD_EVIDENCE_SHA256,
            "failed_call_billing": "UNATTRIBUTED"}
