"""Schema-v1 causal event/outcome export for one treated W10 trial."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .evidence import EvidenceWriter, make_run_manifest, verify_evidence
from .w10_factorial import Trial, frozen_fixtures


_ROOT = Path(__file__).resolve().parents[2]


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _agent(event: Any, sample: Any) -> str | None:
    spans = {item.id: item for item in sample.events if item.event == "span_begin"}
    span_id = getattr(event, "span_id", None)
    while span_id is not None:
        span = spans.get(span_id)
        if span is None:
            break
        if span.type == "agent":
            return span.name
        span_id = span.parent_id
    return None


def export_factorial_trial(
    directory: Path, *, trial: Trial, record: dict[str, Any],
    saved_log: Any, native_data: dict[str, Any], model_id: str,
    pricing: dict[str, Any] | None = None,
    source_sha256: dict[str, str] | None = None,
    model_behavior_tier: str = "REAL_LLM_REMOTE_APPROVED",
    reserved_usd: str = "0", max_output_tokens: int = 4096,
    max_input_bytes: int = 32768,
) -> dict[str, Any]:
    """Derive a schema-v1 event chain after native log and payout are verified."""
    if model_behavior_tier not in {"REAL_LLM_REMOTE_APPROVED", "SCRIPTED"}:
        raise ValueError("unsupported model behavior tier")
    directory = Path(directory)
    inspect_path = directory / "inspect.eval"
    native_path = directory / "native_evidence.json"
    record_path = directory / "trial_record.json"
    if not all(path.is_file() for path in (inspect_path, native_path, record_path)):
        raise FileNotFoundError("factorial event export requires native logs and record")
    if (record["trial_id"] != trial.trial_id
            or record["native_inspect_sha256"] != _sha(inspect_path)
            or record["native_payment_sha256"] != _sha(native_path)
            or native_data.get("trial_id") != trial.trial_id
            or native_data.get("task_settlement", {}).get("verdict") != record["verdict"]):
        raise ValueError("factorial event export inputs differ from frozen trial")
    transactions = {tx["step"]: tx for tx in native_data["transactions"]}
    for name in ("assigned_job.fund", "assigned_prepaid_audit_fee",
                 "assigned_job.submit", "assigned_job.auditor_verdict"):
        if name not in transactions or transactions[name]["status"] != 1:
            raise ValueError("native causal transaction is missing or reverted")
    sample = saved_log.samples[0]
    score = sample.scores["protected_receipt_score"].metadata
    fixture = next(f for f in frozen_fixtures() if f.fixture_id == trial.fixture_id)
    if score["V"] != record["verdict"] or score["Y"] != fixture.truth:
        raise ValueError("native scorer differs from controller truth or auditor verdict")
    current_sources = {name: _sha(_ROOT / name) for name in (
        "src/agent_economic_trust/w10_factorial.py",
        "src/agent_economic_trust/w10_live_native.py",
        "src/agent_economic_trust/w10_factorial_remote.py",
        "src/agent_economic_trust/w10_factorial_reporting.py",
        "src/agent_economic_trust/protected_receipts.py",
        "src/agent_economic_trust/remote.py",
        "src/agent_economic_trust/remote_budget.py",
        "src/agent_economic_trust/remote_pricing.py",
        "src/agent_economic_trust/evidence.py",
        "scripts/run_erc8183_local.py",
    )}
    if source_sha256 is not None and (source_sha256 != current_sources
                                      or record.get("source_sha256") != source_sha256):
        raise ValueError("source hashes changed since the provider request")
    created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest = make_run_manifest(
        run_id=record["ledger_run_id"], experiment_id="w10-economic-rsp-exploratory",
        created_utc=created, model_behavior_tier=model_behavior_tier,
        payment_tier="NATIVE_LOCAL_CHAIN",
        source_pins={
            "orbit": {"version": "1.0.3"},
            "inspect_ai": {"version": "0.3.263"},
            "erc8183_base": {"commit": "142e669c1fd318486a4628395b629f033654dd06"},
        },
        randomization={
            "assignment_unit": "fresh_worker_auditor_economic_pair",
            "assignment_manifest_sha256": record["assignment_manifest_sha256"],
            "trial_id": trial.trial_id, "pair_id": trial.pair_id,
            "R": trial.r, "S": trial.s, "P": trial.p,
        },
        planned_episodes=1, task_ids=[fixture.case.task_id],
        models=[{"id": model_id, "kind": model_behavior_tier,
                 "reasoning_effort": "high" if model_behavior_tier != "SCRIPTED" else "scripted"}],
        obligation_id=trial.obligation_id,
        artifact_digest=trial.artifact_digest,
        check_budget_units=trial.check_budget_units,
        check_cost_units=trial.check_cost_units,
        model_cost_usd_estimate=record["model_cost_usd_estimate"],
        pricing_snapshot=pricing or {"kind": "scripted_control", "remote_calls": 0},
        project_cap_usd="20", ledger_run_id=record["ledger_run_id"],
        ledger_last_hash=record.get("ledger_last_hash"),
        worst_case_reserved_usd=reserved_usd,
        input_byte_cap=max_input_bytes, completion_cap=max_output_tokens,
        source_sha256=current_sources,
        artifacts_sha256={
            "inspect.eval": _sha(inspect_path),
            "native_evidence.json": _sha(native_path),
            "trial_record.json": _sha(record_path),
        },
        notes=("Causal order is a verified native local fee, saved live model actions, "
               "independent oracle score, and ERC-8183 settlement by the auditor verdict. "
               "ERC-20 fee obligation binding is application-level; ERC-8183 does not "
               "judge artifact semantics. One exploratory trial, not an arm result."),
    )
    writer = EvidenceWriter(directory, manifest)
    episode = trial.trial_id
    common = {"episode_id": episode, "task_id": fixture.case.task_id,
              "obligation_id": trial.obligation_id,
              "artifact_digest": trial.artifact_digest}
    parent = None

    def emit(actor_id: str, actor_role: str, event_type: str, payload: dict[str, Any],
             *, protocol_name: str | None = None, payment_reference: str | None = None,
             amount_minor_units: int | None = None, status: str = "SUCCESS") -> None:
        nonlocal parent
        parent = writer.append_event({
            **common, "parent_event_id": parent,
            "actor_id": actor_id, "actor_role": actor_role,
            "event_type": event_type, "status": status,
            "protocol_name": protocol_name,
            "protocol_version": ("local pinned" if protocol_name else None),
            "payment_reference": payment_reference,
            "amount_minor_units": amount_minor_units,
            "currency": ("valueless MockUSDC" if amount_minor_units is not None else None),
            "payload": payload,
        })["event_id"]

    emit("client", "client", "TASK_CREATED", {
        "trial_id": trial.trial_id, "pair_id": trial.pair_id,
        "R": trial.r, "S": trial.s, "P": trial.p,
        "public_task_digest": trial.public_task_digest,
        "provider_digest": trial.provider_digest,
    })
    funded = transactions["assigned_job.fund"]
    emit("client", "client", "JOB_FUNDED", {
        "job_id": native_data["job_id"],
        "block_timestamp": funded["block_timestamp"],
        "receipt_status": funded["status"],
    }, protocol_name="ERC-8183", payment_reference=funded["transaction_hash"],
         amount_minor_units=20_000_000)
    fee = transactions["assigned_prepaid_audit_fee"]
    emit("worker" if trial.r else "client", "payer", "AUDITOR_FEE_PAID", {
        "payer_role": "worker" if trial.r else "client",
        "auditor_role": "auditor", "block_timestamp": fee["block_timestamp"],
        "receipt_status": fee["status"],
        "application_obligation_binding": trial.obligation_id,
    }, protocol_name="ERC-20", payment_reference=fee["transaction_hash"],
         amount_minor_units=2_000_000)
    for event in sample.events:
        if event.event == "model":
            actor = _agent(event, sample)
            if actor not in {"worker", "auditor"}:
                raise ValueError("native model event lacks ORBIT role")
            called = [call.function for choice in (event.output.choices if event.output else [])
                      for call in (choice.message.tool_calls or [])]
            emit(actor, "provider" if actor == "worker" else "verifier", "MODEL_DECISION", {
                "native_event_id": event.uuid, "model": event.model,
                "offered_tools": [tool.name for tool in event.tools or []],
                "tool_calls": called,
            })
        elif event.event == "tool":
            actor = _agent(event, sample)
            if actor not in {"worker", "auditor"}:
                raise ValueError("native tool event lacks ORBIT role")
            emit(actor, "provider" if actor == "worker" else "verifier", "TOOL_RESULT", {
                "native_event_id": event.uuid, "function": event.function,
                "result_sha256": sha256(str(event.result).encode()).hexdigest(),
            })
    emit("auditor", "verifier", "AUDITOR_VERDICT", {
        "verdict": record["verdict"], "checked": record["checked"],
        "channel_isolation_audit": record["channel_isolation_audit"],
        "treatment_audit": record.get("treatment_audit"),
    })
    emit("oracle", "oracle", "ORACLE_SCORED", {
        "Y": fixture.truth, "oracle_status": score["oracle_status"],
        "false_approval": score["false_approval"],
    })
    submitted = transactions["assigned_job.submit"]
    emit("worker", "provider", "JOB_SUBMITTED", {
        "job_id": native_data["job_id"],
        "artifact_digest": trial.artifact_digest,
        "block_timestamp": submitted["block_timestamp"],
    }, protocol_name="ERC-8183", payment_reference=submitted["transaction_hash"])
    settled = transactions["assigned_job.auditor_verdict"]
    emit("settlement", "settlement", "PROVIDER_PAID" if record["payment_status"] == "PAID"
         else "JOB_REJECTED_REFUNDED", {
        "job_id": native_data["job_id"],
        "job_status": native_data["task_settlement"]["job_status"],
        "block_timestamp": settled["block_timestamp"],
        "receipt_status": settled["status"],
    }, protocol_name="ERC-8183", payment_reference=settled["transaction_hash"],
         amount_minor_units=record["provider_payout_minor_units"])
    emit("system", "system", "TASK_CLOSED", {
        "model_cost_usd_estimate": record["model_cost_usd_estimate"],
        "native_inspect_sha256": record["native_inspect_sha256"],
        "native_payment_sha256": record["native_payment_sha256"],
    })
    writer.append_outcome({
        "episode_id": episode, "task_id": fixture.case.task_id,
        "pair_id": trial.pair_id, "fixture_id": trial.fixture_id,
        "R": trial.r, "S": trial.s, "P": trial.p,
        "Y": fixture.truth, "V": record["verdict"], "Q": record["checked"],
        "M": record["payment_status"],
        "false_approval": record["false_approval"],
        "wrong_payment": fixture.truth == 0 and record["payment_status"] == "PAID",
        "legitimate_nonpayment": fixture.truth == 1 and record["payment_status"] != "PAID",
        "check_budget_units": trial.check_budget_units,
        "check_cost_units": trial.check_cost_units,
        "check_spent_units": record["check_spent_units"],
        "audit_fee_payer": "worker" if trial.r else "client",
        "audit_fee_minor_units": 2_000_000,
        "provider_payout_minor_units": record["provider_payout_minor_units"],
        "model_cost_usd_estimate": record["model_cost_usd_estimate"],
        "channel_isolation_audit": record["channel_isolation_audit"],
    })
    cents = int((Decimal(record["model_cost_usd_estimate"]) * 100)
                .to_integral_value(rounding=ROUND_CEILING))
    writer.finalize(status="COMPLETE", completed_episodes=1,
                    numeric_cost_minor_units=cents)
    return verify_evidence(directory)
