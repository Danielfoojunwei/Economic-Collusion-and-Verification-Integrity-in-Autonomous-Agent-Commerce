"""Prospective MPP008 headroom for the stopped MPP006 request.

The MPP006 ledger settlement records provider billing evidence. Even if that
settlement is zero, MPP008 keeps the original worst-case MPP006 reservation as
an external planning exposure; it is not a second ledger charge.
"""
from __future__ import annotations

from decimal import Decimal
import re
from typing import Any, Mapping

from .mpp008_plan import CONTINGENCY_USD


MPP006_STOPPED_RUN_ID = "mpp006-0e11d0595056-mpp006-bc092a2baae1584874c4f308"
MPP006_ORIGINAL_RESERVATION_USD = Decimal("6.307840")
_EVIDENCE_REF = re.compile(r"sha256:[0-9a-f]{64}\Z")


def mpp006_contingent_exposure(snapshot: Mapping[str, Any]) -> dict[str, str]:
    """Require a zero-charge settlement for the exact prior stopped run."""
    runs = snapshot.get("runs")
    run = runs.get(MPP006_STOPPED_RUN_ID) if isinstance(runs, Mapping) else None
    if not isinstance(run, Mapping) or run.get("status") != "SETTLED":
        raise ValueError("MPP006 stopped run must have a settled billing entry")
    if run.get("actual_usd") != "0" or run.get("reserved_usd") != "6.30784":
        raise ValueError("MPP006 stopped run must settle at USD 0 with its original USD 6.307840 reservation")
    evidence = run.get("evidence_ref")
    if not isinstance(evidence, str) or _EVIDENCE_REF.fullmatch(evidence) is None:
        raise ValueError("MPP006 stopped run settlement needs a sha256 billing evidence reference")
    return {"prior_run_id": MPP006_STOPPED_RUN_ID,
            "prior_reservation_usd": str(MPP006_ORIGINAL_RESERVATION_USD),
            "settled_actual_usd": "0", "settlement_evidence_ref": evidence}


def required_headroom(reserves: Mapping[str, Decimal] | list[Decimal]) -> Decimal:
    """Keep MPP006 exposure in addition to MPP008 rows and its $2 contingency."""
    values = reserves.values() if isinstance(reserves, Mapping) else reserves
    return sum(values, Decimal(0)) + Decimal(CONTINGENCY_USD) + MPP006_ORIGINAL_RESERVATION_USD
