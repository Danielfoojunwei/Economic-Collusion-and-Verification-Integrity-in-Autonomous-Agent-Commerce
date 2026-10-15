#!/usr/bin/env python3
"""Collect every frozen W10 assignment, including absent and failed trials.

This is a read-only evidence audit followed by a fresh descriptive export. It
never starts an agent, contacts OpenRouter, or submits a payment transaction.
"""

from __future__ import annotations

import argparse
import csv
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = str(WORKSPACE / ".local" / "share")
os.environ["XDG_CACHE_HOME"] = str(WORKSPACE / ".cache")
os.environ["XDG_CONFIG_HOME"] = str(WORKSPACE / ".config")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.run_erc8183_local import UPSTREAM  # noqa: E402
from inspect_ai.log import read_eval_log  # noqa: E402
from agent_economic_trust.evidence import verify_evidence  # noqa: E402
from agent_economic_trust.remote import PROJECT_LEDGER_PATH  # noqa: E402
from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402
from agent_economic_trust.w10_factorial import (  # noqa: E402
    APPROVED_MODEL_ID, FEE_MINOR_UNITS, Trial, _canonical, _hash,
    analyze_assignments, assignment_manifest, frozen_fixtures, make_assignments,
)
from agent_economic_trust.w10_factorial_remote import _score_trial  # noqa: E402
from agent_economic_trust.w10_funding import _expect_transfer  # noqa: E402


ERC8183_PIN = "142e669c1fd318486a4628395b629f033654dd06"
NATIVE_BUDGET = 20_000_000
SOURCE_FILES = (
    "src/agent_economic_trust/w10_factorial.py",
    "src/agent_economic_trust/protected_receipts.py",
)
REPORT_SOURCE_FILES = (
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
)


class EvidenceProblem(ValueError):
    """A short, non-sensitive reason for excluding an unverified result."""


def _need(condition: bool, reason: str) -> None:
    if not condition:
        raise EvidenceProblem(reason)


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _safe_file(path: Path) -> Path:
    _need(path.is_file() and not path.is_symlink(), "missing_or_linked_file")
    return path


def _load_plan(directory: Path) -> tuple[tuple[Trial, ...], str]:
    manifest_path = _safe_file(directory / "assignment_manifest.json")
    seed_path = _safe_file(directory / "seed.hex")
    private_path = _safe_file(directory / "private_fixtures.json")
    manifest = json.loads(manifest_path.read_bytes())
    seed = seed_path.read_text(encoding="ascii").strip()
    trials = make_assignments(seed)
    regenerated = assignment_manifest(seed)
    for field in ("schema", "plan_version", "seed_commitment_sha256",
                  "assignment_unit", "model_id", "reasoning_effort",
                  "primary_episodes", "cell_counts", "fixtures_private_sha256",
                  "assignments_sha256", "rows"):
        _need(manifest.get(field) == regenerated[field], "frozen_assignment_changed")
    private = json.loads(private_path.read_bytes())
    _need(private == [fixture.private_row() for fixture in frozen_fixtures()]
          and _hash(private) == manifest["fixtures_private_sha256"],
          "private_fixture_commitment_changed")
    source = manifest.get("source_sha256", {})
    for name in SOURCE_FILES:
        _need(source.get(name) == _sha(ROOT / name), "frozen_task_source_changed")
    _need(len(trials) == 32, "assignment_count_changed")
    return trials, _sha(manifest_path)


def _native_check(native: dict[str, Any], trial: Trial, record: dict[str, Any],
                  assignment_sha: str) -> dict[str, Any]:
    _need(native.get("schema") == "w10-live-native-trial-v1"
          and native.get("assignment_manifest_sha256") == assignment_sha
          and native.get("trial_id") == trial.trial_id
          and native.get("pair_id") == trial.pair_id
          and native.get("obligation_id") == trial.obligation_id
          and native.get("R") == trial.r
          and native.get("exception_type") is None,
          "native_assignment_or_completion_mismatch")
    _need(native.get("chain", {}).get("chain_id") == 31337
          and native.get("chain", {}).get("rpc_host") == "127.0.0.1"
          and native.get("source", {}).get("erc8183_base_commit") == ERC8183_PIN,
          "native_local_chain_or_source_mismatch")
    mock_artifact = UPSTREAM / "out" / "MockUSDC.sol" / "MockUSDC.json"
    _need(mock_artifact.is_file()
          and native["source"].get("mock_usdc_artifact_sha256") == _sha(mock_artifact)
          and native.get("contracts", {}).get("MockUSDC", {}).get("artifact_sha256") == _sha(mock_artifact),
          "native_token_artifact_changed")
    terms = native.get("fee_terms", {})
    _need(terms.get("prepaid_audit_fee_minor_units") == FEE_MINOR_UNITS
          and terms.get("conditional_evaluator_fee_bps") == 0
          and terms.get("platform_fee_bps") == 0,
          "native_fee_terms_changed")
    roles = native["roles"]
    _need(len({value.lower() for value in roles.values()}) == len(roles),
          "native_roles_not_distinct")
    token = native["token_address"].lower()
    core = native["core_address"].lower()
    _need(native["contracts"]["MockUSDC"]["address"].lower() == token
          and native["contracts"]["ERC1967Proxy"]["address"].lower() == core,
          "native_contract_addresses_changed")
    transactions = native["transactions"]
    by_step = {tx["step"]: tx for tx in transactions}
    _need(len(by_step) == len(transactions), "duplicate_native_transaction_step")
    steps = ("assigned_job.create", "assigned_job.budget", "assigned_job.fund",
             "assigned_prepaid_audit_fee", "assigned_job.submit",
             "assigned_job.auditor_verdict")
    _need(all(step in by_step for step in steps)
          and [by_step[step]["block_number"] for step in steps]
          == sorted(by_step[step]["block_number"] for step in steps)
          and len({by_step[step]["block_number"] for step in steps}) == len(steps),
          "native_causal_order_changed")
    for step in steps:
        tx = by_step[step]
        receipt = tx["raw_receipt"]
        _need(tx["status"] == tx["expected_status"] == 1
              and int(receipt["status"], 16) == 1
              and tx["transaction_hash"].lower() == receipt["transactionHash"].lower()
              and int(receipt["blockNumber"], 16) == tx["block_number"],
              "native_receipt_or_status_changed")
    fund = by_step["assigned_job.fund"]
    fee = by_step["assigned_prepaid_audit_fee"]
    submit = by_step["assigned_job.submit"]
    settlement = by_step["assigned_job.auditor_verdict"]
    payer = "provider" if trial.r else "client"
    _need(fund["actor_role"] == "client" and fee["actor_role"] == payer
          and submit["actor_role"] == "provider"
          and settlement["actor_role"] == "evaluator",
          "native_transaction_actor_changed")
    _expect_transfer(fund["raw_receipt"], token, roles["client"].lower(), core,
                     NATIVE_BUDGET)
    _need(native["fee_receipt"] == fee["raw_receipt"]
          and native["fee_transaction"]["hash"].lower() == fee["transaction_hash"].lower()
          and native["fee_transaction"]["from"].lower() == roles[payer].lower()
          and native["fee_transaction"]["to"].lower() == token
          and int(native["fee_transaction"]["chainId"], 16) == 31337
          and native["fee_transaction"]["input"].lower()
          == "0xa9059cbb" + roles["evaluator"].lower()[2:].rjust(64, "0")
          + format(FEE_MINOR_UNITS, "064x")
          and record["prepaid_fee_transaction_hash"].lower() == fee["transaction_hash"].lower(),
          "native_prepaid_fee_transaction_changed")
    _expect_transfer(fee["raw_receipt"], token, roles[payer].lower(),
                     roles["evaluator"].lower(), FEE_MINOR_UNITS)
    before_fee, after_fee = native["fee_before"], native["fee_after"]
    _need(set(before_fee) == set(after_fee) == set(roles) | {"escrow"},
          "native_fee_balance_roles_changed")
    for role in before_fee:
        expected_delta = -FEE_MINOR_UNITS if role == payer else \
            FEE_MINOR_UNITS if role == "evaluator" else 0
        _need(after_fee[role] - before_fee[role] == expected_delta,
              "native_fee_balance_delta_changed")
    _need(any(log["data"].lower() == "0x" + trial.artifact_digest
              for log in submit["logs"] if log["name"] == "JobSubmitted"),
          "native_submitted_artifact_changed")
    payout = native["task_settlement"]
    paid = record["verdict"] == "ACCEPT"
    _need(payout["verdict"] == record["verdict"]
          and payout["artifact_digest"] == trial.artifact_digest
          and payout["obligation_id"] == trial.obligation_id
          and payout["job_id"] == native["job_id"] == record["native_job_id"]
          and payout["job_status"] == ("Completed" if paid else "Rejected")
          and payout["provider_paid"] is paid
          and payout["provider_payout_minor_units"] == (NATIVE_BUDGET if paid else 0)
          and record["provider_payout_minor_units"] == payout["provider_payout_minor_units"]
          and record["payment_status"] == ("PAID" if paid else "NOT_PAID")
          and payout["transaction_hash"].lower() == settlement["transaction_hash"].lower()
          and record["native_settlement_transaction_hash"].lower()
          == settlement["transaction_hash"].lower()
          and payout["raw_receipt"] == settlement["raw_receipt"],
          "native_job_settlement_changed")
    _expect_transfer(settlement["raw_receipt"], token, core,
                     roles["provider" if paid else "client"].lower(), NATIVE_BUDGET)
    before = payout["before"]["balances_minor_units"]
    after = payout["after"]["balances_minor_units"]
    _need(before == after_fee and set(after) == set(before)
          and payout["before"]["total_supply_minor_units"]
          == payout["after"]["total_supply_minor_units"]
          == sum(before.values()) == sum(after.values()),
          "native_settlement_balance_snapshot_changed")
    for role in before:
        expected_delta = -NATIVE_BUDGET if role == "escrow" else \
            NATIVE_BUDGET if role == ("provider" if paid else "client") else 0
        _need(after[role] - before[role] == expected_delta,
              "native_provider_payout_or_refund_delta_changed")
    return {"fee_transaction_hash": fee["transaction_hash"],
            "settlement_transaction_hash": settlement["transaction_hash"],
            "fund_transaction_hash": fund["transaction_hash"],
            "submit_transaction_hash": submit["transaction_hash"]}


def _export_check(directory: Path, trial: Trial, record: dict[str, Any],
                  assignment_sha: str, native_links: dict[str, str],
                  expected_run_id: str) -> None:
    for name in ("run_manifest.json", "events.jsonl", "episode_outcomes.csv"):
        _safe_file(directory / name)
    _need(verify_evidence(directory)["outcomes"] == 1, "v1_evidence_count_changed")
    manifest = json.loads(_safe_file(directory / "run_manifest.json").read_bytes())
    _need(manifest.get("status") == "COMPLETE"
          and manifest.get("run_id") == expected_run_id
          and manifest.get("experiment_id") == "w10-economic-rsp-exploratory"
          and manifest.get("planned_episodes") == manifest.get("completed_episodes") == 1
          and manifest.get("model_behavior_tier") == "REAL_LLM_REMOTE_APPROVED"
          and manifest.get("payment_tier") == "NATIVE_LOCAL_CHAIN"
          and manifest.get("project_cap_usd") == "20"
          and manifest.get("ledger_run_id") == expected_run_id,
          "v1_manifest_execution_provenance_changed")
    random = manifest["randomization"]
    _need(random.get("assignment_manifest_sha256") == assignment_sha
          and random.get("trial_id") == trial.trial_id
          and random.get("pair_id") == trial.pair_id
          and (random.get("R"), random.get("S"), random.get("P"))
          == (trial.r, trial.s, trial.p)
          and manifest.get("obligation_id") == trial.obligation_id
          and manifest.get("artifact_digest") == trial.artifact_digest
          and manifest.get("models") == [{"id": APPROVED_MODEL_ID,
                                           "kind": "REAL_LLM_REMOTE_APPROVED",
                                           "reasoning_effort": "high"}],
          "v1_manifest_treatment_or_model_changed")
    source_pins = manifest.get("source_pins", {})
    _need(source_pins.get("orbit", {}).get("version") == "1.0.3"
          and source_pins.get("inspect_ai", {}).get("version") == "0.3.263"
          and source_pins.get("erc8183_base", {}).get("commit") == ERC8183_PIN,
          "v1_upstream_pins_changed")
    for name in REPORT_SOURCE_FILES:
        _need(manifest.get("source_sha256", {}).get(name) == _sha(ROOT / name),
              "v1_local_source_changed")
    _need(manifest.get("source_sha256") == record.get("source_sha256")
          and set(manifest["source_sha256"]) == set(REPORT_SOURCE_FILES),
          "v1_record_source_provenance_changed")
    artifacts = manifest["artifacts_sha256"]
    _need(artifacts.get("inspect.eval") == record["native_inspect_sha256"]
          and artifacts.get("native_evidence.json") == record["native_payment_sha256"],
          "v1_native_artifact_hash_changed")
    with _safe_file(directory / "episode_outcomes.csv").open(newline="", encoding="utf-8") as stream:
        outcomes = list(csv.DictReader(stream))
    _need(len(outcomes) == 1, "v1_outcome_count_changed")
    outcome = outcomes[0]
    truth = next(f.truth for f in frozen_fixtures() if f.fixture_id == trial.fixture_id)
    _need(outcome["episode_id"] == trial.trial_id
          and outcome["pair_id"] == trial.pair_id
          and outcome["fixture_id"] == trial.fixture_id
          and [outcome[key] for key in ("R", "S", "P")]
          == [str(trial.r), str(trial.s), str(trial.p)]
          and outcome["Y"] == str(truth)
          and outcome["V"] == record["verdict"]
          and outcome["Q"] == str(record["checked"])
          and outcome["M"] == record["payment_status"]
          and outcome["provider_payout_minor_units"]
          == str(record["provider_payout_minor_units"])
          and outcome["execution_tier"] == "NATIVE_LOCAL_PROTOCOL",
          "v1_outcome_differs_from_native_trial")
    events = [json.loads(line) for line in
              _safe_file(directory / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    by_type: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_type.setdefault(event["event_type"], []).append(event)
        _need(event["episode_id"] == trial.trial_id
              and event["obligation_id"] == trial.obligation_id,
              "v1_event_assignment_changed")
    expected_singletons = {
        "JOB_FUNDED": native_links["fund_transaction_hash"],
        "AUDITOR_FEE_PAID": native_links["fee_transaction_hash"],
        "JOB_SUBMITTED": native_links["submit_transaction_hash"],
        "PROVIDER_PAID" if record["payment_status"] == "PAID"
        else "JOB_REJECTED_REFUNDED": native_links["settlement_transaction_hash"],
    }
    for kind, transaction_hash in expected_singletons.items():
        _need(len(by_type.get(kind, [])) == 1
              and by_type[kind][0]["payment_reference"].lower() == transaction_hash.lower(),
              "v1_payment_event_unlinked")
    _need(len(by_type.get("AUDITOR_VERDICT", [])) == 1
          and by_type["AUDITOR_VERDICT"][0]["payload"]["verdict"] == record["verdict"]
          and by_type["AUDITOR_VERDICT"][0]["payload"]["treatment_audit"] == "PASS"
          and len(by_type.get("ORACLE_SCORED", [])) == 1
          and by_type["ORACLE_SCORED"][0]["payload"]["Y"] == truth
          and len(by_type.get("TASK_CLOSED", [])) == 1
          and by_type["TASK_CLOSED"][0]["payload"]["native_inspect_sha256"]
          == record["native_inspect_sha256"]
          and by_type["TASK_CLOSED"][0]["payload"]["native_payment_sha256"]
          == record["native_payment_sha256"],
          "v1_decision_or_close_event_changed")


def _validated_record(directory: Path, trial: Trial, assignment_sha: str,
                      raw: dict[str, Any], ledger_runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    expected_run_id = f"w10-factorial-{assignment_sha[:12]}-{trial.trial_id}"
    _need(raw.get("status") == "COMPLETE"
          and raw.get("trial_id") == trial.trial_id
          and raw.get("pair_id") == trial.pair_id
          and raw.get("assignment_manifest_sha256") == assignment_sha
          and raw.get("ledger_run_id") == expected_run_id
          and raw.get("model_tier") == "REAL_LLM"
          and raw.get("payment_tier") == "NATIVE_LOCAL",
          "trial_record_provenance_changed")
    inspect_path = _safe_file(directory / "inspect.eval")
    native_path = _safe_file(directory / "native_evidence.json")
    _need(raw.get("native_inspect_sha256") == _sha(inspect_path)
          and raw.get("native_payment_sha256") == _sha(native_path)
          and _safe_file(directory / "native" / "evidence.json").read_bytes()
          == native_path.read_bytes(),
          "native_evidence_file_hash_changed")
    saved = read_eval_log(str(inspect_path), resolve_attachments=True)
    scored = _score_trial(saved, trial, APPROVED_MODEL_ID)
    _need(raw.get("verdict") == scored["verdict"]
          and raw.get("checked") is scored["checked"]
          and raw.get("check_spent_units") == scored["check_spent_units"]
          and raw.get("oracle_truth") == scored["oracle_truth"]
          and raw.get("false_approval") is scored["false_approval"]
          and raw.get("channel_isolation_audit") == "PASS"
          and raw.get("treatment_audit") == scored["treatment_audit"] == "PASS"
          and raw.get("channel_audit") == scored["channel_audit"],
          "saved_inspect_decision_changed")
    _need(0 < raw.get("model_calls", 0) <= 6
          and raw["model_calls"] == scored["channel_audit"]["model_events"],
          "saved_inspect_model_call_count_changed")
    native = json.loads(native_path.read_bytes())
    native_links = _native_check(native, trial, raw, assignment_sha)
    ledger = ledger_runs.get(expected_run_id, {})
    _need(ledger.get("status") == "SETTLED"
          and ledger.get("evidence_ref") == f"sha256:{raw['native_inspect_sha256']}"
          and ledger.get("metadata", {}).get("model_id") == APPROVED_MODEL_ID
          and ledger.get("metadata", {}).get("trial_id") == trial.trial_id
          and ledger.get("metadata", {}).get("pair_id") == trial.pair_id
          and ledger.get("metadata", {}).get("assignment_sha") == assignment_sha
          and Decimal(ledger["actual_usd"]) == Decimal(raw["model_cost_usd_estimate"]),
          "canonical_budget_ledger_unlinked")
    _export_check(directory, trial, raw, assignment_sha, native_links, expected_run_id)
    return {key: raw[key] for key in (
        "trial_id", "pair_id", "assignment_manifest_sha256", "status",
        "model_tier", "payment_tier", "verdict", "checked", "check_spent_units",
        "oracle_truth", "false_approval", "payment_status",
        "provider_payout_minor_units", "native_job_id",
        "native_settlement_transaction_hash", "prepaid_fee_transaction_hash",
        "channel_isolation_audit", "treatment_audit", "native_inspect_sha256",
        "native_payment_sha256", "model_calls", "model_cost_usd_estimate",
        "ledger_run_id", "source_sha256",
    )} | {"evidence_validation": "PASS", "run_manifest_sha256": _sha(directory / "run_manifest.json")}


def _one_record(directory: Path, trial: Trial, assignment_sha: str,
                ledger_runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    common = {"trial_id": trial.trial_id, "pair_id": trial.pair_id,
              "fixture_id": trial.fixture_id, "R": trial.r, "S": trial.s,
              "P": trial.p, "assignment_manifest_sha256": assignment_sha}
    if not directory.exists():
        return common | {"status": "PENDING", "payment_status": "UNKNOWN",
                         "evidence_validation": "NO_OUTPUT"}
    if directory.is_symlink() or not directory.is_dir():
        return common | {"status": "MODEL_FAILED", "payment_status": "UNKNOWN",
                         "evidence_validation": "FAIL", "evidence_issue": "run_directory_invalid"}
    record_path = directory / "trial_record.json"
    if not record_path.is_file() or record_path.is_symlink():
        return common | {"status": "MODEL_FAILED", "payment_status": "UNKNOWN",
                         "evidence_validation": "FAIL", "evidence_issue": "trial_record_missing"}
    try:
        raw = json.loads(record_path.read_bytes())
        _need(isinstance(raw, dict)
              and raw.get("trial_id") == trial.trial_id
              and raw.get("pair_id") == trial.pair_id
              and raw.get("assignment_manifest_sha256") == assignment_sha,
              "partial_record_assignment_changed")
        if (directory / "STOPPED.json").exists():
            raise EvidenceProblem("runner_stopped_after_record")
        if raw.get("status") == "COMPLETE":
            return common | _validated_record(directory, trial, assignment_sha, raw, ledger_runs)
        _need(raw.get("status") in {"PENDING", "MODEL_FAILED", "PAYMENT_FAILED"}
              and raw.get("payment_status") == "UNKNOWN",
              "invalid_partial_status")
        return common | {"status": raw["status"], "payment_status": "UNKNOWN",
                         "evidence_validation": "INCOMPLETE",
                         "stage": str(raw.get("stage", "unknown"))[:80],
                         "ledger_run_id": str(raw.get("ledger_run_id", ""))[:160]}
    except Exception as exc:
        issue = str(exc) if isinstance(exc, EvidenceProblem) else type(exc).__name__
        return common | {"status": "MODEL_FAILED", "payment_status": "UNKNOWN",
                         "evidence_validation": "FAIL", "evidence_issue": issue}


def _new_file(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def collect(assignment_dir: Path, runs_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Verify each output independently and retain all assigned pair clusters."""
    assignment_dir, runs_dir, output_dir = map(Path, (assignment_dir, runs_dir, output_dir))
    if output_dir.exists():
        raise FileExistsError("collection output already exists")
    if not runs_dir.is_dir() or runs_dir.is_symlink():
        raise FileNotFoundError("trial run directory is missing or linked")
    trials, assignment_sha = _load_plan(assignment_dir)
    ledger = BudgetLedger(PROJECT_LEDGER_PATH).snapshot()
    _need(ledger["cap_usd"] == "20", "canonical_budget_cap_changed")
    records = [_one_record(runs_dir / trial.trial_id, trial, assignment_sha,
                           ledger["runs"]) for trial in trials]
    analysis = analyze_assignments(trials, records)
    analysis.update({
        "assignment_manifest_sha256": assignment_sha,
        "record_count_including_pending": len(records),
        "missing_output_count": sum(row["evidence_validation"] == "NO_OUTPUT" for row in records),
        "failed_evidence_count": sum(row["evidence_validation"] == "FAIL" for row in records),
        "valid_complete_count": sum(row["evidence_validation"] == "PASS" for row in records),
        "incomplete_output_count": sum(row["evidence_validation"] == "INCOMPLETE" for row in records),
        "claim_scope": "descriptive_exploratory_ITT_bounds_only",
        "causal_claim_ready": False,
        "ledger_last_hash_at_collection": ledger["last_hash"],
    })
    output_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    encoded = b"".join(_canonical(record) + b"\n" for record in records)
    _new_file(output_dir / "records.jsonl", encoded)
    analysis["records_sha256"] = sha256(encoded).hexdigest()
    _new_file(output_dir / "analysis.json", _canonical(analysis) + b"\n")
    return {"mode": "read_only_descriptive_collection",
            "assignment_count": len(trials),
            "valid_complete_count": analysis["valid_complete_count"],
            "missing_output_count": analysis["missing_output_count"],
            "failed_evidence_count": analysis["failed_evidence_count"],
            "records_sha256": analysis["records_sha256"],
            "analysis_sha256": _sha(output_dir / "analysis.json")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assignment-dir", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = collect(args.assignment_dir, args.runs_dir, args.output_dir)
    except Exception as exc:
        print(f"W10 factorial collection stopped: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
