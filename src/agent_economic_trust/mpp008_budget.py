"""Prospective MPP008 headroom with a retained MPP006 contingent reservation.

The conditional zero-model-charge evidence is not a final provider invoice.
MPP006 stays reserved in the canonical ledger while MPP008 uses the remaining
available amount, so this helper never adds the old reserve a second time.
"""
from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from .mpp008_plan import CANONICAL_LEDGER_PATH, CONTINGENCY_USD


MPP006_STOPPED_RUN_ID = "mpp006-0e11d0595056-mpp006-bc092a2baae1584874c4f308"
MPP006_ORIGINAL_RESERVATION_USD = Decimal("6.307840")
UNATTRIBUTED_KEY_EXPORT_RESIDUAL_USD = Decimal("0.0000342")
CONDITIONAL_EVIDENCE_SHA256 = "1b06d264b6a60bdfcff4e4a6de5bfe26c0fdf6e3d5aa61483b45cf4d5ddc8fc3"
CONDITIONAL_EVIDENCE_REF = "sha256:" + CONDITIONAL_EVIDENCE_SHA256
CONDITIONAL_EVIDENCE_DIR = (CANONICAL_LEDGER_PATH.parent /
    "provider-reconciliation-mpp006-001/conditional-zero-asof-001")
CONDITIONAL_EVIDENCE_PATH = CONDITIONAL_EVIDENCE_DIR / "evidence.json"
COLLECTION_SHA256 = "e6a323ac4c49382c96860693e43c954a6ddd251d4421db75496eeca561670f52"
COLLECTION_PATH = (CANONICAL_LEDGER_PATH.parent.parent /
    "gates/MPP006/collection-mixed-001-after-first-stop.json")
STOPPED_PATH = (CANONICAL_LEDGER_PATH.parent.parent /
    "gates/MPP006/runs-mixed-001/episodes/mpp006-bc092a2baae1584874c4f308/STOPPED.json")


def _file_sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("MPP006 conditional evidence file missing or symlinked")
    return sha256(path.read_bytes()).hexdigest()


def _conditional_sidecar() -> dict:
    """Bind the exact reviewed conditional evidence and its saved sources."""
    if _file_sha(CONDITIONAL_EVIDENCE_PATH) != CONDITIONAL_EVIDENCE_SHA256:
        raise ValueError("MPP006 conditional evidence bytes differ")
    try:
        record = json.loads(CONDITIONAL_EVIDENCE_PATH.read_bytes())
        _file_sha(STOPPED_PATH)
        stopped = json.loads(STOPPED_PATH.read_bytes())
    except (OSError, ValueError) as exc:
        raise ValueError("MPP006 conditional evidence or stopped record invalid") from exc
    if (record.get("schema") != "mpp006-conditional-zero-asof-export-v1"
            or record.get("result") != "CONDITIONAL_ZERO_MODEL_INFERENCE_AS_OF_OBSERVATION_NOT_INVOICED"
            or record.get("stopped_sample_uuid") != "aqKLUoK75wehRUqhXaE288"
            or record.get("stopped_http_status") != 400
            or record.get("stopped_provider_error_code") != "invalid_function_parameters"
            or record.get("stopped_sample_has_model_response") is not False
            or record.get("stopped_sample_has_model_usage") is not False
            or record.get("stopped_session_in_provider_export") is not False
            or record.get("serialized_request_has_auxiliary_web_or_file_service") is not False
            or record.get("conditional_model_inference_charge_usd") != "0"
            or record.get("actual_final_total_failed_request_usd", "MISSING") is not None
            or record.get("unattributed_key_above_csv_usd") != str(UNATTRIBUTED_KEY_EXPORT_RESIDUAL_USD)
            or record.get("contingent_budget_exposure_usd") != "6.30784"
            or record.get("settlement_requires_independent_review") is not True
            or record.get("per_request_invoice_available") is not False
            or record.get("frozen_collection_sha256") != COLLECTION_SHA256
            or record.get("frozen_collection_status_counts") !=
                {"COMPLETE": 1, "STOPPED": 1, "PENDING": 6}
            or record.get("ledger_prestate", {}).get("unknown_run_ids") != [MPP006_STOPPED_RUN_ID]
            or record.get("ledger_prestate", {}).get("reserved_usd") != "6.30784"
            or record.get("ledger_prestate", {}).get("seq") != 132
            or record.get("ledger_prestate", {}).get("blocked") is not True
            or record.get("ledger_prestate", {}).get("cap_usd") != "50"
            or stopped.get("ledger_run_id") != MPP006_STOPPED_RUN_ID
            or stopped.get("budget_state") != "UNKNOWN"
            or stopped.get("model_calls_attempted") != 1
            or stopped.get("complete_payment_claim") is not False
            or stopped.get("error_type") != "RemoteBoundaryError"):
        raise ValueError("MPP006 conditional evidence facts differ")
    if _file_sha(COLLECTION_PATH) != COLLECTION_SHA256:
        raise ValueError("MPP006 frozen collection differs")
    for key, filename in (("model_count", "request_count_by_model_hour.csv"),
                          ("model_usage", "usage_by_model_hour.csv"),
                          ("session", "usage_by_session_hourly.csv")):
        if _file_sha(CONDITIONAL_EVIDENCE_DIR.parent / filename) != record["owner_csv_sha256"][key]:
            raise ValueError("MPP006 owner CSV evidence differs")
    return record


def mpp006_contingent_exposure(snapshot: Mapping[str, Any], *,
                              additional_reservation_usd: Decimal = Decimal(0)) -> dict[str, str]:
    """Require the exact prior run to retain its reservation as CONTINGENT."""
    _conditional_sidecar()
    runs = snapshot.get("runs")
    run = runs.get(MPP006_STOPPED_RUN_ID) if isinstance(runs, Mapping) else None
    if not isinstance(run, Mapping) or run.get("status") != "CONTINGENT":
        raise ValueError("MPP006 stopped run must be CONTINGENT")
    expected_reserved = format((MPP006_ORIGINAL_RESERVATION_USD +
                                additional_reservation_usd).normalize(), "f")
    if (run.get("reserved_usd") != "6.30784" or "actual_usd" in run
            or run.get("evidence_ref") != CONDITIONAL_EVIDENCE_REF
            or run.get("contingent_evidence_ref") != CONDITIONAL_EVIDENCE_REF
            or snapshot.get("contingent_run_ids") != [MPP006_STOPPED_RUN_ID]
            or snapshot.get("reserved_usd") != expected_reserved):
        raise ValueError("MPP006 stopped run must retain its exact contingent reservation and evidence")
    return {"prior_run_id": MPP006_STOPPED_RUN_ID,
            "prior_reservation_usd": str(MPP006_ORIGINAL_RESERVATION_USD),
            "status": "CONTINGENT", "evidence_ref": CONDITIONAL_EVIDENCE_REF,
            "conditional_evidence_sha256": CONDITIONAL_EVIDENCE_SHA256,
            "unattributed_key_export_residual_usd": str(UNATTRIBUTED_KEY_EXPORT_RESIDUAL_USD),
            "final_invoice_charge_usd": "UNKNOWN"}


def required_headroom(reserves: Mapping[str, Decimal] | list[Decimal]) -> Decimal:
    """MPP006 hold is already deducted; keep the unassigned residual outside it."""
    values = reserves.values() if isinstance(reserves, Mapping) else reserves
    return sum(values, Decimal(0)) + Decimal(CONTINGENCY_USD) + UNATTRIBUTED_KEY_EXPORT_RESIDUAL_USD
