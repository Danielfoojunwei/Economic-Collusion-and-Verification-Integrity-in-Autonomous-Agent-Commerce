"""Prospective MPP010 headroom after the MPP006 charge remains CONTINGENT.

The canonical ledger already subtracts the original USD 6.307840 MPP006
reservation. Adding it again here would double count the unresolved bill.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from .mpp008_budget import (UNATTRIBUTED_KEY_EXPORT_RESIDUAL_USD,
    mpp006_contingent_exposure)
from .mpp010_plan import CONTINGENCY_USD


def required_headroom(reserves: Mapping[str, Decimal]) -> Decimal:
    if len(reserves) != 10 or any(not isinstance(value, Decimal)
                                   or not value.is_finite() or value <= 0
                                   for value in reserves.values()):
        raise ValueError("MPP010 requires ten positive assigned row reservations")
    return (sum(reserves.values(), Decimal(0)) + CONTINGENCY_USD
            + UNATTRIBUTED_KEY_EXPORT_RESIDUAL_USD)


def budget_preflight(snapshot: Mapping[str, Any], reserves: Mapping[str, Decimal]) -> dict[str, str]:
    """Fail closed while MPP006 is unknown/settled or another row is reserved."""
    exposure = mpp006_contingent_exposure(snapshot)
    if (snapshot.get("cap_usd") != "50" or snapshot.get("blocked") is not False
            or snapshot.get("unknown_run_ids") != []):
        raise ValueError("canonical lifetime ledger blocks MPP010")
    full = required_headroom(reserves)
    available = Decimal(snapshot["available_usd"])
    if not available.is_finite() or full > available:
        raise ValueError("full MPP010 block plus ordinary contingency exceeds available USD50 budget")
    return {"required_headroom_usd": str(full),
            "full_block_reserve_usd": str(sum(reserves.values(), Decimal(0))),
            "available_usd": str(available),
            "prior_mpp006_status": exposure["status"],
            "prior_mpp006_reserved_once_usd": exposure["prior_reservation_usd"]}
