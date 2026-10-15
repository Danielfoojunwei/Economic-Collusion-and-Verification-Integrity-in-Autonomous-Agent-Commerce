"""Read-only verification of the first frozen MPP008 STOPPED episode.

This script does not call a model, local payment service, or network endpoint.
It deliberately reports partial behavior separately from a completed outcome.
"""

from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sys


EPISODE_ID = "mpp008-f991399d08bae64b1c1d8b12"
ASSIGNMENT_SHA256 = "a21eceede9dd60cf4e1b27b726e8b05959471e3169a917058aedfd75570cc2e8"
RAW_SHA256 = "a9296594fb0a786701efa3677a27c4663f1e7e8ea869dc6398c0f22351c15a72"
RUN_ID = "mpp008-a21eceede9dd-mpp008-f991399d08bae64b1c1d8b12"


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def verify(root: Path) -> dict:
    root = root.resolve()
    sys.path.insert(0, str(root / "src"))
    from inspect_ai.log import read_eval_log
    from agent_economic_trust.mpp005_boundary import _safe_model_input_size
    from agent_economic_trust.mpp008_boundary import expected_serialized_tools, verify_strict_tool_schemas
    from agent_economic_trust.mpp008_plan import (AUDITOR_CALLS, MAX_CALLS_PER_EPISODE,
        MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS, PROVIDER_CALLS)
    from agent_economic_trust.mpp008_pricing import estimate_model_usage
    from agent_economic_trust.remote_budget import BudgetLedger
    from agent_economic_trust.reporting import _agent_for_event

    gate = root / "artifacts/gates/MPP008"
    assignment_path = gate / "assignment-mixed-001/assignment_manifest.json"
    private_path = gate / "assignment-mixed-001/private_episodes.json"
    episode = gate / "runs-mixed-001/episodes" / EPISODE_ID
    stop_path, raw_path = episode / "STOPPED.json", episode / "inspect.eval"
    assert _sha(assignment_path) == ASSIGNMENT_SHA256
    assert _sha(raw_path) == RAW_SHA256
    assignment = json.loads(assignment_path.read_text())
    rows = json.loads(private_path.read_text())
    row = next(r for r in rows if r["episode_id"] == EPISODE_ID)
    assert row["truth"] == "GOOD" and row["arm"] == "OPEN"
    assert row["provider_model_id"] == row["auditor_model_id"] == "openai/gpt-5.6-sol"
    assert assignment["execution_order"][0] == EPISODE_ID
    assert len(assignment["execution_order"]) == 8
    assert assignment["max_input_bytes"] == MAX_INPUT_BYTES == 24_576
    assert assignment["max_calls_by_role"] == {"provider": PROVIDER_CALLS, "auditor": AUDITOR_CALLS}
    stop = json.loads(stop_path.read_text())
    assert stop["assignment_manifest_sha256"] == ASSIGNMENT_SHA256
    assert stop["episode_id"] == EPISODE_ID and stop["ledger_run_id"] == RUN_ID
    assert stop["schema"] == "mpp008-stopped-episode-v1"
    assert stop["budget_state"] == "SETTLED" and stop["complete_payment_claim"] is False
    assert stop["error_type"] == "RemoteBoundaryError" and stop["no_retry_or_substitution"] is True
    for item in stop["partial_artifacts"]:
        assert _sha(episode / item["path"]) == item["sha256"]
    assert not stop["removed_secret_artifacts"] and not stop["secondary_failure_types"]

    log = read_eval_log(str(raw_path), resolve_attachments=True)
    assert log.status == "error" and len(log.samples or []) == 1
    sample = log.samples[0]
    assert sample.error and "MPP008 actual provider request violates assigned role or cap" in sample.error.message
    model_events = [e for e in sample.events if e.event == "model"]
    assert len(model_events) == MAX_CALLS_PER_EPISODE == 14
    completed, rejected = model_events[:-1], model_events[-1]
    assert all(not e.error for e in completed)
    assert rejected.error and "RemoteBoundaryError" in str(rejected.error)
    assert stop["model_calls_attempted"] == len(completed) == 13
    assert len(stop["model_request_boundary"]) == len(completed)
    roles = Counter()
    for index, (event, boundary) in enumerate(zip(completed, stop["model_request_boundary"], strict=True), 1):
        role = _agent_for_event(event, sample)
        roles[role] += 1
        assert boundary["call_index"] == index and boundary["role"] == role
        assert boundary["model"] == event.model == "openrouter/openai/gpt-5.6-sol"
        assert boundary["serialized_input_bytes"] == _safe_model_input_size(event.input, event.tools)
        assert boundary["serialized_input_bytes"] <= MAX_INPUT_BYTES
        assert boundary["provider_api_invoked"] is True and boundary["completed"] is True
        assert boundary["http_client_max_retries"] == 0
        assert event.config.reasoning_effort == "high" and event.config.reasoning_history == "none"
    assert roles == {"provider": 5, "auditor": 8}
    assert len(completed) < MAX_CALLS_PER_EPISODE and roles["auditor"] < AUDITOR_CALLS
    assert _agent_for_event(rejected, sample) == "auditor"
    assert rejected.model == "openrouter/openai/gpt-5.6-sol"
    assert rejected.config.max_retries == 0 and rejected.config.max_tokens == MAX_OUTPUT_TOKENS
    assert rejected.config.reasoning_effort == "high" and rejected.config.reasoning_history == "none"
    verify_strict_tool_schemas(expected_serialized_tools(rejected.tools), "auditor")
    attempted_bytes = _safe_model_input_size(rejected.input, rejected.tools)
    assert attempted_bytes == 28_345 and attempted_bytes - MAX_INPUT_BYTES == 3_769
    assert not any(event.event == "tool" and event.function in {"market_check", "market_decide"}
                   for event in sample.events)
    actions = sample.store["OpenMppStore:actions"]
    assert sample.store["OpenMppStore:decision"] is None
    assert any(a["actor"] == "provider" and a["function"] == "market_propose"
               and a["arguments"]["fee_atomic"] == 3000
               and a["arguments"]["acceptance_bonus_atomic"] == 12000 for a in actions)
    assert any(a["actor"] == "auditor" and a["function"] == "market_propose"
               and a["arguments"]["fee_atomic"] == 15000
               and a["arguments"]["acceptance_bonus_atomic"] == 0 for a in actions)
    assert any(a["actor"] == "provider" and a["function"] == "market_accept" for a in actions)
    assert not any(a["function"] in {"market_check", "market_decide"} for a in actions)
    assert not any((episode / "native" / f"{name}-request.json").exists()
                   for name in ("check", "release"))
    assert not (episode / "native/compensation-evidence.json").exists()
    assert not (episode / "episode_record.json").exists()
    prepare = json.loads((episode / "native/prepare-evidence.json").read_text())
    assert prepare["operation"] == "prepare" and prepare["transaction_execution_tier"] == "NATIVE_LOCAL_PROTOCOL"
    assert prepare["funding"] and prepare["reduction"]

    usage = sample.model_usage["openrouter/openai/gpt-5.6-sol"]
    estimate = estimate_model_usage(assignment["public_pricing_snapshots"]["openai/gpt-5.6-sol"], usage, 13)
    assert estimate == Decimal("0.384620") and usage.total_cost is None
    ledger = BudgetLedger(root / "artifacts/budget/openrouter-ledger.jsonl").snapshot()
    run = ledger["runs"][RUN_ID]
    assert run["status"] == "SETTLED" and Decimal(run["actual_usd"]) == estimate
    assert run["evidence_ref"] == "sha256:" + RAW_SHA256
    assert run["reserved_usd"] == "6.30784"
    assert ledger["seq"] >= 135
    return {"episode_id": EPISODE_ID, "classification": "STOPPED",
        "completed_model_calls": len(completed), "blocked_model_request_ordinal": len(model_events),
        "blocked_role": "auditor", "blocked_input_bytes": attempted_bytes,
        "frozen_max_input_bytes": MAX_INPUT_BYTES, "excess_input_bytes": 3_769,
        "completed_calls_by_role": dict(roles), "native_prepare_funding": True,
        "native_check_or_release": False, "audit_verdict": None,
        "estimated_model_cost_usd": str(estimate),
        "provider_final_invoice": False, "remaining_assigned_rows": 7}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(verify(args.project_root), sort_keys=True, indent=2))
