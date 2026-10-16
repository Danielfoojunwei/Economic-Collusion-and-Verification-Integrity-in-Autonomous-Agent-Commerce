"""Exact shared-ledger hold gate for the prospective FEE012 block."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from .mpp008_budget import MPP006_STOPPED_RUN_ID
from .x402_live011_budget import FEE_HOLD_RUN_ID
from .x402_live012_budget import (BASE_HOLDS_USD, X402011_RUN_ID,
                                  prior_billing_holds)


EXACT_OPEN_IDS = {MPP006_STOPPED_RUN_ID, FEE_HOLD_RUN_ID, X402011_RUN_ID}


def exact_prior_holds(snapshot: Mapping[str, Any], *,
                      active_run_id: str | None = None,
                      active_reservation_usd: Decimal = Decimal(0)) -> dict:
    """Retain all three unresolved old charges; admit at most one FEE012 hold.

    Removing a *verified* active reservation from a local projection lets the
    existing predecessor verifier replay the exact saved sidecars unchanged.
    """
    if (not isinstance(active_reservation_usd, Decimal)
            or not active_reservation_usd.is_finite()
            or active_reservation_usd < 0):
        raise ValueError("FEE012 active reservation differs")
    runs = snapshot.get("runs")
    if not isinstance(runs, Mapping):
        raise ValueError("FEE012 shared ledger runs missing")
    open_ids = {ident for ident, row in runs.items()
                if row.get("status") in {"RESERVED", "CONTINGENT", "UNKNOWN"}}
    if active_reservation_usd:
        if (not isinstance(active_run_id, str)
                or not active_run_id.startswith("fee012-")
                or active_run_id in EXACT_OPEN_IDS
                or runs.get(active_run_id, {}).get("status") != "RESERVED"
                or Decimal(runs[active_run_id].get("reserved_usd", "-1"))
                   != active_reservation_usd):
            raise ValueError("FEE012 active reserved run differs")
        expected = EXACT_OPEN_IDS | {active_run_id}
    elif active_run_id is not None:
        raise ValueError("FEE012 active run without reserve")
    else:
        expected = EXACT_OPEN_IDS
    if (open_ids != expected or snapshot.get("blocked")
            or snapshot.get("unknown_run_ids")
            or set(snapshot.get("contingent_run_ids", []))
               != {MPP006_STOPPED_RUN_ID, X402011_RUN_ID}
            or Decimal(snapshot.get("reserved_usd", "-1"))
               != BASE_HOLDS_USD + active_reservation_usd):
        raise ValueError("FEE012 open ledger hold set differs from three predecessors")
    projection = dict(snapshot)
    if active_run_id is not None:
        projection["runs"] = {key: value for key, value in runs.items()
                              if key != active_run_id}
        projection["reserved_usd"] = str(BASE_HOLDS_USD)
    old = prior_billing_holds(projection)
    if old["mpp011_contingent_run_ids"]:
        raise ValueError("MPP011 contingent exposure remains before FEE012")
    return {"exact_open_run_ids": sorted(EXACT_OPEN_IDS),
            "prior_reserved_usd": str(BASE_HOLDS_USD),
            "active_reservation_usd": str(active_reservation_usd)}
