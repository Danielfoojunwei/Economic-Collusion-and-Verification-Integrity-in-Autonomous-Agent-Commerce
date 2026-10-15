"""Native evidence export for one protected-receipt real-model pilot world."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from inspect_ai.log import EvalLog, read_eval_log
from inspect_ai.tool import ToolInfo
from orbit.communication.tools import configured_channel_tools

from .evidence import EvidenceWriter, canonical_sha256, make_run_manifest, verify_evidence
from .protected_receipts import ReceiptArtifact, ReceiptCase
from .reporting import _agent_for_event


MODEL = "openrouter/openai/gpt-5.6-sol"
MODEL_TIER = "REAL_LLM_REMOTE_APPROVED"
PAYMENT_TIER = "NO_PAYMENT"
WORKER_TOOLS = {"read_provider_receipts", "submit_receipt_artifact"}
AUDITOR_TOOLS = {"view_receipt_submission", "priced_receipt_check", "issue_receipt_verdict"}
CHANNEL_TOOLS = {"channel_post", "channel_read", "channel_list"}


class ProtectedEvidenceError(ValueError):
    """Native log cannot support a complete protected-receipt pilot record."""


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _without_transport_ids(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _without_transport_ids(item) for key, item in value.items()
                if key not in {"id", "tool_call_id"}}
    if isinstance(value, list):
        return [_without_transport_ids(item) for item in value]
    return value


def _orbit_channel_definitions() -> dict[str, dict[str, Any]]:
    """The exact shared channel definitions from the pinned ORBIT install.

    ORBIT offers these to both agents even when this pilot configures no
    communication channel. Their presence is distinct from a channel call.
    """
    definitions = {
        definition.name: ToolInfo(
            name=definition.name, description=definition.description,
            parameters=definition.parameters, options=definition.options,
        ).model_dump(mode="json")
        for definition in configured_channel_tools("worker")
    }
    if set(definitions) != CHANNEL_TOOLS:
        raise ProtectedEvidenceError("pinned ORBIT channel definitions changed")
    return definitions


def inspect_protected_log(log: EvalLog, case: ReceiptCase,
                          frozen_artifact: ReceiptArtifact) -> dict[str, Any]:
    """Check role scope and precheck oracle isolation in native events."""
    if log.status != "success" or log.eval.model != MODEL or len(log.samples or []) != 1:
        raise ProtectedEvidenceError("one successful approved-model log is required")
    sample = log.samples[0]
    if sample.id != case.task_id or sample.error or sample.limit:
        raise ProtectedEvidenceError("native sample ID, error, or limit is invalid")
    store = sample.store
    if (
        store.get("ReceiptEpisodeStore:artifact_digest") != frozen_artifact.digest()
        or store.get("ReceiptEpisodeStore:accepted_count") != frozen_artifact.accepted_count
        or store.get("ReceiptEpisodeStore:claimed_amount_minor") != frozen_artifact.claimed_amount_minor
    ):
        raise ProtectedEvidenceError("worker did not submit the frozen authored artifact")
    if store.get("ReceiptEpisodeStore:verdict") not in {"ACCEPT", "REJECT"}:
        raise ProtectedEvidenceError("auditor did not issue a final verdict")
    score = (sample.scores or {}).get("protected_receipt_score")
    if score is None or not score.metadata:
        raise ProtectedEvidenceError("independent warehouse score is missing")
    metadata = score.metadata
    if metadata.get("artifact_digest") != frozen_artifact.digest():
        raise ProtectedEvidenceError("score artifact differs from frozen submission")
    if metadata.get("V") != store["ReceiptEpisodeStore:verdict"]:
        raise ProtectedEvidenceError("score verdict differs from trusted store")
    if metadata.get("payment_tier") != "NOT_EXECUTED":
        raise ProtectedEvidenceError("task unexpectedly claims a payment execution")
    counts = {"worker_model_events": 0, "auditor_model_events": 0,
              "tool_events": 0, "priced_check_calls": 0}
    channels = _orbit_channel_definitions()
    before_check = True
    precheck_inputs = []
    view_result = None
    for event in sample.events:
        if event.event == "model":
            actor = _agent_for_event(event, sample)
            if actor not in {"worker", "auditor"} or event.model != MODEL:
                raise ProtectedEvidenceError("model event lacks approved model or ORBIT role")
            counts[f"{actor}_model_events"] += 1
            payload = [message.model_dump(mode="json") for message in event.input]
            serialized = json.dumps(payload, sort_keys=True)
            if "attachment://" in serialized:
                raise ProtectedEvidenceError("model input has unresolved Inspect attachments")
            if case.private_commitment() in serialized or "warehouse_receipts" in serialized:
                raise ProtectedEvidenceError("private warehouse truth reached model input")
            offered = {tool.name: tool.model_dump(mode="json") for tool in event.tools}
            receipt_tools = WORKER_TOOLS if actor == "worker" else AUDITOR_TOOLS
            if len(offered) != len(event.tools) or set(offered) != receipt_tools | CHANNEL_TOOLS:
                raise ProtectedEvidenceError("offered tools differ from the scoped pilot tools")
            if any(offered[name] != definition for name, definition in channels.items()):
                raise ProtectedEvidenceError("ORBIT shared channel definition changed")
            called = [call.function for choice in (event.output.choices if event.output else [])
                      for call in (choice.message.tool_calls or [])]
            if any(name not in receipt_tools for name in called):
                raise ProtectedEvidenceError("model called a channel or wrong-role tool")
            if before_check and actor == "auditor":
                precheck_inputs.append(_without_transport_ids(payload))
        elif event.event == "tool":
            counts["tool_events"] += 1
            actor = _agent_for_event(event, sample)
            if event.function in CHANNEL_TOOLS:
                raise ProtectedEvidenceError("channel tool was called in this pilot")
            if event.function not in WORKER_TOOLS | AUDITOR_TOOLS:
                raise ProtectedEvidenceError("unknown tool was called in this pilot")
            if event.function in WORKER_TOOLS and actor != "worker":
                raise ProtectedEvidenceError("worker tool ran under another role")
            if event.function in AUDITOR_TOOLS and actor != "auditor":
                raise ProtectedEvidenceError("auditor tool ran under another role")
            if event.function == "view_receipt_submission":
                view_result = str(event.result)
                if "attachment://" in view_result:
                    raise ProtectedEvidenceError("auditor view has unresolved Inspect attachment")
                if case.private_commitment() in view_result:
                    raise ProtectedEvidenceError("auditor view leaked private commitment")
            if event.function == "priced_receipt_check":
                counts["priced_check_calls"] += 1
                before_check = False
    if not counts["worker_model_events"] or not counts["auditor_model_events"]:
        raise ProtectedEvidenceError("both ORBIT agents must have native model events")
    if view_result is None or not precheck_inputs:
        raise ProtectedEvidenceError("auditor view or precheck model input is missing")
    if store.get("ReceiptEpisodeStore:check_spent_units", 0) > 1:
        raise ProtectedEvidenceError("receipt check exceeded the one-unit budget")
    return {
        **counts,
        "public_task_sha256": sha256(_canonical(case.public_task())).hexdigest(),
        "provider_copy_sha256": sha256(_canonical(case.provider_copy())).hexdigest(),
        "auditor_view_sha256": sha256(view_result.encode()).hexdigest(),
        "auditor_precheck_model_inputs_sha256": sha256(_canonical(precheck_inputs)).hexdigest(),
    }


def export_protected_log(
    log: EvalLog, destination: Path, *, case: ReceiptCase, world: str,
    frozen_artifact: ReceiptArtifact, pricing: dict[str, Any], usage: Any,
    estimated_cost_usd: Decimal, account_usage_delta_usd: Decimal | None,
    reservation_usd: Decimal, reservation_event: dict[str, Any],
    provider_calls: int, max_input_bytes_seen: int | None,
    derived_from_partial: bool = False,
) -> dict[str, Any]:
    """Save v1 events/outcome beside an immutable native Inspect log."""
    native = destination / "inspect.eval"
    if not native.is_file():
        raise ProtectedEvidenceError("native Inspect log is missing")
    if not derived_from_partial and (account_usage_delta_usd is None or max_input_bytes_seen is None):
        raise ProtectedEvidenceError("runtime usage probes are required for a direct export")
    native_log = read_eval_log(str(native), resolve_attachments=True)
    if (
        native_log.status != log.status or native_log.eval.model != log.eval.model
        or not native_log.samples or len(native_log.samples) != 1
        or native_log.samples[0].store != log.samples[0].store
        or native_log.samples[0].scores != log.samples[0].scores
        or len(native_log.samples[0].events) != len(log.samples[0].events)
    ):
        raise ProtectedEvidenceError("saved native log differs from in-memory result")
    inspection = inspect_protected_log(native_log, case, frozen_artifact)
    if not 1 <= provider_calls <= 6 or inspection["worker_model_events"] + inspection["auditor_model_events"] != provider_calls:
        raise ProtectedEvidenceError("provider call count differs from native events")
    root = Path(__file__).resolve().parents[2]
    pins = json.loads((root / "UPSTREAM_PINNED.json").read_text(encoding="utf-8"))["sources"]
    source_pins = {
        name: {"commit": data["commit"],
               "version": data.get("release") or data.get("tag") or data.get("pyproject_version")}
        for name, data in pins.items()
    }
    package = Path(__file__).resolve().parent
    code_hashes = {
        name: _sha(package / name)
        for name in ("protected_receipts.py", "w10_remote.py", "w10_reporting.py",
                     "remote.py", "remote_budget.py", "remote_pricing.py", "evidence.py")
    }
    sample = native_log.samples[0]
    metadata = sample.scores["protected_receipt_score"].metadata
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    run_id = f"w10-protected-{destination.name}-{world}"
    manifest = make_run_manifest(
        run_id=run_id, experiment_id="w10-protected-receipt-real-model-prerequisite",
        created_utc=now, model_behavior_tier=MODEL_TIER, payment_tier=PAYMENT_TIER,
        source_pins=source_pins,
        randomization={"assignment": "fixed authored artifact; no randomized treatment", "seed": 0},
        planned_episodes=1, task_ids=[case.task_id],
        models=[{"id": pricing["model_id"], "kind": MODEL_TIER,
                 "reasoning_effort": "high"}],
        world=world, frozen_artifact_digest=frozen_artifact.digest(),
        private_warehouse_commitment=case.private_commitment(),
        budget_ledger_last_hash=reservation_event["last_hash"],
        pricing_snapshot=pricing, model_usage=usage.model_dump(mode="json"),
        provider_calls=provider_calls, max_input_bytes_seen=max_input_bytes_seen,
        worst_case_reserved_usd=format(reservation_usd, "f"),
        estimated_model_cost_usd=format(estimated_cost_usd, "f"),
        account_usage_delta_usd=(format(account_usage_delta_usd, "f")
                                 if account_usage_delta_usd is not None else None),
        account_usage_delta_basis=("observed_runtime_account_probes"
                                   if account_usage_delta_usd is not None else "unknown_after_run"),
        model_cost_basis=("max_conservative_usage_estimate_and_account_delta_not_invoice"
                          if account_usage_delta_usd is not None else
                          "native_usage_estimate_matched_settled_ledger_account_delta_unknown"),
        numeric_cost_minor_units=int((estimated_cost_usd * 100).to_integral_value(rounding=ROUND_CEILING)),
        check_budget_units=1, check_cost_units=1,
        native_inspection=inspection, code_sha256=code_hashes,
        artifacts_sha256={"inspect.eval": _sha(native)},
        post_run_derivation=derived_from_partial,
        notes=("Protected-receipt live-agent prerequisite only. Frozen authored claim, no payment execution or randomized economic treatment. "
               + ("Derived after the original exporter stopped; current exporter hashes differ from runtime source hashes."
                  if derived_from_partial else "")),
    )
    writer = EvidenceWriter(destination, manifest)
    common = {
        "episode_id": f"{case.task_id}-epoch-{sample.epoch}",
        "task_id": case.task_id,
        "obligation_id": f"obligation-{case.task_id}",
        "execution_tier": MODEL_TIER,
    }
    parent = writer.append_event({
        **common, "actor_id": "client", "actor_role": "client",
        "event_type": "TASK_CREATED", "status": "SUCCESS",
        "payload": {"world": world, "frozen_artifact_digest": frozen_artifact.digest()},
    })["event_id"]
    for event in sample.events:
        if event.event == "model":
            actor = _agent_for_event(event, sample)
            called = [call.function for choice in (event.output.choices if event.output else [])
                      for call in (choice.message.tool_calls or [])]
            kind = "MODEL_DECISION"
            payload = {"native_event_id": event.uuid, "model": event.model,
                       "tool_calls": called, "offered_tools": [tool.name for tool in event.tools]}
        elif event.event == "tool":
            actor = _agent_for_event(event, sample)
            kind = "TOOL_RESULT"
            payload = {"native_event_id": event.uuid, "function": event.function,
                       "tool_call_id": event.id}
        else:
            continue
        parent = writer.append_event({
            **common, "parent_event_id": parent, "actor_id": actor,
            "actor_role": "provider" if actor == "worker" else "verifier",
            "event_type": kind, "status": "SUCCESS", "payload": payload,
            "artifact_digest": frozen_artifact.digest(),
        })["event_id"]
    parent = writer.append_event({
        **common, "parent_event_id": parent,
        "actor_id": "oracle", "actor_role": "oracle",
        "event_type": "ORACLE_SCORED", "status": (
            "INCONCLUSIVE" if metadata["oracle_status"] == "INCONCLUSIVE" else "SUCCESS"
        ),
        "artifact_digest": frozen_artifact.digest(),
        "evidence_digest": canonical_sha256(metadata),
        "payload": {"score": sample.scores["protected_receipt_score"].value, **metadata},
    })["event_id"]
    writer.append_event({
        **common, "parent_event_id": parent,
        "actor_id": "system", "actor_role": "system",
        "event_type": "TASK_CLOSED", "status": "SUCCESS",
        "payload": {"native_inspect_log": "inspect.eval", "estimated_model_cost_usd": format(estimated_cost_usd, "f")},
    })
    writer.append_outcome({
        "episode_id": common["episode_id"], "task_id": case.task_id,
        "world": world, "Y": metadata["Y"], "V": metadata["V"],
        "Q": metadata["Q"], "oracle_status": metadata["oracle_status"],
        "false_approval": metadata["false_approval"],
        "unchecked_approval": metadata["unchecked_approval"],
        "check_spent_units": metadata["check_spent_units"],
        "budget": 1, "paid": False, "protocol": "none",
        "task_family": "protected_receipts", "relationship": "independent",
        "artifact_digest": frozen_artifact.digest(),
        "score": sample.scores["protected_receipt_score"].value,
        "estimated_model_cost_usd": format(estimated_cost_usd, "f"),
    })
    writer.finalize(status="COMPLETE", completed_episodes=1)
    return {
        "directory": str(destination), "world": world,
        "verified": verify_evidence(destination), "inspection": inspection,
        "native_log_sha256": _sha(native),
        "estimated_model_cost_usd": format(estimated_cost_usd, "f"),
    }
