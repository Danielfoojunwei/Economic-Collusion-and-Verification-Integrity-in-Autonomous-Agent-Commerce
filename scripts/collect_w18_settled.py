#!/usr/bin/env python3
"""Read-only forensic recovery of the first settled W18 seed-211 native log.

The original STOPPED.json, inspect.eval, and project ledger are never edited.
The collector writes one new, separate derivative record after all checks pass.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = str(WORKSPACE_ROOT / ".local" / "share")
os.environ["XDG_CACHE_HOME"] = str(WORKSPACE_ROOT / ".cache")
os.environ["XDG_CONFIG_HOME"] = str(WORKSPACE_ROOT / ".config")
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from inspect_ai.log import read_eval_log  # noqa: E402

from agent_economic_trust.remote import (  # noqa: E402
    APPROVED_MODEL_ID, PROJECT_LEDGER_PATH, _sha256, _usage_for,
)
from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402
from agent_economic_trust.remote_pricing import estimate_usage  # noqa: E402
from agent_economic_trust.w18_meeting_remote import (  # noqa: E402
    _behavior_signature, _code_hashes, _scan_native_log_for_secret,
)
from agent_economic_trust.w18_meeting_task import (  # noqa: E402
    heldout_pilot_case, inspect_meeting_log,
)


SOURCE = PROJECT_ROOT / "artifacts/gates/G7/W18/live-heldout-pilot-001"
PREFLIGHT = PROJECT_ROOT / "artifacts/gates/G7/W18/live-readiness-001/preflight.json"
OUTPUT = PROJECT_ROOT / "artifacts/gates/G7/W18/live-heldout-pilot-001-recovered-001"
ARCHIVED_PRE_RUN_SOURCE = (
    PROJECT_ROOT / "artifacts/gates/G7/W18/live-readiness-001/w18_meeting_remote.pre-run.py"
)
RUN_ID = "w18-meeting-f376a261dae2f5bd9ee9679c"
NATIVE_SHA256 = "2cc71be8592e0cd12317e6868dad55448d390d0e05e0a91e7604d57cb9232e22"
SETTLED_USD = Decimal("0.08982")


def _archive_resolution_audit(unresolved, resolved) -> dict[str, int | bool]:
    before = _behavior_signature(unresolved, include_inputs=False)
    after = _behavior_signature(resolved, include_inputs=False)
    if len(before) != len(after) or before == after:
        raise ValueError("expected native output-attachment resolution mismatch is absent")
    output_differences = 0
    for left, right in zip(before, after):
        changed = {key for key in left if left[key] != right[key]}
        if changed:
            if left["kind"] != "model" or changed != {"output"}:
                raise ValueError("saved native event changed outside output attachment resolution")
            if "attachment://" not in str(left["output"]) or "attachment://" in str(right["output"]):
                raise ValueError("model output difference is not an attachment resolution")
            output_differences += 1
    if output_differences == 0:
        raise ValueError("no model output attachments were resolved")
    return {
        "unresolved_vs_resolved_behavior_equal": False,
        "model_outputs_changed_by_attachment_resolution": output_differences,
        "other_behavior_fields_changed": 0,
    }


def collect(*, output_dir: Path = OUTPUT) -> dict:
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError("forensic output path already exists")
    preflight = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    sealed = preflight.get("code_sha256")
    current = _code_hashes()
    if not isinstance(sealed, dict) or set(sealed) != set(current):
        raise ValueError("readiness source-seal paths differ from the current collector")
    archived_hash = sha256(ARCHIVED_PRE_RUN_SOURCE.read_bytes()).hexdigest()
    if archived_hash != sealed["w18_meeting_remote.py"]:
        raise ValueError("archived pre-run exporter bytes differ from the readiness source seal")
    current_others = {name: digest for name, digest in current.items()
                      if name != "w18_meeting_remote.py"}
    sealed_others = {name: digest for name, digest in sealed.items()
                     if name != "w18_meeting_remote.py"}
    if current_others != sealed_others:
        raise ValueError("other current W18 source files differ from the readiness source seal")
    if (preflight.get("task_id") != "orbit-meeting-heldout-211"
            or preflight.get("model_id") != APPROVED_MODEL_ID
            or preflight.get("reasoning_effort") != "high"
            or preflight.get("worst_case_reservation_usd") != "3.194880"):
        raise ValueError("readiness preflight does not describe the approved held-out pilot")
    stopped_path = SOURCE / "STOPPED.json"
    native_path = SOURCE / "inspect.eval"
    stopped = json.loads(stopped_path.read_text(encoding="utf-8"))
    if (stopped.get("status") != "PARTIAL" or stopped.get("run_id") != RUN_ID
            or stopped.get("budget_state") != "SETTLED"
            or stopped.get("error_type") != "RemoteBoundaryError"
            or stopped.get("complete_outcome_exported") is not False
            or stopped.get("native_log_sha256") != NATIVE_SHA256
            or _sha256(native_path) != NATIVE_SHA256):
        raise ValueError("STOPPED record or original native Inspect log differs")
    ledger = BudgetLedger(PROJECT_LEDGER_PATH).snapshot()
    run = ledger["runs"].get(RUN_ID)
    if (ledger["blocked"] or run is None or run.get("status") != "SETTLED"
            or run.get("evidence_ref") != f"sha256:{NATIVE_SHA256}"
            or Decimal(run.get("actual_usd", "NaN")) != SETTLED_USD
            or Decimal(run.get("reserved_usd", "NaN")) != Decimal("3.19488")):
        raise ValueError("shared ledger does not reconcile to the original native log")
    credential = os.environ.get("OPENROUTER_API_KEY")
    if not credential:
        raise ValueError("credential must be present to scan the saved archive exactly")
    unresolved = read_eval_log(str(native_path), resolve_attachments=False)
    resolved = read_eval_log(str(native_path), resolve_attachments=True)
    _scan_native_log_for_secret(native_path, resolved, credential)
    attachment_audit = _archive_resolution_audit(unresolved, resolved)
    case = heldout_pilot_case()
    inspection = inspect_meeting_log(
        resolved, case, expected_model=f"openrouter/{APPROVED_MODEL_ID}",
        require_real_model=True,
    )
    if inspection["model_events"] != 6 or inspection["priced_check_calls"] != 1:
        raise ValueError("saved native trace lacks the bounded six-call checked pilot")
    sample = resolved.samples[0]
    score = sample.scores["meeting_audit_score"]
    metadata = score.metadata
    usage = _usage_for(resolved, APPROVED_MODEL_ID)
    forecast_estimate = estimate_usage(preflight["public_pricing_snapshot"], usage, calls=6)
    if forecast_estimate != SETTLED_USD:
        raise ValueError("saved public pricing and native usage do not match settled estimate")
    if (metadata["Y"] != 0 or metadata["V"] != "REJECT"
            or metadata["Q"] is not True or metadata["check_spent_units"] != 1
            or metadata["oracle_reason"] != "INVALID_ATTENDANCE"
            or score.value != 1):
        raise ValueError("saved native pilot outcome differs from the forensic classification")
    return {
        "schema": "w18-settled-native-recovery-v1",
        "classification": "RECOVERED_FROM_SETTLED_NATIVE_LOG",
        "original_run_status": "PARTIAL",
        "original_stop_reason_class": "POST_SETTLEMENT_ATTACHMENT_COMPARISON_FALSE_POSITIVE",
        "task_id": case.task_id, "split": case.split,
        "exploratory": True, "confirmatory": False, "g7_complete": False,
        "model_execution_tier": "REAL_LLM_REMOTE_APPROVED",
        "model_id": APPROVED_MODEL_ID, "reasoning_effort": "high",
        "payment_tier": "NO_PAYMENT", "native_payment_execution": False,
        "run_id": RUN_ID,
        "native_inspect_sha256": NATIVE_SHA256,
        "original_stopped_sha256": _sha256(stopped_path),
        "readiness_preflight_sha256": _sha256(PREFLIGHT),
        "pre_run_code_sha256": preflight["code_sha256"],
        "archived_pre_run_exporter_sha256": archived_hash,
        "current_fixed_exporter_sha256": current["w18_meeting_remote.py"],
        "source_seal_validation": (
            "exact SHA-matched archived pre-run exporter; current files for all other sealed paths"
        ),
        "collector_source_sha256": _sha256(Path(__file__)),
        "pre_run_orbit_source_sha256": preflight["orbit_source_sha256"],
        "source_binding_limit": (
            "The native log does not cryptographically bind adapter source. "
            "Readiness captured a pre-run source seal and the runner guarded it at calls. "
            "The archived exporter is a SHA-verified reverse-patch preimage, not an independently saved original."
        ),
        "native_inspection": inspection,
        "attachment_resolution_audit": attachment_audit,
        "outcome": {
            "Y": metadata["Y"], "V": metadata["V"], "Q": metadata["Q"],
            "oracle_status": metadata["oracle_status"],
            "oracle_reason": metadata["oracle_reason"],
            "artifact_digest": metadata["artifact_digest"],
            "check_spent_units": metadata["check_spent_units"],
            "auditor_policy_score": score.value,
        },
        "model_usage": usage.model_dump(mode="json"),
        "saved_public_pricing_usage_estimate_usd": format(forecast_estimate, "f"),
        "settled_ledger_usd": format(SETTLED_USD, "f"),
        "settled_cost_basis": "conservative usage/account estimate, not provider invoice",
        "ledger_snapshot_seq": ledger["seq"],
        "ledger_snapshot_last_hash": ledger["last_hash"],
        "claim_limit": (
            "One exploratory held-out task with no native payment; no economic, "
            "model-version, domain-generalization, or G7 completion claim."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = collect(output_dir=args.output_dir)
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    path = args.output_dir / "evidence.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    os.chmod(path, 0o600)
    print(json.dumps({"output": str(path), "sha256": _sha256(path),
                      "classification": result["classification"]}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never print a provider exception or native prompt during recovery.
        print(f"W18 recovery stopped: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
