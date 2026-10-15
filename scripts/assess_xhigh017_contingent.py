#!/usr/bin/env python3
"""Provisional XHIGH017 first-stop billing assessment; retain the entire hold.

The default command only replays archived evidence. ``--apply`` is a one-time
canonical-ledger operation after an independent review with an explicitly
supplied SHA-256. The failed local validator hid the provider result and bill.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

from inspect_ai.log import read_eval_log

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from agent_economic_trust.remote_budget import BudgetLedger, read_ledger  # noqa: E402
from scripts.collect_x402_live012 import verify_stopped_model_and_account  # noqa: E402

CANONICAL_ROOT = Path(
    "/workspace/Economic-Collusion-and-Verification-Integrity-in-Autonomous-Agent-Commerce"
)
EPISODE_ID = "xhigh017-0a63961c0d306890326609f6"
RUN_ID = "xhigh017-a0f79e6ba7de-xhigh017-0a63961c0d306890326609f6"
GATE = ROOT / "artifacts/gates/ERC8183_XHIGH017"
EPISODE = GATE / "runs-001/episodes" / EPISODE_ID
FORENSICS = GATE / "independent-first-stop-forensics-001.json"
ASSESSMENT = ROOT / "artifacts/budget/xhigh017-first-stop-contingent-001"
PRESTATE = ASSESSMENT / "openrouter-ledger.prestate.jsonl"
EVIDENCE = ASSESSMENT / "evidence.json"
REVIEW = ASSESSMENT / "independent-review.json"
CANONICAL_LEDGER = ROOT / "artifacts/budget/openrouter-ledger.jsonl"
HOLD_USD = Decimal("4.718592")
LAST_HASH = "f0e592b73cfb4091e8459e637365352ce49fb444f5ab1a2d40d03f355e0b1fcf"
EXPECTED = {
    "assignment": "a0f79e6ba7de1c1b0bee28e39e9d70165405f325d9a52a9c0b2f432708b2237b",
    "freeze": "dc8d700b72279383417bb526de62aa6eea6c09d3d58deb98f465aa01add8969a",
    "collection": "eefd7c61b9b8667a3923a8979c78226e8433488f9a032e537b11f418633e95ec",
    "stopped": "20628ac8c11a1e658728ba37b04d5ae3d9ff22c99c94da7be5418b5bb9f1097d",
    "inspect": "3c83426dfa2a27f60ab2851db6ed8cc60f59020b8cc36fb8b3495d7b6f587778",
    "native": "5b3a470f2f490f67837a27ca60cd789877d33fe03d5d6093943629d569565e17",
    "forensics": "66b0c983ebc587380fcaaad8ce8f16a4f9b169684981385b3df0512751780e17",
    "boundary_source": "ad8b2ac57d98d0cb27345d99ee6917a9d87770d649d896ef1e7df6f27c1d5f62",
    "remote_source": "d089f7f03cc088d6e00be860c87cd3db9116191497311e3fef811f4f11b325c9",
    "ledger": "22d8e15df568f151edb0589715ec5489ce89f2d9c01d5917fa4dbb6503b36bd9",
    "anchor": "0ffd24b300c70d21fba155cbadbd76d0a36622852b2226d6cb826786a6871219",
}
ARTIFACTS = {
    "assignment": GATE / "assignment-001/assignment_manifest.json",
    "freeze": GATE / "first-freeze.lock.json",
    "collection": GATE / "collection-001-after-first-stop.json",
    "stopped": EPISODE / "STOPPED.json",
    "inspect": EPISODE / "inspect.eval",
    "native": EPISODE / "erc8183/native-partial.json",
    "forensics": FORENSICS,
    "boundary_source": ROOT / "src/agent_economic_trust/xhigh017_boundary.py",
    "remote_source": ROOT / "src/agent_economic_trust/xhigh017_remote.py",
    "ledger": PRESTATE,
    "anchor": PRESTATE.with_name(PRESTATE.name + ".anchor"),
}
EVIDENCE_SHA256 = "53bdf0afe52a99f0ee18ab48772fac41b1a7054cb3b8f34386d392205c9ca009"


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def pinned(label: str) -> bytes:
    path = ARTIFACTS[label]
    if path.is_symlink() or digest(path) != EXPECTED[label]:
        raise ValueError(f"XHIGH017 frozen {label} SHA-256 differs")
    return path.read_bytes()


def serialized(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def assess() -> dict:
    """Replay the frozen STOPPED row and hash-anchored ledger without network."""
    docs = {name: json.loads(pinned(name)) for name in (
        "assignment", "freeze", "collection", "stopped", "native", "forensics")}
    pinned("inspect")
    pinned("boundary_source")
    pinned("remote_source")
    pinned("ledger")
    pinned("anchor")
    assignment, freeze, collection, stop, native, forensic = (
        docs[name] for name in ("assignment", "freeze", "collection", "stopped",
                              "native", "forensics"))
    before = read_ledger(PRESTATE)
    reviewed = forensic.get("reviewed_sha256", {})
    for label, name in (
        ("assignment", "artifacts/gates/ERC8183_XHIGH017/assignment-001/assignment_manifest.json"),
        ("freeze", "artifacts/gates/ERC8183_XHIGH017/first-freeze.lock.json"),
        ("collection", "artifacts/gates/ERC8183_XHIGH017/collection-001-after-first-stop.json"),
        ("stopped", f"artifacts/gates/ERC8183_XHIGH017/runs-001/episodes/{EPISODE_ID}/STOPPED.json"),
        ("inspect", f"artifacts/gates/ERC8183_XHIGH017/runs-001/episodes/{EPISODE_ID}/inspect.eval"),
        ("native", f"artifacts/gates/ERC8183_XHIGH017/runs-001/episodes/{EPISODE_ID}/erc8183/native-partial.json"),
        ("ledger", "artifacts/budget/openrouter-ledger.jsonl"),
        ("anchor", "artifacts/budget/openrouter-ledger.jsonl.anchor"),
        ("boundary_source", "src/agent_economic_trust/xhigh017_boundary.py"),
        ("remote_source", "src/agent_economic_trust/xhigh017_remote.py"),
    ):
        if reviewed.get(name) != EXPECTED[label]:
            raise ValueError(f"independent forensics {label} binding differs")
    rows = collection.get("rows")
    if (freeze.get("assignment_manifest_sha256") != EXPECTED["assignment"]
            or collection.get("assignment_manifest_sha256") != EXPECTED["assignment"]
            or stop.get("assignment_manifest_sha256") != EXPECTED["assignment"]
            or assignment.get("auditor_efforts_in_seed_order") != ["high", "xhigh"]
            or assignment.get("execution_order") != [EPISODE_ID,
                "xhigh017-233069417b32cf795127733a"]
            or not isinstance(rows, list) or len(rows) != 2
            or [r.get("status") for r in rows] != ["STOPPED", "PENDING"]
            or collection.get("completed_episodes") != 0
            or collection.get("stopped_episodes") != 1
            or collection.get("pending_episodes") != 1
            or collection.get("shared_ledger_seq") != 216
            or rows[0].get("episode_id") != EPISODE_ID
            or forensic.get("decision") != "TECHNICAL_STOP_NO_XHIGH_COMPARISON"
            or forensic.get("assignment", {}).get("no_reroll_or_substitution") is not True
            or forensic.get("observations", {}).get("no_verifiable_live_collusion_outcome") is not True):
        raise ValueError("frozen XHIGH017 denominator or independent review differs")
    boundary = stop.get("model_request_boundary")
    model = stop.get("stopped_model_events", {})
    account = stop.get("stopped_account_usage", {})
    if (stop.get("budget_state") != "UNKNOWN"
            or stop.get("ledger_status_at_stop") != "UNKNOWN"
            or stop.get("ledger_run_id") != RUN_ID
            or stop.get("episode_id") != EPISODE_ID
            or stop.get("no_retry_or_substitution") is not True
            or stop.get("complete_native_claim") is not False
            or not isinstance(boundary, list) or len(boundary) != 1
            or boundary[0].get("provider_api_invoked") is not True
            or boundary[0].get("completed") is not False
            or boundary[0].get("role") != "provider"
            or boundary[0].get("model") != "openrouter/anthropic/claude-sonnet-5.5"
            or boundary[0].get("requested_reasoning_effort") != "high"
            or boundary[0].get("http_client_max_retries") != 0
            or model.get("guarded_api_invocations") != 1
            or model.get("guard_completed_returns") != 0
            or model.get("inspect_model_events") != 1
            or model.get("inspect_successful_model_events") != 0
            or model.get("inspect_failed_model_events") != 1
            or model.get("provider_billing_for_failed_events") != "UNVERIFIED"
            or model.get("guard_inspect_counts_agree") is not True
            or account.get("scope") != "whole OpenRouter account; not a per-call receipt"
            or account.get("failed_call_billing") != "UNVERIFIED"
            or Decimal(account.get("before_usd", "-1")) != Decimal("3.4305802")
            or Decimal(account.get("after_usd", "-1")) != Decimal("3.4305802")
            or Decimal(account.get("aggregate_delta_usd", "-1")) != 0):
        raise ValueError("STOPPED model/account observations differ")
    verify_stopped_model_and_account(stop, EPISODE)
    log = read_eval_log(str(EPISODE / "inspect.eval"))
    if log.status != "error" or len(log.samples or []) != 1:
        raise ValueError("Inspect stopped sample differs")
    sample = log.samples[0]
    events = [(i, e) for i, e in enumerate(sample.events or []) if e.event == "model"]
    if (len(events) != 1 or events[0][1].model != boundary[0]["model"]
            or "XHIGH017 model output lacks a single choice" not in str(events[0][1].error)
            or events[0][1].output is None
            or events[0][1].output.usage is not None
            or sample.model_usage):
        raise ValueError("Inspect failed event or no-usage observation differs")
    if (native.get("native_terminal_claim") is not False
            or native.get("verdict") is not None
            or native.get("final") is not None
            or native.get("settle_receipt") is not None
            or native.get("check_receipt") is not None
            or native.get("job_id") != 1
            or native.get("funded", {}).get("balances_minor_units", {}).get("escrow") != 20_000_000
            or native.get("funded", {}).get("balances_minor_units", {}).get("provider") != 0
            or [x.get("step") for x in native.get("transactions", [])][-1:] != ["job.submit"]):
        raise ValueError("local ERC-8183 nonterminal state differs")
    billing = forensic.get("billing", {})
    if (before.get("seq") != 216 or before.get("last_hash") != LAST_HASH
            or before.get("cap_usd") != "50"
            or before.get("settled_spent_usd") != "9.814298"
            or before.get("reserved_usd") != "23.1055"
            or before.get("available_usd") != "17.080202"
            or before.get("blocked") is not True
            or before.get("unknown_run_ids") != [RUN_ID]
            or before.get("runs", {}).get(RUN_ID, {}).get("status") != "UNKNOWN"
            or Decimal(before["runs"][RUN_ID].get("reserved_usd", "-1")) != HOLD_USD
            or billing.get("full_reserved_usd") != str(HOLD_USD)
            or billing.get("per_call_provider_charge") != "UNVERIFIED"
            or billing.get("aggregate_delta_is_per_call_bill") is not False
            or billing.get("transition_applied_by_this_review") is not False):
        raise ValueError("full-hold USD50 ledger prestate differs")
    return {
        "schema": "xhigh017-first-stop-provisional-billing-v1",
        "result": "PROVISIONAL_HOLD_RETAINED_FINAL_CHARGE_UNKNOWN",
        "run_id": RUN_ID, "episode_id": EPISODE_ID,
        "frozen_artifacts_sha256": EXPECTED,
        "inspect_sample_uuid": sample.uuid,
        "inspect_model_event_indices": [events[0][0]],
        "guarded_provider_api_invocations": 1,
        "completed_model_returns": 0,
        "auditor_api_invocations": 0,
        "failed_local_boundary_class": "FROZEN_API_RESULT_TUPLE_SHAPE_MISMATCH",
        "underlying_provider_http_status": None,
        "underlying_provider_model_choice_count": None,
        "provider_request_or_billing_id": None,
        "attributable_final_provider_bill_usd": None,
        "account_usage_before_usd": account["before_usd"],
        "account_usage_after_usd": account["after_usd"],
        "whole_account_delta_usd": str(Decimal(account["aggregate_delta_usd"])),
        "whole_account_delta_is_per_call_bill": False,
        "ledger_prestate": {key: before[key] for key in (
            "seq", "last_hash", "cap_usd", "settled_spent_usd", "reserved_usd",
            "available_usd", "blocked", "unknown_run_ids")},
        "retained_run_reservation_usd": str(HOLD_USD),
        "intended_transition": "UNKNOWN_TO_CONTINGENT_WITH_FULL_HOLD",
        "frozen_row_disposition": "ZERO_COMPLETE_ONE_STOPPED_ONE_PENDING_NO_RETRY",
        "native_local_state": "FUNDED_SUBMITTED_NO_TERMINAL_VERDICT_OR_PAYOUT",
        "live_collusion_effect_estimate": None,
        "final_settlement_requires": "attributable provider final billing for the guarded call",
        "paid_model_calls_by_assessment": 0,
        "ledger_mutations_by_assessment": 0,
    }


def validate_saved_evidence() -> dict:
    result = assess()
    raw = serialized(result)
    if (not re.fullmatch(r"[0-9a-f]{64}", EVIDENCE_SHA256)
            or sha256(raw).hexdigest() != EVIDENCE_SHA256
            or EVIDENCE.is_symlink() or EVIDENCE.read_bytes() != raw):
        raise ValueError("reviewed provisional evidence digest or contents differ")
    return result


def validate_independent_review(path: Path, expected_sha256: str) -> dict:
    if (not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
            or path.is_symlink() or digest(path) != expected_sha256):
        raise ValueError("separately supplied independent review SHA-256 differs")
    review = json.loads(path.read_text())
    hashes = review.get("reviewed_artifacts_sha256", {})
    prestate = review.get("canonical_ledger_prestate", {})
    if (review.get("schema") != "xhigh017-provisional-billing-independent-review-v1"
            or review.get("decision") != "GO_FOR_ONE_CANONICAL_UNKNOWN_TO_CONTINGENT_TRANSITION"
            or review.get("reviewer_id") in {None, "", "/root/xhigh017_billing_assessment"}
            or hashes.get("scripts/assess_xhigh017_contingent.py") != digest(Path(__file__))
            or hashes.get("artifacts/budget/xhigh017-first-stop-contingent-001/evidence.json") != EVIDENCE_SHA256
            or hashes.get("artifacts/budget/xhigh017-first-stop-contingent-001/openrouter-ledger.prestate.jsonl") != EXPECTED["ledger"]
            or hashes.get("artifacts/budget/xhigh017-first-stop-contingent-001/openrouter-ledger.prestate.jsonl.anchor") != EXPECTED["anchor"]
            or prestate.get("seq") != 216 or prestate.get("last_hash") != LAST_HASH
            or prestate.get("cap_usd") != "50"
            or prestate.get("unknown_run_ids") != [RUN_ID]
            or review.get("retained_reservation_usd") != str(HOLD_USD)
            or review.get("attributable_final_provider_bill_usd", "not-set") is not None
            or review.get("no_paid_calls_or_ledger_mutations") is not True):
        raise ValueError("independent full-hold billing review differs")
    return review


def transition(ledger_path: Path, review_path: Path, review_sha256: str) -> dict:
    """Guard a one-time optimistic-concurrency transition on a supplied ledger."""
    validate_saved_evidence()
    validate_independent_review(review_path, review_sha256)
    if (digest(ledger_path) != EXPECTED["ledger"]
            or digest(ledger_path.with_name(ledger_path.name + ".anchor")) != EXPECTED["anchor"]):
        raise ValueError("ledger changed since independent review")
    before = read_ledger(ledger_path)
    if before["seq"] != 216 or before["last_hash"] != LAST_HASH:
        raise ValueError("ledger no longer has the reviewed UNKNOWN prestate")
    after = BudgetLedger(ledger_path).mark_contingent(
        RUN_ID, "sha256:" + EVIDENCE_SHA256,
        expected_seq=before["seq"], expected_last_hash=before["last_hash"])
    run = after["runs"][RUN_ID]
    if (after["seq"] != 217 or after["blocked"] is not False
            or after["unknown_run_ids"]
            or after["cap_usd"] != before["cap_usd"]
            or after["settled_spent_usd"] != before["settled_spent_usd"]
            or after["reserved_usd"] != before["reserved_usd"]
            or after["available_usd"] != before["available_usd"]
            or run["status"] != "CONTINGENT"
            or Decimal(run["reserved_usd"]) != HOLD_USD
            or run.get("actual_usd") is not None
            or run["contingent_evidence_ref"] != "sha256:" + EVIDENCE_SHA256):
        raise ValueError("contingent transition failed to retain full hold")
    return {"applied": True, "run_id": RUN_ID, "new_ledger_seq": after["seq"],
            "status": run["status"], "retained_reservation_usd": str(HOLD_USD),
            "actual_final_charge_usd": None,
            "evidence_ref": "sha256:" + EVIDENCE_SHA256,
            "frozen_row_disposition": "ZERO_COMPLETE_ONE_STOPPED_ONE_PENDING_NO_RETRY"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="one-time canonical ledger transition; default is read-only")
    parser.add_argument("--review-sha256",
                        help="independently supplied digest of the separate review")
    args = parser.parse_args()
    if args.apply:
        if ROOT.resolve() != CANONICAL_ROOT.resolve():
            raise ValueError("--apply requires the canonical shared-ledger checkout")
        if args.review_sha256 is None:
            raise ValueError("--apply requires a separately supplied independent review SHA-256")
        result = transition(CANONICAL_LEDGER, REVIEW, args.review_sha256)
    else:
        if args.review_sha256 is not None:
            raise ValueError("--review-sha256 requires --apply")
        result = validate_saved_evidence()
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
