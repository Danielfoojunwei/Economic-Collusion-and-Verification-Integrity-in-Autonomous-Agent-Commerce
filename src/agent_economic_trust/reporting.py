"""Export observed Inspect actions into the proposed v1 evidence contract."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
from typing import Any

from inspect_ai.log import EvalLog

from .evidence import EvidenceWriter, canonical_sha256, make_run_manifest, verify_evidence
from .orbit_task import AUDIT_BUDGET_UNITS, CHECK_COST_UNITS, MODEL_TIER, PAYMENT_TIER


_EXPECTED_TOOL = {
    "WORK_SUBMITTED": "submit_artifact",
    "SUBMISSION_VIEWED": "view_submission",
    "CHECK_COMPLETED": "priced_check",
    "CHECK_REJECTED": "priced_check",
    "MOCK_SETTLED": "issue_verdict",
    "VERDICT_ISSUED": "issue_verdict",
}
_ROLE = {"worker": "provider", "auditor": "verifier", "payment_agent": "payer"}
_EVENT_TYPE = {"MOCK_SETTLED": "PAYMENT_SETTLED", "SUBMISSION_VIEWED": "AUDIT_REQUESTED"}


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _agent_for_event(event: Any, sample: Any) -> str | None:
    spans = {
        span.id: span for span in sample.events
        if span.event == "span_begin"
    }
    span_id = getattr(event, "span_id", None)
    while span_id is not None:
        span = spans.get(span_id)
        if span is None:
            break
        if span.type == "agent":
            return span.name
        span_id = span.parent_id
    return None


def assert_log_isolation(log: EvalLog) -> dict[str, int]:
    """Inspect actual model payloads and tool replies before evidence export."""
    counters = {"model_events": 0, "tool_events": 0, "worker_events": 0, "auditor_events": 0}
    for sample in log.samples or []:
        marker = f"private-oracle-{sample.id}"
        check_seen = False
        for event in sample.events:
            if event.event == "model":
                counters["model_events"] += 1
                actor = _agent_for_event(event, sample)
                if actor not in {"worker", "auditor"}:
                    raise AssertionError("model event lacks an ORBIT agent span")
                counters[f"{actor}_events"] += 1
                serialized = json.dumps(
                    [message.model_dump(mode="json") for message in event.input],
                    sort_keys=True,
                )
                if marker in serialized or "private_oracle_marker" in serialized:
                    raise AssertionError(f"private oracle marker reached {actor} model")
                if "expected_amount_cents" in serialized:
                    raise AssertionError(f"private target field reached {actor} model")
                offered = {tool.name for tool in event.tools}
                if actor == "worker" and offered.intersection(
                    {"view_submission", "priced_check", "issue_verdict"}
                ):
                    raise AssertionError("worker received auditor-only tools")
                if actor == "auditor" and "submit_artifact" in offered:
                    raise AssertionError("auditor received worker-only tool")
            elif event.event == "tool":
                counters["tool_events"] += 1
                if event.function == "priced_check":
                    check_seen = True
                else:
                    # Even authorized check output must not contain the private
                    # target marker; prior tool replies also lack oracle status.
                    result = json.dumps(event.result, sort_keys=True, default=str)
                    if marker in result or "private_oracle_marker" in result:
                        raise AssertionError("private marker reached tool reply")
                    if not check_seen and event.function == "view_submission":
                        if '"status": "PASS"' in result or '"status": "FAIL"' in result:
                            raise AssertionError("view_submission leaked oracle status")
        if not sample.scores or "reconciliation_score" not in sample.scores:
            raise AssertionError("independent scorer missing")
    if not counters["worker_events"] or not counters["auditor_events"]:
        raise AssertionError("both native ORBIT agents must execute")
    return counters


def export_log(
    log: EvalLog,
    destination: str | Path,
    *,
    policy: str,
    source_pins: dict[str, Any],
    created_utc: str | None = None,
) -> dict[str, Any]:
    """Save native log and derived, validated evidence for one scripted policy."""
    if log.status != "success" or not log.samples:
        raise ValueError("only complete Inspect evaluations can be exported")
    isolation = assert_log_isolation(log)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    native = destination / "inspect.eval"
    if native.exists():
        raise FileExistsError(f"refusing to overwrite native evidence: {native}")
    shutil.copy2(log.location, native)
    created_utc = created_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    code_root = Path(__file__).resolve().parent
    code_hashes = {
        name: _hash_file(code_root / name)
        for name in ("core.py", "orbit_task.py", "offline.py", "evidence.py", "reporting.py")
    }
    manifest = make_run_manifest(
        run_id=f"g1-{policy}-{canonical_sha256([sample.id for sample in log.samples])[:12]}",
        experiment_id="g1-reconciliation-controlled-pilot",
        created_utc=created_utc,
        model_behavior_tier=MODEL_TIER,
        payment_tier=PAYMENT_TIER,
        source_pins=source_pins,
        randomization={"assignment": "fixed scripted controls", "seed": 0},
        planned_episodes=len(log.samples),
        models=[{"id": "mockllm/reconciliation-control", "kind": "SCRIPTED_CONTROL"}],
        task_ids=[sample.id for sample in log.samples],
        numeric_cost_minor_units=0,
        check_budget_units=AUDIT_BUDGET_UNITS,
        check_cost_units=CHECK_COST_UNITS,
        code_sha256=code_hashes,
        artifacts_sha256={"inspect.eval": _hash_file(native)},
        protocol_capability="mock_escrow_only",
        notes="Controlled verifier plumbing pilot. Fixed worker submissions; no LLM or native payment claims.",
    )
    writer = EvidenceWriter(destination, manifest)
    for sample in log.samples:
        if sample.error or sample.limit:
            raise ValueError(f"sample {sample.id} has an error or limit")
        task_id = str(sample.id)
        episode_id = f"{task_id}-epoch-{sample.epoch}"
        store = sample.store
        actions = store.get("EpisodeStore:actions", [])
        native_tools = [event.function for event in sample.events if event.event == "tool"]
        for action in actions:
            if action["action"] not in _EXPECTED_TOOL:
                raise ValueError(f"unknown trusted action {action['action']}")
            if _EXPECTED_TOOL[action["action"]] not in native_tools:
                raise ValueError(f"trusted action lacks native tool evidence: {action['action']}")
        artifact_digest = store.get("EpisodeStore:artifact_digest")
        parent = writer.append_event({
            "episode_id": episode_id,
            "actor_id": "client", "actor_role": "client",
            "event_type": "TASK_CREATED", "task_id": task_id,
            "obligation_id": f"obligation-{task_id}",
            "artifact_digest": None, "evidence_digest": None,
            "protocol_name": "mock_escrow", "protocol_version": "local-v1",
            "payment_reference": None, "amount_minor_units": 500, "currency": "MOCK_CENT",
            "status": "SUCCESS", "execution_tier": "SCRIPTED_SIMULATION",
            "payload": {"policy": policy, "check_budget_units": AUDIT_BUDGET_UNITS},
        })["event_id"]
        for action in actions:
            kind = action["action"]
            actor = action["actor"]
            receipt = action if kind == "MOCK_SETTLED" else None
            parent = writer.append_event({
                "episode_id": episode_id,
                "parent_event_id": parent,
                "actor_id": actor, "actor_role": _ROLE[actor],
                "event_type": _EVENT_TYPE.get(kind, kind), "task_id": task_id,
                "obligation_id": f"obligation-{task_id}",
                "artifact_digest": artifact_digest,
                "evidence_digest": canonical_sha256(action),
                "protocol_name": "mock_escrow" if receipt else None,
                "protocol_version": "local-v1" if receipt else None,
                "payment_reference": receipt["request_id"] if receipt else None,
                "amount_minor_units": 500 if receipt else None,
                "currency": "MOCK_CENT" if receipt else None,
                "status": "FAIL" if kind == "CHECK_REJECTED" else "SUCCESS",
                "execution_tier": "SCRIPTED_SIMULATION",
                "payload": {"source": "Inspect StoreModel and ToolEvent", "tool_call_verified": True, **action},
            })["event_id"]
        score = sample.scores["reconciliation_score"]
        metadata = score.metadata or {}
        parent = writer.append_event({
            "episode_id": episode_id,
            "parent_event_id": parent,
            "actor_id": "oracle", "actor_role": "oracle",
            "event_type": "ORACLE_SCORED", "task_id": task_id,
            "obligation_id": f"obligation-{task_id}",
            "artifact_digest": artifact_digest,
            "evidence_digest": canonical_sha256(metadata),
            "protocol_name": None, "protocol_version": None,
            "payment_reference": None, "amount_minor_units": None, "currency": None,
            "status": metadata["oracle_status"] if metadata["oracle_status"] == "INCONCLUSIVE" else "SUCCESS",
            "execution_tier": "SCRIPTED_SIMULATION",
            "payload": {"score": score.value, **metadata},
        })["event_id"]
        writer.append_event({
            "episode_id": episode_id,
            "parent_event_id": parent,
            "actor_id": "system", "actor_role": "system",
            "event_type": "TASK_CLOSED", "task_id": task_id,
            "obligation_id": f"obligation-{task_id}",
            "artifact_digest": artifact_digest,
            "evidence_digest": None,
            "protocol_name": "mock_escrow", "protocol_version": "local-v1",
            "payment_reference": None, "amount_minor_units": None, "currency": None,
            "status": "SUCCESS", "execution_tier": "SCRIPTED_SIMULATION",
            "payload": {"native_inspect_log": "inspect.eval"},
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
            "policy": policy, "score": score.value,
        })
    writer.finalize(status="COMPLETE", completed_episodes=len(log.samples))
    verified = verify_evidence(destination)
    if _hash_file(native) != writer.manifest["artifacts_sha256"]["inspect.eval"]:
        raise AssertionError("native Inspect log hash changed during export")
    return {"directory": str(destination), "verified": verified, "isolation": isolation}
