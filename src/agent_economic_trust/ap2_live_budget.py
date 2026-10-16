"""AP2 LIVE checks for the stopped MPP006 contingent ledger hold.

The charge remains uncertain. Its original reservation stays inside the shared
ledger and must be counted exactly once in available project headroom.
"""

from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .ap2_live_plan import CONTINGENCY_USD


MPP006_STOPPED_RUN_ID = "mpp006-0e11d0595056-mpp006-bc092a2baae1584874c4f308"
MPP006_ORIGINAL_RESERVATION_USD = Decimal("6.307840")
UNASSIGNED_ACCOUNT_RESIDUAL_USD = Decimal("0.0000342")
MPP006_EVIDENCE_SHA256 = "1b06d264b6a60bdfcff4e4a6de5bfe26c0fdf6e3d5aa61483b45cf4d5ddc8fc3"
ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "artifacts/budget/provider-reconciliation-mpp006-001/conditional-zero-asof-001/evidence.json"
COLLECTION = ROOT / "artifacts/gates/MPP006/collection-mixed-001-after-first-stop.json"
COLLECTION_SHA256 = "e6a323ac4c49382c96860693e43c954a6ddd251d4421db75496eeca561670f52"
_EVIDENCE_REF = re.compile(r"sha256:[0-9a-f]{64}\Z")


def mpp006_contingent_exposure(snapshot: Mapping[str, Any]) -> dict[str, str]:
    """Require the exact prior run's retained hold and pinned billing sidecar."""
    if snapshot.get("contingent_run_ids") != [MPP006_STOPPED_RUN_ID]:
        raise ValueError("MPP006 must be the only contingent ledger run")
    runs = snapshot.get("runs")
    run = runs.get(MPP006_STOPPED_RUN_ID) if isinstance(runs, Mapping) else None
    if not isinstance(run, Mapping) or run.get("status") != "CONTINGENT":
        raise ValueError("MPP006 stopped run needs a contingent ledger hold")
    if run.get("reserved_usd") != "6.30784" or run.get("actual_usd") is not None:
        raise ValueError("MPP006 stopped run must retain its original unbilled reservation")
    evidence = run.get("evidence_ref")
    if (not isinstance(evidence, str) or _EVIDENCE_REF.fullmatch(evidence) is None
            or evidence != "sha256:" + MPP006_EVIDENCE_SHA256
            or run.get("contingent_evidence_ref") != evidence):
        raise ValueError("MPP006 contingent hold needs its exact sha256 billing evidence reference")
    if EVIDENCE.is_symlink() or not EVIDENCE.is_file() or COLLECTION.is_symlink() or not COLLECTION.is_file():
        raise ValueError("MPP006 billing evidence or frozen collection is missing")
    raw = EVIDENCE.read_bytes()
    if sha256(raw).hexdigest() != MPP006_EVIDENCE_SHA256:
        raise ValueError("MPP006 billing evidence bytes differ from contingent ledger reference")
    if sha256(COLLECTION.read_bytes()).hexdigest() != COLLECTION_SHA256:
        raise ValueError("MPP006 STOPPED collection bytes differ from archived denominator")
    record = json.loads(raw)
    prestate = record.get("ledger_prestate", {})
    if (record.get("schema") != "mpp006-conditional-zero-asof-export-v1"
            or record.get("result") != "CONDITIONAL_ZERO_MODEL_INFERENCE_AS_OF_OBSERVATION_NOT_INVOICED"
            or record.get("conditional_model_inference_charge_usd") != "0"
            or record.get("actual_final_total_failed_request_usd") is not None
            or record.get("contingent_budget_exposure_usd") != "6.30784"
            or record.get("unattributed_key_above_csv_usd") != "0.0000342"
            or record.get("stopped_sample_uuid") != "aqKLUoK75wehRUqhXaE288"
            or record.get("stopped_http_status") != 400
            or record.get("stopped_provider_error_code") != "invalid_function_parameters"
            or record.get("frozen_collection_sha256") != COLLECTION_SHA256
            or record.get("frozen_collection_status_counts") != {
                "COMPLETE": 1, "PENDING": 6, "STOPPED": 1}
            or prestate.get("seq") != 132
            or prestate.get("unknown_run_ids") != [MPP006_STOPPED_RUN_ID]
            or prestate.get("reserved_usd") != "6.30784"):
        raise ValueError("MPP006 billing sidecar does not describe the stopped conditional charge")
    return {"prior_run_id": MPP006_STOPPED_RUN_ID,
            "prior_reservation_usd": str(MPP006_ORIGINAL_RESERVATION_USD),
            "billing_status": "CONTINGENT", "evidence_ref": evidence}


def required_headroom(per_episode_reserve: Decimal, remaining: int) -> Decimal:
    """Add the unassigned account residual; ledger available already nets MPP006."""
    if per_episode_reserve < 0 or remaining < 0:
        raise ValueError("AP2 reserve and remaining rows must be nonnegative")
    return (per_episode_reserve * remaining + CONTINGENCY_USD
            + UNASSIGNED_ACCOUNT_RESIDUAL_USD)
