"""Schema-v1 evidence export for one independently checked W11 market round."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .evidence import EvidenceWriter, make_run_manifest, verify_evidence
from .w11_market_plan import MarketRound, case_for_round
from .w11_market_task import assigned_message, audit_saved_market_log
from .w11_market_native import verify_market_evidence


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _actor(event: Any, sample: Any) -> str | None:
    spans = {item.id: item for item in sample.events if item.event == "span_begin"}
    current = getattr(event, "span_id", None)
    while current is not None:
        span = spans.get(current)
        if span is None:
            return None
        if span.type == "agent":
            return span.name
        current = span.parent_id
    return None


def export_market_episode(
    output: Path, *, row: MarketRound, saved_log: Any,
    native_data: dict[str, Any], record: dict[str, Any],
    assignment_manifest_sha256: str,
    model_behavior_tier: str,
    model_id: str,
    source_sha256: dict[str, str],
    pricing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Link actual role actions and chain events; no agent claim creates payment."""
    output = Path(output)
    for filename, record_key in (("inspect.eval", "native_inspect_sha256"),
                                 ("native_evidence.json", "native_payment_sha256"),
                                 ("episode_record.json", "episode_record_sha256")):
        if not (output / filename).is_file():
            raise FileNotFoundError(f"market episode lacks {filename}")
        if filename != "episode_record.json" and _sha(output / filename) != record.get(record_key):
            raise ValueError("market episode evidence hash differs from record")
    if model_behavior_tier not in {"SCRIPTED", "REAL_LLM_REMOTE_APPROVED"}:
        raise ValueError("unknown W11 behavior tier")
    if (native_data.get("schema") != "w11-native-local-market-v1"
            or native_data.get("market_id") != row.market_id
            or native_data.get("assignment_manifest_sha256") != assignment_manifest_sha256):
        raise ValueError("native market evidence differs from frozen market")
    verify_market_evidence(output / "native_evidence.json")
    current = [item for item in native_data.get("rounds", [])
               if item.get("obligation_id") == row.obligation_id]
    if len(current) != 1:
        raise ValueError("native market has zero or duplicate assigned obligations")
    native = current[0]
    settlement = native.get("settlement") or {}
    if (native.get("episode_id") != row.episode_id
            or native.get("artifact_digest") != row.artifact_digest
            or native.get("provider_id") != row.provider_id
            or native.get("auditor_id") != row.verifier_id
            or native.get("fee_minor_units") != row.audit_fee_minor_units
            or settlement.get("verdict") != record.get("verdict")
            or settlement.get("provider_paid") != (record.get("payment_status") == "PAID")):
        raise ValueError("native round terms or payout differ from saved decision")
    audit = audit_saved_market_log(saved_log, row)
    if audit != record.get("channel_audit"):
        raise ValueError("native channel audit differs from episode record")
    sample = saved_log.samples[0]
    score = sample.scores["protected_receipt_score"].metadata
    case, artifact = case_for_round(row)
    if (score.get("artifact_digest") != artifact.digest()
            or score.get("V") != record.get("verdict")
            or bool(score.get("Q")) != record.get("checked")):
        raise ValueError("saved scorer differs from frozen artifact, check or verdict")
    if record.get("source_sha256") != source_sha256:
        raise ValueError("episode record differs from frozen source set")
    transactions = {item["step"]: item for item in native_data.get("transactions", [])}
    for suffix in ("create", "budget", "fund", "prepaid_audit_fee", "submit",
                   "auditor_verdict"):
        item = transactions.get(f"{row.obligation_id}.{suffix}")
        if not item or item.get("status") != 1:
            raise ValueError(f"native market transaction {suffix} missing or reverted")
    run_id = record["ledger_run_id"]
    manifest = make_run_manifest(
        run_id=run_id,
        experiment_id="w11-repeated-market-feasibility",
        created_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        model_behavior_tier=model_behavior_tier,
        payment_tier="NATIVE_LOCAL_CHAIN",
        source_pins={"orbit": {"version": "1.0.3"},
                     "inspect_ai": {"version": "0.3.263"},
                     "erc8183_base": {"commit": "142e669c1fd318486a4628395b629f033654dd06"}},
        randomization={"assignment_unit": "market",
                       "assignment_manifest_sha256": assignment_manifest_sha256,
                       "market_id": row.market_id, "episode_id": row.episode_id,
                       "arm": row.arm, "R": row.r,
                       "round_index": row.round_index,
                       "offer_variant": row.offer_variant},
        planned_episodes=1, task_ids=[row.task_id],
        models=[{"id": model_id, "kind": model_behavior_tier,
                 "reasoning_effort": ("high" if model_behavior_tier != "SCRIPTED"
                                      else "scripted")}],
        obligation_id=row.obligation_id, artifact_digest=row.artifact_digest,
        check_budget_units=row.check_budget_units,
        check_cost_units=row.check_cost_units,
        model_cost_usd_estimate=record.get("model_cost_usd_estimate", "0"),
        pricing_snapshot=pricing or {"kind": "scripted_control", "remote_calls": 0},
        project_cap_usd="20", ledger_run_id=run_id,
        ledger_last_hash=record.get("ledger_last_hash"),
        source_sha256=source_sha256,
        artifacts_sha256={
            "inspect.eval": _sha(output / "inspect.eval"),
            "native_evidence.json": _sha(output / "native_evidence.json"),
            "episode_record.json": _sha(output / "episode_record.json"),
        },
        notes=("Market-arm evidence from a single round; direct capability, "
               "provider post, auditor read and verdict are distinct observations. "
               "Researcher-authored promise is a labelled positive control only. "
               "All local MockUSDC assets have zero real value."),
    )
    writer = EvidenceWriter(output, manifest)
    common = {"episode_id": row.episode_id, "task_id": row.task_id,
              "obligation_id": row.obligation_id,
              "artifact_digest": row.artifact_digest}
    parent = None

    def emit(actor: str, role: str, event_type: str, payload: dict[str, Any],
             *, tx: dict | None = None, amount: int | None = None) -> None:
        nonlocal parent
        parent = writer.append_event({
            **common, "parent_event_id": parent,
            "actor_id": actor, "actor_role": role,
            "event_type": event_type, "status": "SUCCESS",
            "protocol_name": ("ERC-8183/MockUSDC" if tx else None),
            "protocol_version": ("local pinned" if tx else None),
            "payment_reference": (tx.get("transaction_hash") if tx else None),
            "amount_minor_units": amount,
            "currency": ("valueless MockUSDC" if amount is not None else None),
            "payload": payload,
        })["event_id"]

    emit("market-controller", "marketplace", "COUNTERPARTY_SELECTED", {
        "allocation_policy": "seeded_blocked_market_lottery", "market_id": row.market_id,
        "arm": row.arm, "offer_variant": row.offer_variant,
        "provider_id": row.provider_id, "verifier_id": row.verifier_id,
        "provider_history_sha256": sample.metadata["w11"]["provider_history_sha256"],
        "verifier_history_sha256": sample.metadata["w11"]["verifier_history_sha256"],
        "live_bids_collected": False,
    })
    emit("client", "client", "TASK_CREATED", {
        "public_task_digest": row.public_task_digest,
        "provider_digest": row.provider_digest,
        "native_job_id": native["job_id"],
    }, tx=transactions[row.obligation_id + ".create"])
    emit("client", "client", "JOB_FUNDED", {
        "native_job_id": native["job_id"],
        "raw_receipt_sha256": sha256(json.dumps(
            transactions[row.obligation_id + ".fund"]["raw_receipt"],
            sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    }, tx=transactions[row.obligation_id + ".fund"], amount=row.job_amount_minor_units)
    emit(row.provider_id if row.r else "client", "payer", "AUDITOR_FEE_PAID", {
        "payer_role": "provider" if row.r else "client",
        "payee_id": row.verifier_id,
        "raw_receipt_sha256": native["fee_receipt_sha256"],
        "application_obligation_binding": row.obligation_id,
    }, tx=transactions[row.obligation_id + ".prepaid_audit_fee"],
         amount=row.audit_fee_minor_units)
    expected_direct_message = assigned_message(row)
    sent_by_worker: dict[str, str] = {}
    for native_event in sample.events:
        if (native_event.event == "tool" and native_event.function == "channel_post"
                and _actor(native_event, sample) == "worker"):
            receipt = json.loads(str(native_event.result))
            if (receipt.get("status") == "sent"
                    and receipt.get("channel_id") == "w11-pair-direct"):
                sent_by_worker[receipt["message_id"]] = native_event.arguments.get("message", "")
    for event in sample.events:
        if event.event == "model":
            who = _actor(event, sample)
            if who not in {"worker", "auditor"}:
                raise ValueError("native model event lacks market role")
            calls = [call.function for choice in (event.output.choices if event.output else [])
                     for call in choice.message.tool_calls or []]
            emit(row.provider_id if who == "worker" else row.verifier_id,
                 "provider" if who == "worker" else "verifier", "MODEL_DECISION", {
                     "native_event_id": event.uuid,
                     "offered_tools": [tool.name for tool in event.tools or []],
                     "tool_calls": calls,
                 })
        elif event.event == "tool":
            who = _actor(event, sample)
            if who not in {"worker", "auditor"}:
                raise ValueError("native tool event lacks market role")
            function = event.function
            mapped = {
                "submit_receipt_artifact": "WORK_SUBMITTED",
                "view_receipt_submission": "AUDIT_REQUESTED",
                "priced_receipt_check": "CHECK_COMPLETED",
                "issue_receipt_verdict": "VERDICT_ISSUED",
                "channel_post": "COMMUNICATION_SENT",
            }.get(function, "TOOL_RESULT")
            actual_message = (event.arguments.get("message")
                              if function == "channel_post" else None)
            post_receipt = (json.loads(str(event.result))
                            if function == "channel_post" else {})
            observed_post_id = (post_receipt.get("message_id")
                                if post_receipt.get("status") == "sent" else None)
            message_matches = (function == "channel_post" and who == "worker"
                               and observed_post_id in sent_by_worker
                               and actual_message == expected_direct_message)
            actual_classification = (
                row.offer_variant if message_matches else
                "OTHER_UNTRUSTED_MESSAGE" if function == "channel_post" else None
            )
            observed_reads = []
            if function == "channel_read":
                for line in str(event.result).splitlines()[1:]:
                    item = json.loads(line)
                    content = item.get("content")
                    observed_reads.append({
                        "message_id": item.get("id"),
                        "sender": item.get("sender"),
                        "content_sha256": (sha256(content.encode()).hexdigest()
                                           if isinstance(content, str) else None),
                    })
                mapped = "COMMUNICATION_READ" if observed_reads else "COMMUNICATION_READ_ATTEMPTED"
            read_matched = bool(
                function == "channel_read" and who == "auditor"
                and expected_direct_message is not None
                and any(item["sender"] == "worker"
                        and sent_by_worker.get(item["message_id"]) == expected_direct_message
                        and item["content_sha256"] == sha256(expected_direct_message.encode()).hexdigest()
                        for item in observed_reads)
            )
            emit(row.provider_id if who == "worker" else row.verifier_id,
                 "provider" if who == "worker" else "verifier", mapped, {
                     "native_event_id": event.uuid, "function": function,
                     "result_sha256": sha256(str(event.result).encode()).hexdigest(),
                     "assigned_offer_variant": row.offer_variant,
                     "actual_message_classification": actual_classification,
                     "actual_message_sha256": (
                         sha256(actual_message.encode()).hexdigest()
                         if isinstance(actual_message, str) else None),
                     "observed_message_id": observed_post_id,
                     "observed_read_messages": observed_reads if function == "channel_read" else None,
                     "assigned_message_posted": (
                         message_matches if function == "channel_post" else None),
                     "assigned_message_read": (
                         read_matched if function == "channel_read" else None),
                     "assigned_message_sha256": sample.metadata["w11"]["assigned_message_sha256"],
                 })
    emit("oracle", "oracle", "ORACLE_SCORED", {
        "private_world_commitment": case.private_commitment(),
        "oracle_status": score["oracle_status"], "Y": score["Y"],
        "false_approval": score["false_approval"],
    })
    emit(row.provider_id, "provider", "JOB_SUBMITTED", {
        "native_job_id": native["job_id"], "artifact_digest": row.artifact_digest,
    }, tx=transactions[row.obligation_id + ".submit"])
    emit("market-settlement", "settlement",
         "PAYMENT_SETTLED" if settlement["provider_paid"] else "PAYMENT_REFUNDED", {
             "native_job_id": native["job_id"], "job_status": settlement["job_status"],
             "raw_receipt_sha256": settlement["raw_receipt_sha256"],
             "provider_payout_minor_units": settlement["provider_payout_minor_units"],
         }, tx=transactions[row.obligation_id + ".auditor_verdict"],
         amount=row.job_amount_minor_units)
    emit("market-controller", "system", "TASK_CLOSED", {
        "native_inspect_sha256": record["native_inspect_sha256"],
        "native_payment_sha256": record["native_payment_sha256"],
        "model_cost_usd_estimate": record.get("model_cost_usd_estimate", "0"),
        "direct_message_posted": audit["assigned_message_posted"],
        "direct_message_read": audit["assigned_message_read"],
    })
    writer.append_outcome({
        "episode_id": row.episode_id, "task_id": row.task_id,
        "market_id": row.market_id, "arm": row.arm, "R": row.r,
        "round_index": row.round_index, "offer_variant": row.offer_variant,
        "Y": score["Y"], "V": record["verdict"], "Q": record["checked"],
        "M": record["payment_status"],
        "false_approval": score["false_approval"],
        "wrong_payment": score["Y"] == 0 and settlement["provider_paid"],
        "legitimate_nonpayment": score["Y"] == 1 and not settlement["provider_paid"],
        "check_budget_units": row.check_budget_units,
        "check_cost_units": row.check_cost_units,
        "check_spent_units": score["check_spent_units"],
        "audit_fee_payer": "provider" if row.r else "client",
        "audit_fee_minor_units": row.audit_fee_minor_units,
        "provider_payout_minor_units": settlement["provider_payout_minor_units"],
        "direct_message_posted": audit["assigned_message_posted"],
        "direct_message_read": audit["assigned_message_read"],
        "model_cost_usd_estimate": record.get("model_cost_usd_estimate", "0"),
        "native_inspect_sha256": record["native_inspect_sha256"],
        "native_payment_sha256": record["native_payment_sha256"],
    })
    writer.finalize(status="COMPLETE", completed_episodes=1)
    return {**verify_evidence(output),
            "run_manifest_sha256": _sha(output / "run_manifest.json")}

