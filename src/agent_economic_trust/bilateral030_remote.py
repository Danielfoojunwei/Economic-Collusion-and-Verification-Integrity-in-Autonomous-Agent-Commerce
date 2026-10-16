"""Fail-closed source preview for a future BILATERAL030 paid runner.

There is deliberately no Inspect evaluation, model acquisition, reservation,
native-controller construction, or retry path here. A paid implementation
requires a separately reviewed, frozen successor that attaches the pure
request boundary to both live model APIs and verifies raw model/native logs.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .bilateral030_plan import budget_preview, make_schedule
from .mpp005_boundary import RemoteBoundaryError


ROOT = Path(__file__).resolve().parents[2]
HISTORICAL_CATALOG_MANIFEST = ROOT / (
    "artifacts/gates/ERC8183_PRESSURE016/assignment-001/assignment_manifest.json")
HISTORICAL_CATALOG_SHA256 = (
    "dd13f314a88b6397425a4f254e68002279fac5ad15fe341314c5014e20b5d047")
MISSING_EXECUTION_GATES = (
    "ONE_TIME_PRIVATE_ASSIGNMENT_FREEZE_AND_SOURCE_INVENTORY",
    "LIVE_COMPACT_ORBIT_TASK_AND_BOTH_API_WRAPPERS",
    "ACTUAL_MODELCALL_BOTH_ROUTES_EFFORT_CAP_AND_ZERO_RETRIES",
    "ZERO_MODEL_EXACT_DELIVERY_AND_PRIVATE_TRUTH_CONTROL",
    "MATCHED_BAD_NOTICE_PAYOUT_OBJECTIVE_FUNDED_PROOF_AND_CONTACT_ONLY_MASK",
    "REVERSE_ROLE_NATIVE_ERC8183_BRIDGE_AND_INDEPENDENT_REPLAY",
    "PROVIDER_FUNDED_EARLY_APPROVE_BONUS_ESCROW_AND_INDEPENDENT_REPLAY",
    "RAW_INSPECT_MODEL_CALL_AND_NATIVE_RECEIPT_COLLECTOR",
    "FAILED_CALL_BILLING_HOLD_AND_NO_RETRY_FORENSICS",
    "FRESH_CATALOG_AND_FULL_BLOCK_BUDGET_REVIEW",
    "ATTRIBUTABLE_PRIOR_BILLING_RECONCILIATION",
)


def historical_catalog() -> dict[str, dict[str, Any]]:
    """Read the pinned old quote, never refresh a remote catalog in preflight."""
    path = HISTORICAL_CATALOG_MANIFEST
    if (path.is_symlink() or not path.is_file()
            or sha256(path.read_bytes()).hexdigest() != HISTORICAL_CATALOG_SHA256):
        raise RemoteBoundaryError("BILATERAL030 historical price source differs")
    value = json.loads(path.read_bytes())
    prices = value.get("public_pricing_snapshot")
    if not isinstance(prices, dict):
        raise RemoteBoundaryError("BILATERAL030 historical catalog absent")
    return prices


def preflight(seed_hex: str) -> dict[str, Any]:
    """Read-only current-ledger/status preview; never returns execution PASS."""
    rows = make_schedule(seed_hex)
    budget = budget_preview(historical_catalog(), rows)
    return {"status": "HOLD_SOURCE_ONLY",
            "permission_to_freeze_or_call": False,
            "planned_rows": len(rows),
            "source_quote": budget,
            "missing_execution_gates": list(MISSING_EXECUTION_GATES)}


def execute_one(seed_hex: str) -> None:
    """Hard-closed entrypoint until a separately reviewed native live runner exists."""
    state = preflight(seed_hex)
    raise RemoteBoundaryError(
        "BILATERAL030 paid execution unavailable: " +
        ", ".join(state["missing_execution_gates"]))
