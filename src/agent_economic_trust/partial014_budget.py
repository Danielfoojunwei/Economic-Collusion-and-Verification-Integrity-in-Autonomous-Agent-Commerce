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
FEE015_ASSIGNMENT_SHA = "18f457fc4df4311412824d29520b3a88cac29e6ea50e9b9c85c42ce0fc0575de"
FEE015_RESERVED_USD = "4.022272"
FEE015_SETTLED = (
    ("fee015-43a6638d8a029c8af0932207", "0.053706", "4c86d910f1dc4cb2772d4732d3304771e02fcd9f6a88186f00be261678fa08cc"),
    ("fee015-73b9d2e6f24699baebeef807", "0.069884", "1273c9ea90ffb77fb7d0c801c86a1345d294d41ca1aa87389a9d16fe7f739c18"),
    ("fee015-213cf289c354b0d811a7daca", "0.055702", "4080cb3b7f0b6e5209491f6dade8c5681d1115e42203c327d23f42304df74c33"),
    ("fee015-af89ad4c0bc3d4e48f6359bb", "0.076762", "174cd18d4612c47610a93c03acf47c686cc9316eceb05b04b08b98ea1921b904"),
    ("fee015-1077be9dc3cab942c3cb2e36", "0.053260", "18eadd6cb3da7a5a5ad5ada32c43fd12dfe0ad4d80e6495ab8812e66366e6f6b"),
)


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
    settled_ids = []
    for episode_id, actual, inspect_sha in FEE015_SETTLED:
        ident = "fee015-" + FEE015_ASSIGNMENT_SHA[:12] + "-" + episode_id
        row = runs.get(ident)
        if (not isinstance(row, Mapping) or row.get("status") != "SETTLED"
                or row.get("reserved_usd") != FEE015_RESERVED_USD
                or row.get("metadata") != {
                    "assignment_sha": FEE015_ASSIGNMENT_SHA,
                    "episode_id": episode_id,
                    "provider_model_id": "anthropic/claude-sonnet-5.5",
                    "auditor_model_id": "openai/gpt-5.6-sol"}
                or not same_usd_amount(row.get("actual_usd"), actual)
                or row.get("evidence_ref") != "sha256:" + inspect_sha):
            raise ValueError("FEE015 exact settled model run differs")
        settled_ids.append(ident)
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
                          if key not in {active_run_id, FEE014_STOPPED_RUN_ID,
                                         *settled_ids}}
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
            "fee015_settled_run_ids": settled_ids,
            "fee015_settled_usage_estimate_usd": str(sum(
                (Decimal(actual) for _, actual, _ in FEE015_SETTLED), Decimal(0))),
            "active_reservation_usd": str(active_reservation_usd)}
