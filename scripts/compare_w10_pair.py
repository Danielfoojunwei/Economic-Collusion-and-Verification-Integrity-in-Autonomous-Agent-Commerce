#!/usr/bin/env python3
"""Read-only comparison of the two fixed protected-receipt live pilot worlds."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from inspect_ai.log import read_eval_log

from agent_economic_trust.evidence import verify_evidence
from agent_economic_trust.reporting import _agent_for_event
from agent_economic_trust.remote_budget import BudgetLedger
from agent_economic_trust.w10_recovery import verify_recovery
from agent_economic_trust.w10_remote import FROZEN_ARTIFACT, pilot_case
from agent_economic_trust.w10_reporting import _without_transport_ids, inspect_protected_log


ROOT = Path(__file__).resolve().parents[1]
GOOD_DIR = ROOT / "artifacts/gates/W10_PILOT/real-good-001-derived-complete"
BAD_DIR = ROOT / "artifacts/gates/W10_PILOT/real-bad-001"
LEDGER = ROOT / "artifacts/budget/openrouter-ledger.jsonl"


def _hash(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode()).hexdigest()


def _world(directory: Path, world: str) -> dict[str, object]:
    if not verify_evidence(directory):
        raise ValueError(f"invalid v1 evidence for {world}")
    manifest = json.loads((directory / "run_manifest.json").read_text(encoding="utf-8"))
    native = directory / "inspect.eval"
    native_hash = sha256(native.read_bytes()).hexdigest()
    if manifest["artifacts_sha256"]["inspect.eval"] != native_hash:
        raise ValueError(f"native hash differs from manifest for {world}")
    log = read_eval_log(str(native), resolve_attachments=True)
    case = pilot_case(world)
    inspection = inspect_protected_log(log, case, FROZEN_ARTIFACT)
    if inspection != manifest["native_inspection"]:
        raise ValueError(f"native inspection differs from manifest for {world}")
    sample = log.samples[0]
    first = next(event for event in sample.events if event.event == "model"
                 and _agent_for_event(event, sample) == "auditor")
    first_input = _without_transport_ids(
        [message.model_dump(mode="json") for message in first.input]
    )
    score = sample.scores["protected_receipt_score"].metadata
    return {
        "world": world, "native_sha256": native_hash,
        "first_auditor_input_sha256": _hash(first_input),
        "inspection": inspection,
        "private_warehouse_commitment": case.private_commitment(),
        "oracle_status": score["oracle_status"],
        "verdict": score["V"], "checked": score["Q"],
        "check_spent_units": score["check_spent_units"],
        "paid": False,
    }


def compare() -> dict[str, object]:
    if not verify_recovery()["verified"]:
        raise ValueError("good-world post-run recovery is invalid")
    good, bad = _world(GOOD_DIR, "good"), _world(BAD_DIR, "bad")
    for key in ("public_task_sha256", "provider_copy_sha256", "auditor_view_sha256"):
        if good["inspection"][key] != bad["inspection"][key]:
            raise ValueError(f"worlds differed on visible {key}")
    if good["first_auditor_input_sha256"] != bad["first_auditor_input_sha256"]:
        raise ValueError("first auditor model inputs differ between worlds")
    if good["private_warehouse_commitment"] == bad["private_warehouse_commitment"]:
        raise ValueError("worlds have the same private warehouse facts")
    if ((good["oracle_status"], good["verdict"], good["checked"], good["check_spent_units"])
            != ("PASS", "ACCEPT", True, 1)
            or (bad["oracle_status"], bad["verdict"], bad["checked"], bad["check_spent_units"])
            != ("FAIL", "REJECT", True, 1)):
        raise ValueError("native oracle or auditor behavior differs from pair record")
    ledger = BudgetLedger(LEDGER).snapshot()
    for world in ("good", "bad"):
        run_id = f"w10-protected-real-{world}-001-{world}"
        if ledger["runs"].get(run_id, {}).get("status") != "SETTLED":
            raise ValueError(f"{world} model budget is not settled")
    return {
        "verified": True,
        "identical_first_auditor_input_sha256": good["first_auditor_input_sha256"],
        "identical_public_task_sha256": good["inspection"]["public_task_sha256"],
        "identical_provider_copy_sha256": good["inspection"]["provider_copy_sha256"],
        "identical_auditor_view_sha256": good["inspection"]["auditor_view_sha256"],
        "aggregate_precheck_inputs_identical": (
            good["inspection"]["auditor_precheck_model_inputs_sha256"]
            == bad["inspection"]["auditor_precheck_model_inputs_sha256"]
        ),
        "worlds": [good, bad],
        "ledger_committed_usd": ledger["committed_usd"],
        "ledger_available_usd": ledger["available_usd"],
    }


if __name__ == "__main__":
    print(json.dumps(compare(), indent=2, sort_keys=True))
