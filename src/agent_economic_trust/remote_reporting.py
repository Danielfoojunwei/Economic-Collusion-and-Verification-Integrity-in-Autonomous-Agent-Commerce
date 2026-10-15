"""Observed real-model ORBIT evidence, separate from scripted controls."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from inspect_ai.log import EvalLog, read_eval_log

from .evidence import EvidenceWriter, canonical_sha256, make_run_manifest, verify_evidence
from .orbit_task import AUDIT_BUDGET_UNITS, CHECK_COST_UNITS
from .reporting import assert_log_isolation, _agent_for_event


MODEL_TIER = "REAL_LLM_REMOTE_APPROVED"
PAYMENT_TIER = "MOCK_LOCAL"
EXECUTION_TIER = "REAL_LLM_REMOTE_APPROVED"
ACTION_ROLE = {"worker": "provider", "auditor": "verifier", "payment_agent": "payer"}
ACTION_TYPE = {"MOCK_SETTLED": "PAYMENT_SETTLED", "SUBMISSION_VIEWED": "AUDIT_REQUESTED"}
ACTION_TOOL = {
    "WORK_SUBMITTED": "submit_artifact",
    "SUBMISSION_VIEWED": "view_submission",
    "CHECK_COMPLETED": "priced_check",
    "CHECK_REJECTED": "priced_check",
    "MOCK_SETTLED": "issue_verdict",
    "VERDICT_ISSUED": "issue_verdict",
}
EXPECTED_MODEL = "openrouter/openai/gpt-5.6-sol"


class IncompleteEpisodeError(ValueError):
    """The real worker or auditor did not perform required pilot actions."""


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def export_remote_log(
    log: EvalLog, destination: Path, *, pricing: dict[str, Any], usage: Any,
    cost_usd: Decimal, reservation_usd: Decimal,
    account_usage_delta_usd: Decimal,
    reservation_event: dict[str, Any], native_path: Path,
    provider_calls: int, max_input_bytes_seen: int,
) -> dict[str, Any]:
    """Export one native sample and verified events after the budget settles."""
    if log.status != "success" or not log.samples or len(log.samples) != 1:
        raise ValueError("a complete single-sample Inspect evaluation is required")
    if log.eval.model != EXPECTED_MODEL:
        raise ValueError("native Inspect run did not use the approved real model")
    if native_path != destination / "inspect.eval" or not native_path.is_file():
        raise ValueError("native Inspect evidence was not saved")
    native_log = read_eval_log(str(native_path))
    if (
        native_log.status != log.status or native_log.eval.model != log.eval.model
        or not native_log.samples or len(native_log.samples) != 1
        or native_log.samples[0].id != log.samples[0].id
        or native_log.samples[0].scores != log.samples[0].scores
        or native_log.samples[0].store != log.samples[0].store
        or len(native_log.samples[0].events) != len(log.samples[0].events)
    ):
        raise ValueError("saved native Inspect log differs from in-memory result")
    if not 1 <= provider_calls <= 5:
        raise ValueError("provider call count is outside the pilot bound")
    isolation = assert_log_isolation(log)
    sample = log.samples[0]
    if sample.error or sample.limit:
        raise ValueError("sample contains an error or reached a limit")
    score = (sample.scores or {}).get("reconciliation_score")
    if score is None or not score.metadata:
        raise ValueError("independent oracle score is missing")
    metadata = score.metadata
    if metadata.get("model_behavior_tier") != MODEL_TIER:
        raise ValueError("native score is not marked as remote LLM behavior")
    if metadata.get("payment_tier") != PAYMENT_TIER:
        raise ValueError("native payment tier differs from mock settlement")
    store = sample.store
    actions = store.get("EpisodeStore:actions", [])
    action_names = {action.get("action") for action in actions}
    if not {"WORK_SUBMITTED", "VERDICT_ISSUED", "MOCK_SETTLED"}.issubset(action_names):
        raise IncompleteEpisodeError("worker submission or auditor verdict is missing")
    if not store.get("EpisodeStore:artifact_digest") or metadata.get("V") not in {"ACCEPT", "REJECT"}:
        raise IncompleteEpisodeError("artifact digest or final verdict is missing")
    native_tools = [event.function for event in sample.events if event.event == "tool"]
    for action in actions:
        if action.get("action") not in ACTION_TOOL:
            raise ValueError("unexpected trusted action")
        if ACTION_TOOL[action["action"]] not in native_tools:
            raise ValueError("trusted action lacks a native Inspect tool event")
    root = Path(__file__).resolve().parents[2]
    pins = json.loads((root / "UPSTREAM_PINNED.json").read_text(encoding="utf-8"))["sources"]
    source_pins = {
        name: {
            "commit": details["commit"],
            "version": details.get("release") or details.get("tag") or details.get("pyproject_version"),
        }
        for name, details in pins.items()
    }
    package = Path(__file__).resolve().parent
    code_hashes = {
        name: _sha256(package / name)
        for name in ("core.py", "orbit_task.py", "remote.py", "remote_budget.py",
                     "remote_pricing.py", "remote_reporting.py", "evidence.py", "reporting.py")
    }
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    task_id = str(sample.id)
    episode_id = f"{task_id}-epoch-{sample.epoch}"
    run_id = f"w05-{destination.parent.name}-{task_id}"
    manifest = make_run_manifest(
        run_id=run_id, experiment_id="w05-reconciliation-real-model-pilot",
        created_utc=now, model_behavior_tier=MODEL_TIER, payment_tier=PAYMENT_TIER,
        source_pins=source_pins,
        randomization={"assignment": "fixed pilot fixture", "seed": 0},
        planned_episodes=1, task_ids=[task_id],
        models=[{"id": pricing["model_id"], "reasoning_effort": "high",
                 "kind": MODEL_TIER}],
        numeric_cost_minor_units=int((cost_usd * 100).to_integral_value(rounding=ROUND_CEILING)),
        estimated_model_cost_usd=format(cost_usd, "f"),
        model_cost_basis="max_conservative_catalog_times_inspect_usage_and_account_delta_not_provider_invoice",
        account_usage_delta_usd=format(account_usage_delta_usd, "f"),
        worst_case_reserved_usd=format(reservation_usd, "f"),
        budget_ledger_last_hash=reservation_event["last_hash"],
        pricing_snapshot=pricing,
        model_usage=usage.model_dump(mode="json"),
        provider_calls=provider_calls,
        max_input_bytes_seen=max_input_bytes_seen,
        check_budget_units=AUDIT_BUDGET_UNITS, check_cost_units=CHECK_COST_UNITS,
        code_sha256=code_hashes,
        artifacts_sha256={"inspect.eval": _sha256(native_path)},
        notes="Real OpenRouter agent behavior on controlled reconciliation fixtures. Mock settlement only; no economic-collusion inference.",
    )
    writer = EvidenceWriter(destination, manifest)
    common = {
        "episode_id": episode_id,
        "task_id": task_id,
        "obligation_id": f"obligation-{task_id}",
        "execution_tier": EXECUTION_TIER,
    }
    parent = writer.append_event({
        **common, "actor_id": "client", "actor_role": "client",
        "event_type": "TASK_CREATED", "status": "SUCCESS",
        "payload": {"model_id": pricing["model_id"], "payment_tier": PAYMENT_TIER},
    })["event_id"]
    for event in sample.events:
        if event.event == "model":
            if event.model != EXPECTED_MODEL:
                raise ValueError("native ModelEvent used a different model")
            actor = _agent_for_event(event, sample)
            tools_called = [
                call.function
                for choice in event.output.choices
                for call in (choice.message.tool_calls or [])
            ] if event.output else []
            kind, payload = "MODEL_DECISION", {
                "native_event_id": event.uuid, "model": event.model,
                "tool_calls": tools_called,
                "offered_tools": [tool.name for tool in event.tools],
            }
        elif event.event == "tool":
            actor = _agent_for_event(event, sample)
            kind, payload = "TOOL_RESULT", {
                "native_event_id": event.uuid, "function": event.function,
                "tool_call_id": event.id,
            }
        else:
            continue
        if actor not in ("worker", "auditor"):
            raise ValueError("native model/tool event lacks a bound ORBIT role")
        parent = writer.append_event({
            **common, "parent_event_id": parent,
            "actor_id": actor, "actor_role": ACTION_ROLE[actor],
            "event_type": kind, "status": "SUCCESS", "payload": payload,
        })["event_id"]
    artifact_digest = store.get("EpisodeStore:artifact_digest")
    for action in actions:
        actor, kind = action["actor"], action["action"]
        receipt = action if kind == "MOCK_SETTLED" else None
        parent = writer.append_event({
            **common, "parent_event_id": parent,
            "actor_id": actor, "actor_role": ACTION_ROLE[actor],
            "event_type": ACTION_TYPE.get(kind, kind),
            "artifact_digest": artifact_digest,
            "evidence_digest": canonical_sha256(action),
            "protocol_name": "mock_escrow" if receipt else None,
            "protocol_version": "local-v1" if receipt else None,
            "payment_reference": receipt["request_id"] if receipt else None,
            "amount_minor_units": 500 if receipt else None,
            "currency": "MOCK_CENT" if receipt else None,
            "status": "FAIL" if kind == "CHECK_REJECTED" else "SUCCESS",
            "payload": {"source": "Inspect StoreModel and ToolEvent", **action},
        })["event_id"]
    parent = writer.append_event({
        **common, "parent_event_id": parent,
        "actor_id": "oracle", "actor_role": "oracle",
        "event_type": "ORACLE_SCORED",
        "artifact_digest": artifact_digest,
        "evidence_digest": canonical_sha256(metadata),
        "status": "INCONCLUSIVE" if metadata["oracle_status"] == "INCONCLUSIVE" else "SUCCESS",
        "payload": {"score": score.value, **metadata},
    })["event_id"]
    writer.append_event({
        **common, "parent_event_id": parent,
        "actor_id": "system", "actor_role": "system",
        "event_type": "TASK_CLOSED", "status": "SUCCESS",
        "payload": {"native_inspect_log": "inspect.eval", "estimated_model_cost_usd": format(cost_usd, "f")},
    })
    writer.append_outcome({
        "episode_id": episode_id, "task_id": task_id,
        "Y": metadata["Y"], "V": metadata["V"], "Q": metadata["Q"],
        "paid": metadata["paid"], "wrong_paid": metadata["wrong_paid"],
        "honest_unpaid": metadata["honest_unpaid"],
        "false_approval": metadata["false_approval"],
        "unchecked_approval": metadata["unchecked_approval"],
        "oracle_status": metadata["oracle_status"],
        "check_spent_units": metadata["check_spent_units"],
        "budget": AUDIT_BUDGET_UNITS, "guard": "none",
        "relationship": "independent", "task_family": "invoice_reconciliation",
        "protocol": "mock_escrow", "artifact_digest": artifact_digest,
        "score": score.value, "estimated_model_cost_usd": format(cost_usd, "f"),
    })
    writer.finalize(status="COMPLETE", completed_episodes=1)
    return {
        "directory": str(destination), "native_log_sha256": _sha256(native_path),
        "verified": verify_evidence(destination), "isolation": isolation,
        "estimated_model_cost_usd": format(cost_usd, "f"),
        "provider_calls": provider_calls,
    }
