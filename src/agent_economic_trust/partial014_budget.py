"""Exact shared-ledger hold gate for the prospective PARTIAL014 block."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .mpp008_budget import MPP006_STOPPED_RUN_ID
from .x402_live011_budget import FEE_HOLD_RUN_ID
from .x402_live012_budget import (BASE_HOLDS_USD, X402011_RUN_ID,
                                  prior_billing_holds)


EXACT_OPEN_IDS = {MPP006_STOPPED_RUN_ID, FEE_HOLD_RUN_ID, X402011_RUN_ID}
FEE014_STOPPED_RUN_ID = "fee014-d6409ff93bcb-fee014-deb758472e05bb8622e9a1d6"
FEE014_FULL_HOLD_USD = Decimal("4.292608")
FEE014_PROVISIONAL_EVIDENCE_SHA = "22ca35d7dabb6d8ab87ecb2410c2f2f84a1ce22cc48eb18a7f703aa60c08d155"
FEE014_PROVISIONAL_EVIDENCE_REF = "sha256:" + FEE014_PROVISIONAL_EVIDENCE_SHA
FEE014_METADATA = {
    "assignment_sha": "d6409ff93bcbd1332aba4ad90b19953c045e9a3136383ea6fa30fe76ece3bfed",
    "episode_id": "fee014-deb758472e05bb8622e9a1d6",
    "provider_model_id": "anthropic/claude-sonnet-5.5",
    "auditor_model_id": "openai/gpt-5.6-sol",
}


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
    """Retain all old holds and FEE014's exact reviewed full contingent hold.

    Removing a *verified* active reservation from a local projection lets the
    existing predecessor verifier replay the exact saved sidecars unchanged.
    """
    if (not isinstance(active_reservation_usd, Decimal)
            or not active_reservation_usd.is_finite()
            or active_reservation_usd < 0):
        raise ValueError("PARTIAL014 active reservation differs")
    runs = snapshot.get("runs")
    if not isinstance(runs, Mapping):
        raise ValueError("PARTIAL014 shared ledger runs missing")
    fee014 = runs.get(FEE014_STOPPED_RUN_ID)
    if (not isinstance(fee014, Mapping)
            or fee014.get("metadata") != FEE014_METADATA
            or fee014.get("reserved_usd") != str(FEE014_FULL_HOLD_USD)
            or fee014.get("status") != "CONTINGENT"):
        raise ValueError("FEE014 stopped charge lacks reviewed full-hold disposition")
    evidence = fee014.get("evidence_ref")
    if (evidence != FEE014_PROVISIONAL_EVIDENCE_REF
            or fee014.get("contingent_evidence_ref") != evidence
            or "actual_usd" in fee014):
        raise ValueError("FEE014 contingent hold evidence differs")
    open_ids = {ident for ident, row in runs.items()
                if row.get("status") in {"RESERVED", "CONTINGENT", "UNKNOWN"}}
    if active_reservation_usd:
        if (not isinstance(active_run_id, str)
                or not active_run_id.startswith("partial014-")
                or active_run_id in EXACT_OPEN_IDS
                or runs.get(active_run_id, {}).get("status") != "RESERVED"
                or Decimal(runs[active_run_id].get("reserved_usd", "-1"))
                   != active_reservation_usd):
            raise ValueError("PARTIAL014 active reserved run differs")
        expected = EXACT_OPEN_IDS | {active_run_id}
    elif active_run_id is not None:
        raise ValueError("PARTIAL014 active run without reserve")
    else:
        expected = set(EXACT_OPEN_IDS)
    expected.add(FEE014_STOPPED_RUN_ID)
    expected_contingent = {MPP006_STOPPED_RUN_ID, X402011_RUN_ID,
                           FEE014_STOPPED_RUN_ID}
    if (open_ids != expected or snapshot.get("blocked")
            or snapshot.get("unknown_run_ids")
            or set(snapshot.get("contingent_run_ids", []))
               != expected_contingent
            or Decimal(snapshot.get("reserved_usd", "-1"))
               != BASE_HOLDS_USD + FEE014_FULL_HOLD_USD + active_reservation_usd):
        raise ValueError("PARTIAL014 open ledger hold set differs from reviewed predecessors")
    projection = dict(snapshot)
    projection["runs"] = {key: value for key, value in runs.items()
                          if key not in {active_run_id, FEE014_STOPPED_RUN_ID}}
    projection["reserved_usd"] = str(BASE_HOLDS_USD)
    projection["contingent_run_ids"] = sorted({MPP006_STOPPED_RUN_ID, X402011_RUN_ID})
    old = prior_billing_holds(projection)
    if old["mpp011_contingent_run_ids"]:
        raise ValueError("MPP011 contingent exposure remains before PARTIAL014")
    return {"exact_open_run_ids": sorted(EXACT_OPEN_IDS),
            "prior_reserved_usd": str(BASE_HOLDS_USD),
            "fee014_stopped_run_id": FEE014_STOPPED_RUN_ID,
            "fee014_charge_status": fee014["status"],
            "fee014_full_reserved_usd": str(FEE014_FULL_HOLD_USD),
            "fee014_active_hold_usd": str(FEE014_FULL_HOLD_USD),
            "fee014_billing_evidence_ref": evidence,
            "active_reservation_usd": str(active_reservation_usd)}
