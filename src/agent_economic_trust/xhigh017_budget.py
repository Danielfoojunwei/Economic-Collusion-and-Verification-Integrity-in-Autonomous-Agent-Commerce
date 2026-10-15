"""Exact shared-ledger hold gate for the prospective XHIGH017 block."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .mpp008_budget import MPP006_STOPPED_RUN_ID
from .x402_live011_budget import FEE_HOLD_RUN_ID
from .x402_live012_budget import (BASE_HOLDS_USD, X402011_RUN_ID,
                                  prior_billing_holds)


FEE014_STOP_RUN_ID = (
    "fee014-d6409ff93bcb-fee014-deb758472e05bb8622e9a1d6")
FEE014_HOLD_USD = Decimal("4.292608")
EXACT_OPEN_IDS = {MPP006_STOPPED_RUN_ID, FEE_HOLD_RUN_ID,
                  X402011_RUN_ID, FEE014_STOP_RUN_ID}


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
    """Retain old charges and full FEE014 failed-call hold.

    Removing a *verified* active reservation from a local projection lets the
    existing predecessor verifier replay the exact saved sidecars unchanged.
    """
    if (not isinstance(active_reservation_usd, Decimal)
            or not active_reservation_usd.is_finite()
            or active_reservation_usd < 0):
        raise ValueError("XHIGH017 active reservation differs")
    runs = snapshot.get("runs")
    if not isinstance(runs, Mapping):
        raise ValueError("XHIGH017 shared ledger runs missing")
    open_ids = {ident for ident, row in runs.items()
                if row.get("status") in {"RESERVED", "CONTINGENT", "UNKNOWN"}}
    if active_reservation_usd:
        if (not isinstance(active_run_id, str)
                or not active_run_id.startswith("xhigh017-")
                or active_run_id in EXACT_OPEN_IDS
                or runs.get(active_run_id, {}).get("status") != "RESERVED"
                or Decimal(runs[active_run_id].get("reserved_usd", "-1"))
                   != active_reservation_usd):
            raise ValueError("XHIGH017 active reserved run differs")
        expected = EXACT_OPEN_IDS | {active_run_id}
    elif active_run_id is not None:
        raise ValueError("XHIGH017 active run without reserve")
    else:
        expected = EXACT_OPEN_IDS
    fee014 = runs.get(FEE014_STOP_RUN_ID, {})
    if (open_ids != expected or snapshot.get("blocked")
            or snapshot.get("unknown_run_ids")
            or set(snapshot.get("contingent_run_ids", []))
               != {MPP006_STOPPED_RUN_ID, X402011_RUN_ID,
                   FEE014_STOP_RUN_ID}
            or fee014.get("status") != "CONTINGENT"
            or Decimal(fee014.get("reserved_usd", "-1")) != FEE014_HOLD_USD
            or Decimal(snapshot.get("reserved_usd", "-1"))
               != BASE_HOLDS_USD + FEE014_HOLD_USD + active_reservation_usd):
        raise ValueError("XHIGH017 open ledger hold set differs from four predecessors")
    projection = dict(snapshot)
    projection["runs"] = {key: value for key, value in runs.items()
                          if key not in {active_run_id, FEE014_STOP_RUN_ID}}
    projection["reserved_usd"] = str(BASE_HOLDS_USD)
    projection["contingent_run_ids"] = [ident for ident in
        snapshot.get("contingent_run_ids", []) if ident != FEE014_STOP_RUN_ID]
    old = prior_billing_holds(projection)
    if old["mpp011_contingent_run_ids"]:
        raise ValueError("MPP011 contingent exposure remains before XHIGH017")
    return {"exact_open_run_ids": sorted(EXACT_OPEN_IDS),
            "prior_reserved_usd": str(BASE_HOLDS_USD + FEE014_HOLD_USD),
            "active_reservation_usd": str(active_reservation_usd)}
