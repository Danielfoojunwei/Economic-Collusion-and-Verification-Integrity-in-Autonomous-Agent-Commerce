#!/usr/bin/env python3
"""Offline FEE014 row-2 billing assessment; --apply retains its entire hold.

The assessment is provisional. Four returned generations have priced Inspect
usage, but neither they nor the fifth HTTP 400 have attributable final billing.
The default command reads only. --apply is a one-time ledger transition and
cannot be run from an isolated worktree.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sys

from inspect_ai.log import read_eval_log

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agent_economic_trust.mpp008_pricing import estimate_model_usage  # noqa: E402
from agent_economic_trust.remote_budget import BudgetLedger, read_ledger  # noqa: E402

CANONICAL_ROOT = Path(
    "/workspace/Economic-Collusion-and-Verification-Integrity-in-Autonomous-Agent-Commerce"
)
RUN_ID = "fee014-d6409ff93bcb-fee014-deb758472e05bb8622e9a1d6"
EPISODE_ID = "fee014-deb758472e05bb8622e9a1d6"
GATE = ROOT / "artifacts/gates/ERC8183_FEE014"
EPISODE = GATE / "runs-001/episodes" / EPISODE_ID
ASSESSMENT_DIR = ROOT / "artifacts/budget/fee014-first-stop-contingent-001"
PRESTATE = ASSESSMENT_DIR / "openrouter-ledger.prestate.jsonl"
CANONICAL_LEDGER = ROOT / "artifacts/budget/openrouter-ledger.jsonl"
EVIDENCE = ASSESSMENT_DIR / "evidence.json"
EVIDENCE_SHA256 = "22ca35d7dabb6d8ab87ecb2410c2f2f84a1ce22cc48eb18a7f703aa60c08d155"
EXPECTED = {
    "assignment": "d6409ff93bcbd1332aba4ad90b19953c045e9a3136383ea6fa30fe76ece3bfed",
    "freeze": "acdb7050d3dae0bdfd341ffdde22d20c86ff8c939fd8ced470f1ecf766eb4cbf",
    "collection": "e929867f0e327bba854be8a53d8949ee097a1677adda4e7eb96f98d9ce38444f",
    "stopped": "f65fae3085a8b7cfc26da2eeb3945a982f93cdb4a770601fc3fac6c833051864",
    "inspect": "a7970238ee8f78c3a41ef0c8fae836638f10986fb1cb2ad92e9f3eb97faa2838",
    "native": "db2930e0d8240973de07f96dde9799cd23a19838d65b819c699be06384c656f8",
    "independent_review": "3ab4ad292c0021124bc396c70400731100e866aa4749c667c2a9c1850b8aaa38",
    "ledger": "62bd28a529e6cc003ad4094c13925cbe3c1c717f55f470bd5331ef94b987b8b2",
    "anchor": "a5f56167c710258f64531377b3087a3999a3b670b164358d48f5dd64412cbb0b",
    "owner_request_csv": "f1e30259ab4c3a22576ee79906fc7d61ffff4708f689d6b6b2a9b3620d576372",
    "owner_usage_csv": "900a5135005e16e5aee31eb2d6f0cd96da714e6ddba47cca898323310377fdc3",
}
LAST_HASH = "a26c433d9a01cfcb2f06297b15d77b1c8eecc78e2f21a2f13a759db11962712c"
HOLD_USD = Decimal("4.292608")
SUCCESS_ESTIMATE_USD = Decimal("0.036636")


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def pinned(path: Path, label: str) -> bytes:
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != EXPECTED[label]:
        raise ValueError(f"frozen {label} SHA-256 differs")
    return raw


def serialized(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def assess() -> dict:
    """Replay frozen evidence and an archived hash-anchored ledger, no network."""
    manifest = json.loads(pinned(GATE / "assignment-001/assignment_manifest.json", "assignment"))
    freeze = json.loads(pinned(GATE / "first-freeze.lock.json", "freeze"))
    collection = json.loads(pinned(GATE / "collection-002-after-first-stop.json", "collection"))
    stopped = json.loads(pinned(EPISODE / "STOPPED.json", "stopped"))
    pinned(EPISODE / "inspect.eval", "inspect")
    native = json.loads(pinned(EPISODE / "erc8183/native-partial.json", "native"))
    review = json.loads(pinned(
        GATE / "forensics-first-stop-001/report.json", "independent_review"))
    pinned(PRESTATE, "ledger")
    pinned(PRESTATE.with_name(PRESTATE.name + ".anchor"), "anchor")
    before = read_ledger(PRESTATE)
    exports = {}
    for name, filename in (
        ("owner_request_csv", "openrouter-request-count-2026-10-15-13h.csv"),
        ("owner_usage_csv", "openrouter-total-usage-2026-10-15-13h.csv"),
    ):
        raw = pinned(ROOT / "artifacts/billing" / filename, name)
        rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
        hours = {r["date__hour"] for r in rows}
        if not rows or max(hours) != "2026-10-15 13:00:00":
            raise ValueError("owner CSV no longer ends at the earlier 13:00 UTC hour")
        exports[name] = len(rows)

    if (freeze["assignment_manifest_sha256"] != EXPECTED["assignment"]
            or stopped["assignment_manifest_sha256"] != EXPECTED["assignment"]
            or collection["assignment_manifest_sha256"] != EXPECTED["assignment"]
            or len(collection["rows"]) != 5
            or [r["status"] for r in collection["rows"]] !=
            ["COMPLETE", "STOPPED", "PENDING", "PENDING", "PENDING"]
            or collection["rows"][1]["episode_id"] != EPISODE_ID
            or collection["shared_ledger_seq"] != 193
            or review["assigned_denominator"]["no_retry_or_substitution"] is not True
            or review["assigned_denominator"]["row_status"] != "STOPPED"
            or review["immutable_evidence_sha256"]["STOPPED.json"] != EXPECTED["stopped"]
            or review["immutable_evidence_sha256"]["inspect.eval"] != EXPECTED["inspect"]
            or review["immutable_evidence_sha256"]["openrouter-ledger.jsonl"] != EXPECTED["ledger"]
            or review["scientific_disposition"]["bilateral_collusion_eligible"] is not False):
        raise ValueError("frozen FEE014 assignment, denominator, or independent review differs")

    account = stopped["stopped_account_usage"]
    model_stop = stopped["stopped_model_events"]
    if (stopped["budget_state"] != "UNKNOWN"
            or stopped["ledger_status_at_stop"] != "UNKNOWN"
            or stopped["ledger_run_id"] != RUN_ID
            or stopped["no_retry_or_substitution"] is not True
            or stopped["complete_native_claim"] is not False
            or native["native_terminal_claim"] is not False
            or native["verdict"] is not None
            or account["before_usd"] != "3.1852534"
            or account["after_usd"] != "3.1852534"
            or Decimal(account["aggregate_delta_usd"]) != 0
            or account["scope"] != "whole OpenRouter account; not a per-call receipt"
            or account["failed_call_billing"] != "UNVERIFIED"
            or model_stop["guarded_api_invocations"] != 5
            or model_stop["inspect_successful_model_events"] != 4
            or model_stop["inspect_failed_model_events"] != 1
            or model_stop["provider_billing_for_failed_events"] != "UNVERIFIED"):
        raise ValueError("stopped native, model or account observation differs")

    log = read_eval_log(str(EPISODE / "inspect.eval"))
    if log.status != "error" or len(log.samples or []) != 1:
        raise ValueError("Inspect does not preserve exactly one stopped sample")
    sample = log.samples[0]
    events = [(i, e) for i, e in enumerate(sample.events or []) if e.event == "model"]
    if ([i for i, _ in events] != [20, 37, 54, 66, 82]
            or [e.model for _, e in events] != [
                "openrouter/anthropic/claude-sonnet-5.5",
                "openrouter/openai/gpt-5.6-sol",
                "openrouter/anthropic/claude-sonnet-5.5",
                "openrouter/openai/gpt-5.6-sol",
                "openrouter/anthropic/claude-sonnet-5.5",
            ]
            or any(e.error or e.output is None or e.output.usage is None for _, e in events[:4])
            or not events[4][1].error
            or events[4][1].output is None
            or events[4][1].output.usage is not None
            or "This model does not support assistant message prefill" not in events[4][1].error
            or "Error code: 400" not in events[4][1].error
            or review["inspect_replay"]["successful_model_completions"] != 4
            or review["inspect_replay"]["failed_model_events"] != 1):
        raise ValueError("saved Inspect events do not prove four returns and one HTTP 400")
    counts = Counter(e.model.removeprefix("openrouter/") for _, e in events[:4])
    prices = manifest["public_pricing_snapshot"]
    if set(sample.model_usage) != {"openrouter/" + name for name in counts}:
        raise ValueError("saved Inspect usage routes differ")
    estimate = sum((estimate_model_usage(prices[name],
                    sample.model_usage["openrouter/" + name], count)
                    for name, count in counts.items()), Decimal(0))
    if estimate != SUCCESS_ESTIMATE_USD:
        raise ValueError("frozen-price success-only model estimate differs")

    run = before["runs"].get(RUN_ID)
    if (before["seq"] != 193 or before["last_hash"] != LAST_HASH
            or before["cap_usd"] != "50"
            or before["settled_spent_usd"] != "8.832534"
            or before["reserved_usd"] != "18.386908"
            or before["available_usd"] != "22.780558"
            or before["blocked"] is not True
            or before["unknown_run_ids"] != [RUN_ID]
            or run is None or run["status"] != "UNKNOWN"
            or Decimal(run["reserved_usd"]) != HOLD_USD):
        raise ValueError("archived USD 50 ledger prestate differs")

    return {
        "schema": "fee014-first-stop-provisional-billing-v1",
        "result": "PROVISIONAL_HOLD_RETAINED_FINAL_CHARGE_UNKNOWN",
        "episode_id": EPISODE_ID,
        "run_id": RUN_ID,
        "frozen_artifacts_sha256": {name: EXPECTED[name] for name in (
            "assignment", "freeze", "collection", "stopped", "inspect", "native",
            "independent_review", "ledger", "anchor", "owner_request_csv",
            "owner_usage_csv")},
        "sample_uuid": sample.uuid,
        "sample_started_at_utc": sample.started_at,
        "sample_completed_at_utc": sample.completed_at,
        "inspect_model_event_indices": [i for i, _ in events],
        "successful_model_completions": 4,
        "failed_http_400_requests": 1,
        "failed_request_reason_class": "UNSUPPORTED_ASSISTANT_PREFILL",
        "guard_completed_flags_reliable_for_billing": False,
        "successful_usage_estimate_usd": str(estimate),
        "successful_usage_estimate_is_provider_invoice": False,
        "failed_request_provider_charge_usd": None,
        "attributable_final_provider_bill_usd": None,
        "per_request_billing_ids_saved": False,
        "owner_csv_latest_hour_utc": "2026-10-15 13:00:00",
        "owner_csv_covers_episode_at_20h_utc": False,
        "owner_csv_is_signed_provider_invoice": False,
        "owner_csv_row_counts": exports,
        "account_usage_before_usd": account["before_usd"],
        "account_usage_after_usd": account["after_usd"],
        "account_aggregate_delta_usd": str(Decimal(account["aggregate_delta_usd"])),
        "account_delta_is_per_request_evidence": False,
        "ledger_prestate": {key: before[key] for key in (
            "seq", "last_hash", "cap_usd", "settled_spent_usd", "reserved_usd",
            "available_usd", "blocked", "unknown_run_ids")},
        "retained_run_reservation_usd": str(HOLD_USD),
        "intended_transition": "UNKNOWN_TO_CONTINGENT_WITH_FULL_HOLD",
        "frozen_row_disposition": "STOPPED_NO_RETRY_THREE_PENDING",
        "final_settlement_requires": "attributable provider final billing for four successful and one failed request",
        "paid_model_calls": 0,
        "ledger_mutations_by_assessment": 0,
    }


def validate_saved_evidence() -> dict:
    result = assess()
    raw = serialized(result)
    if sha256(raw).hexdigest() != EVIDENCE_SHA256 or EVIDENCE.read_bytes() != raw:
        raise ValueError("reviewed provisional evidence digest or contents differ")
    return result


def transition(ledger_path: Path) -> dict:
    """One-time optimistic-concurrency transition; useful with a test ledger."""
    evidence = validate_saved_evidence()
    if (digest(ledger_path) != EXPECTED["ledger"]
            or digest(ledger_path.with_name(ledger_path.name + ".anchor")) != EXPECTED["anchor"]):
        raise ValueError("canonical ledger changed since independent review")
    before = read_ledger(ledger_path)
    if before["seq"] != 193 or before["last_hash"] != LAST_HASH:
        raise ValueError("canonical ledger is not the reviewed UNKNOWN prestate")
    after = BudgetLedger(ledger_path).mark_contingent(
        RUN_ID, "sha256:" + EVIDENCE_SHA256,
        expected_seq=before["seq"], expected_last_hash=before["last_hash"])
    run = after["runs"][RUN_ID]
    if (after["seq"] != 194 or after["blocked"] is not False
            or after["unknown_run_ids"]
            or after["settled_spent_usd"] != before["settled_spent_usd"]
            or after["reserved_usd"] != before["reserved_usd"]
            or after["available_usd"] != before["available_usd"]
            or run["status"] != "CONTINGENT"
            or Decimal(run["reserved_usd"]) != HOLD_USD
            or run.get("actual_usd") is not None
            or run["contingent_evidence_ref"] != "sha256:" + EVIDENCE_SHA256):
        raise ValueError("contingent transition failed to retain the full reserve")
    return {"applied": True, "run_id": RUN_ID, "new_ledger_seq": after["seq"],
            "status": run["status"], "retained_reservation_usd": str(HOLD_USD),
            "actual_final_charge_usd": None,
            "evidence_ref": "sha256:" + EVIDENCE_SHA256,
            "frozen_row_disposition": evidence["frozen_row_disposition"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="one-time canonical ledger transition; default is read-only")
    args = parser.parse_args()
    if args.apply:
        if ROOT.resolve() != CANONICAL_ROOT.resolve():
            raise ValueError("--apply requires the canonical shared-ledger checkout")
        result = transition(CANONICAL_LEDGER)
    else:
        result = validate_saved_evidence()
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
