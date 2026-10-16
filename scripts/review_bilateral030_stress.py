"""Independent read-only replay of one completed scripted BILATERAL030 block.

This replays saved public funding, native receipts and Inspect logs offline.
It does not query a stopped chain, call hosted models or change the budget ledger.
Run with assertions enabled in the pinned ORBIT Python environment.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sys

from inspect_ai.log import read_eval_log

from agent_economic_trust.bilateral030_funding_verifier import verify_funding_file
from agent_economic_trust.bilateral030_native_verifier import verify_file
from agent_economic_trust.bilateral030_plan import canonical
from agent_economic_trust.bilateral030_scripted_stress import (
    _source_snapshot, make_scripts,
)
from agent_economic_trust.bilateral030_trace_verifier import verify_saved_inspect_trace


if not __debug__:
    raise RuntimeError("BILATERAL030 replay requires Python assertions enabled")
if len(sys.argv) != 2:
    raise SystemExit("usage: review_bilateral030_stress.py STRESS_ROOT")

root = Path(sys.argv[1]).resolve()
scripts = make_scripts()
plan_path = root / "script-plan.json"
index_path = root / "stress-index.json"
plan = json.loads(plan_path.read_text())
index = json.loads(index_path.read_text())
assert plan["scientific_result_row"] is False
assert plan["model_behavior_tier"] == "SCRIPTED_SIMULATION"
assert index["scientific_result_row"] is False
assert index["model_behavior_tier"] == "SCRIPTED_SIMULATION"
assert index["status"] == "SCRIPTED_INFRASTRUCTURE_REPLAYED"
assert index["planned_rows"] == index["completed_rows"] == len(scripts) == 30
assert index["script_plan_sha256"] == sha256(plan_path.read_bytes()).hexdigest()
assert index["completed_episodes"] == [s.row.episode_id for s in scripts]
assert not (root / "failure.json").exists()
assert len(plan["source_sha256"]) == 14
assert plan["source_sha256"] == index["source_sha256"] == _source_snapshot()
assert plan["rows"] == [
    {"assignment": asdict(s.row), "scripted_note": s.note,
     "scripted_paid_check": s.paid_check, "scripted_decision": s.decision}
    for s in scripts
]

counts = Counter()
for number, script in enumerate(scripts, 1):
    row = script.row
    episode_dir = root / row.episode_id
    summary_path = episode_dir / "scripted-row-summary.json"
    summary = json.loads(summary_path.read_text())
    assert summary["status"] == "SCRIPTED_INFRASTRUCTURE_REPLAYED"
    assert summary["scientific_result_row"] is False
    assert summary["model_behavior_tier"] == "SCRIPTED_SIMULATION"
    assert summary["payment_tier"] == "NATIVE_LOCAL_PROTOCOL"
    assert summary["episode_id"] == row.episode_id
    assert summary["group"] == row.group and summary["truth"] == row.truth
    assert summary["contact"] == row.contact
    assert summary["scripted_paid_check"] is script.paid_check
    assert summary["scripted_decision"] == script.decision
    assert summary["scripted_note"] == script.note
    assert summary["assigned_bonus_minor"] == row.accept_bonus_minor
    assert summary["assigned_model_ids_unexecuted"] == [
        row.provider_model_id, row.auditor_model_id]
    assert summary["actual_model_routes"] == [
        "mockllm/bilateral030-provider-transport",
        "mockllm/bilateral030-auditor-transport"]
    assert summary["funding_pre_view_live_confirmed_and_exposed_to_mock_roles"] is True
    assert summary["model_view_independently_verified"] is True
    assert summary["chain_history_authenticated_after_stop"] is False

    for name, item in summary["artifacts"].items():
        path = episode_dir / item["relative_path"]
        assert path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(episode_dir.resolve()), name
        assert sha256(path.read_bytes()).hexdigest() == item["sha256"], name

    archive_path = episode_dir / "pre-view-funding.json"
    archive = json.loads(archive_path.read_text())
    prefix = archive["public_prefix"]
    public_assignment = {
        "episode_id": row.episode_id,
        "obligation_id": row.obligation_id,
        "provider_model_id": row.provider_model_id,
        "auditor_model_id": row.auditor_model_id,
        "assigned_bonus_minor": row.accept_bonus_minor,
    }
    assert archive["public_assignment"] == public_assignment
    funding = verify_funding_file(archive_path, public_assignment)
    saved_funding = json.loads((episode_dir / "pre-view-funding-replay.json").read_text())
    assert funding["status"] == "FUNDING_ARCHIVE_REPLAYED"
    assert saved_funding["status"] == "FUNDING_LIVE_CONFIRMED"
    assert saved_funding["read_only_rpc_source"] == "loopback"
    assert saved_funding["live_chain_checked"] is True
    for key, value in funding.items():
        if key not in {"status", "read_only_rpc_source", "live_chain_checked"}:
            assert saved_funding[key] == value, (row.episode_id, key)

    proof = {
        "schema": "bilateral030-live-funding-proof-v1",
        "status": saved_funding["status"],
        "episode_id": row.episode_id,
        "obligation_id": row.obligation_id,
        "job_id": prefix["job_id"],
        "report_digest": prefix["report_digest"],
        "bonus_amount_minor": row.accept_bonus_minor,
        "bonus_trigger": prefix["bonus_trigger"],
        "hook_address": prefix["hook_address"],
        "job_funding_tx_hash": prefix["job_funding_tx_hash"],
        "job_funding_receipt_sha256": saved_funding["job_funding_receipt_sha256"],
        "bonus_funding_tx_hash": prefix["bonus_funding_tx_hash"],
        "bonus_funding_receipt_sha256": saved_funding["bonus_funding_receipt_sha256"],
        "public_prefix_sha256": saved_funding["public_prefix_sha256"],
        "archive_sha256": saved_funding["archive_sha256"],
        "verifier_source_sha256": saved_funding["verifier_source_sha256"],
        "live_chain_checked": True,
        "read_only_rpc_source": "loopback",
        "model_view_independently_verified": False,
    }

    log_path = episode_dir / summary["artifacts"]["inspect_log"]["relative_path"]
    log = read_eval_log(log_path, resolve_attachments=True)
    sample = log.samples[0]
    assert json.loads(sample.input)["funding_attestation"] == proof
    trace = verify_saved_inspect_trace(log_path, row, prefix, trusted_public_proof=proof)
    native = verify_file(episode_dir / "native-evidence.json", row)
    assert trace == json.loads((episode_dir / "inspect-replay.json").read_text())
    assert native == json.loads((episode_dir / "native-replay.json").read_text())
    assert trace["funding_attestation_exposed_both_roles"] is True
    assert trace["funding_attestation_in_auditor_inbox"] is True
    assert trace["funding_attestation_sha256"] == sha256(canonical(proof)).hexdigest()
    assert trace["paid_check_requested"] is script.paid_check
    assert trace["early_decision"] == script.decision
    assert trace["provider_note_text"] == script.note
    assert trace["provider_note_exposed_to_auditor"] is (row.contact == "CHANNEL")
    assert native["assigned_bonus_minor"] == row.accept_bonus_minor
    assert native["job_funding_tx_hash"] == saved_funding["job_funding_tx_hash"]
    assert native["bonus_funding_tx_hash"] == saved_funding["bonus_funding_tx_hash"]
    assert native["claim_tx_hash"] == trace["claim_tx_hash_controller_claim"]
    assert native["check_tx_hash"] == trace["check_tx_hash_controller_claim"]
    assert native["first_decision_tx_hash"] == trace["first_decision_tx_hash_controller_claim"]

    model_inputs = json.loads((episode_dir / "model-inputs.json").read_text())
    model_events = [event for event in sample.events if event.event == "model"]
    assert len(model_inputs) == len(model_events) in {4, 5}
    for record, event in zip(model_inputs, model_events, strict=True):
        assert record["messages"] == [message.model_dump(mode="json") for message in event.input]
        assert json.loads(event.input[1].text)["funding_attestation"] == proof
    assert summary["first_bonus_status"] == (
        "RELEASED" if row.accept_bonus_minor and script.decision == "APPROVE" else
        "REFUNDED" if row.accept_bonus_minor else "ABSENT")
    assert summary["first_provider_paid_minor"] == native["first_provider_paid_minor"]
    assert summary["first_bonus_to_evaluator_minor"] == native["first_bonus_to_evaluator_minor"]
    raw_native = json.loads((episode_dir / "native-evidence.json").read_text())
    assert summary["final_status"] == raw_native["final_receipt"]["status"]
    counts[(row.group, row.truth, row.accept_bonus_minor, script.paid_check,
            script.decision)] += 1
    print(f"reviewed {number}/30 {row.episode_id} {row.group} {script.decision}", flush=True)

assert dict(index["condition_counts"]) == dict(Counter(s.row.group for s in scripts))
assert dict(index["direction_counts"]) == dict(Counter(
    "sol_provider_sonnet_auditor" if s.row.provider_model_id.endswith("sol")
    else "sonnet_provider_sol_auditor" for s in scripts))
assert index["funding_live_confirmed_rows"] == 30
assert index["model_proof_view_replayed_rows"] == 30
assert index["native_replayed_rows"] == 30
assert index["inspect_replayed_rows"] == 30
print("PASS all 30 raw funding, native, Inspect and model-input replays")
print("scenario counts:", json.dumps({str(key): count for key, count in counts.items()}, sort_keys=True))
