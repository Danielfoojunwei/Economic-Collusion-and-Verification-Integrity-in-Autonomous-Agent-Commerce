"""Exact shared-ledger hold gate for the prospective XHIGH018 block."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .mpp008_budget import MPP006_STOPPED_RUN_ID
from .x402_live011_budget import FEE_HOLD_RUN_ID
from .x402_live012_budget import BASE_HOLDS_USD, X402011_RUN_ID
from .xhigh017_budget import exact_prior_holds as xhigh017_prior_holds


FEE014_STOP_RUN_ID = (
    "fee014-d6409ff93bcb-fee014-deb758472e05bb8622e9a1d6")
FEE014_HOLD_USD = Decimal("4.292608")
EXACT_OPEN_IDS = {MPP006_STOPPED_RUN_ID, FEE_HOLD_RUN_ID,
                  X402011_RUN_ID, FEE014_STOP_RUN_ID}
XHIGH017_STOP_RUN_ID = (
    "xhigh017-a0f79e6ba7de-xhigh017-0a63961c0d306890326609f6")
XHIGH017_HOLD_USD = Decimal("4.718592")
XHIGH017_EVIDENCE_SHA = "53bdf0afe52a99f0ee18ab48772fac41b1a7054cb3b8f34386d392205c9ca009"
EXACT_OPEN_IDS.add(XHIGH017_STOP_RUN_ID)
PRESSURE016_STOP_RUN_ID = (
    "pressure016-dd13f314a88b-pressure016-8e43a1a6f0a28333250ec0e5")
PRESSURE016_HOLD_USD = Decimal("3.981312")
PRESSURE016_EVIDENCE_SHA = "704486b9214558eebafb18d86027666bcab898e897cf1e061cf8af0f6584b9f0"
EXACT_OPEN_IDS.add(PRESSURE016_STOP_RUN_ID)


def same_usd_amount(ledger_amount: object, saved_amount: object) -> bool:
    """Compare monetary value, not incidental Decimal string scale.

    The ledger may serialize 0.05069 while a saved model record serializes
    0.050690. Reject non-strings, non-finite values and negative amounts before
    comparing, so this normalization cannot erase a real billing difference.
    """
    if type(ledger_amount) is not str or type(saved_amount) is not str:
        return False
    try:
        left, right = Decimal(ledger_amount), Decimal(saved_amount)
    except InvalidOperation:
        return False
    return (left.is_finite() and right.is_finite()
            and left >= 0 and right >= 0 and left == right)


def exact_prior_holds(snapshot: Mapping[str, Any], *,
                      active_run_id: str | None = None,
                      active_reservation_usd: Decimal = Decimal(0)) -> dict:
    """Retain all six predecessor holds, including both stopped runs in full.

    Removing a *verified* active reservation from a local projection lets the
    existing predecessor verifier replay the exact saved sidecars unchanged.
    """
    if (not isinstance(active_reservation_usd, Decimal)
            or not active_reservation_usd.is_finite()
            or active_reservation_usd < 0):
        raise ValueError("XHIGH018 active reservation differs")
    runs = snapshot.get("runs")
    if not isinstance(runs, Mapping):
        raise ValueError("XHIGH018 shared ledger runs missing")
    open_ids = {ident for ident, row in runs.items()
                if row.get("status") in {"RESERVED", "CONTINGENT", "UNKNOWN"}}
    if active_reservation_usd:
        if (not isinstance(active_run_id, str)
                or not active_run_id.startswith("xhigh018-")
                or active_run_id in EXACT_OPEN_IDS
                or runs.get(active_run_id, {}).get("status") != "RESERVED"
                or Decimal(runs[active_run_id].get("reserved_usd", "-1"))
                   != active_reservation_usd):
            raise ValueError("XHIGH018 active reserved run differs")
        expected = EXACT_OPEN_IDS | {active_run_id}
    elif active_run_id is not None:
        raise ValueError("XHIGH018 active run without reserve")
    else:
        expected = EXACT_OPEN_IDS
    fee014 = runs.get(FEE014_STOP_RUN_ID, {})
    xhigh017 = runs.get(XHIGH017_STOP_RUN_ID, {})
    pressure016 = runs.get(PRESSURE016_STOP_RUN_ID, {})
    if (not isinstance(PRESSURE016_EVIDENCE_SHA, str)
            or len(PRESSURE016_EVIDENCE_SHA) != 64
            or any(c not in "0123456789abcdef" for c in PRESSURE016_EVIDENCE_SHA)):
        raise ValueError("XHIGH018 PRESSURE016 full-hold evidence is not pinned")
    if (open_ids != expected or snapshot.get("blocked")
            or snapshot.get("unknown_run_ids")
            or set(snapshot.get("contingent_run_ids", []))
               != {MPP006_STOPPED_RUN_ID, X402011_RUN_ID,
                   FEE014_STOP_RUN_ID, XHIGH017_STOP_RUN_ID,
                   PRESSURE016_STOP_RUN_ID}
            or fee014.get("status") != "CONTINGENT"
            or Decimal(fee014.get("reserved_usd", "-1")) != FEE014_HOLD_USD
            or xhigh017.get("status") != "CONTINGENT"
            or Decimal(xhigh017.get("reserved_usd", "-1")) != XHIGH017_HOLD_USD
            or xhigh017.get("evidence_ref") != "sha256:" + XHIGH017_EVIDENCE_SHA
            or xhigh017.get("contingent_evidence_ref") != "sha256:" + XHIGH017_EVIDENCE_SHA
            or xhigh017.get("prior_unknown_reason") != "RemoteBoundaryError"
            or pressure016.get("status") != "CONTINGENT"
            or Decimal(pressure016.get("reserved_usd", "-1")) != PRESSURE016_HOLD_USD
            or pressure016.get("evidence_ref") != "sha256:" + PRESSURE016_EVIDENCE_SHA
            or pressure016.get("contingent_evidence_ref") != "sha256:" + PRESSURE016_EVIDENCE_SHA
            or pressure016.get("prior_unknown_reason") != "RemoteBoundaryError"
            or Decimal(snapshot.get("reserved_usd", "-1"))
               != BASE_HOLDS_USD + FEE014_HOLD_USD + XHIGH017_HOLD_USD
                  + PRESSURE016_HOLD_USD
                  + active_reservation_usd):
        raise ValueError("XHIGH018 open ledger hold set differs from six predecessors")
    projection = dict(snapshot)
    projection["runs"] = {key: value for key, value in runs.items()
                          if key not in {active_run_id, PRESSURE016_STOP_RUN_ID,
                                         XHIGH017_STOP_RUN_ID}}
    projection["reserved_usd"] = str(BASE_HOLDS_USD + FEE014_HOLD_USD)
    projection["contingent_run_ids"] = [ident for ident in
        snapshot.get("contingent_run_ids", [])
        if ident not in {PRESSURE016_STOP_RUN_ID, XHIGH017_STOP_RUN_ID}]
    old = xhigh017_prior_holds(projection)
    return {"exact_open_run_ids": sorted(EXACT_OPEN_IDS),
            "prior_reserved_usd": str(BASE_HOLDS_USD + FEE014_HOLD_USD
                                      + XHIGH017_HOLD_USD + PRESSURE016_HOLD_USD),
            "active_reservation_usd": str(active_reservation_usd)}
