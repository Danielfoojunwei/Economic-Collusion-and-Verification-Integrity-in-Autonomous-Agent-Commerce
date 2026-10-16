#!/usr/bin/env python3
"""W09: replay a frozen invoice decision through two distinct native payment uses.

ERC-8183 pays the worker after an evaluator attests to a submitted job. x402
pays a seller for delivering an HTTP record. The shared task, artifact, and
scripted verdict are application inputs; neither protocol guarantees the
record's semantic correctness. All balances are valueless local test tokens.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agent_economic_trust.core import FIXTURES, OracleStatus, oracle_score


W07_DEFAULT = ROOT / "artifacts" / "gates" / "W07" / "native-run-001" / "evidence.json"
X402_RUNNER = ROOT / "scripts" / "run_x402_local.mjs"
ERC_PIN = "142e669c1fd318486a4628395b629f033654dd06"
X402_PIN = "e95b06661e1a2a8a9a21fce34cc28b9934834650"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _load_w07(path: Path) -> dict[str, Any]:
    evidence = json.loads(path.read_text(encoding="utf-8"))
    if evidence["work_order"] != "W07" or evidence["source"]["commit"] != ERC_PIN:
        raise AssertionError("W07 evidence does not match the pinned native replay")
    if evidence["model_behavior_tier"] != "SCRIPTED_SIMULATION":
        raise AssertionError("W07 verdict origin is not the scripted control")
    if evidence["payment_tier"] != "NATIVE_LOCAL_PROTOCOL":
        raise AssertionError("W07 payment is not native local protocol evidence")
    if set(evidence["pairs"]) != {"good", "bad"}:
        raise AssertionError("W07 requires both good and bad invoice controls")
    return evidence


def _record(case: str, pair: dict[str, Any]) -> dict[str, Any]:
    fixture, artifact = FIXTURES[case]
    decision = pair["frozen_auditor_decision"]
    digest = artifact.digest()
    if pair["task_id"] != fixture.task_id or pair["artifact_digest"] != digest:
        raise AssertionError(f"W07 {case} task/artifact changed")
    if decision["artifact_digest"] != digest or decision["verdict"] != "ACCEPT":
        raise AssertionError(f"W07 {case} decision does not approve this artifact")
    if decision["check_completed"] or decision["check_spent_units"]:
        raise AssertionError(f"W07 {case} control verdict was not unchecked")
    if canonical_sha256(decision) != pair["frozen_decision_sha256"]:
        raise AssertionError(f"W07 {case} frozen decision hash is invalid")
    if pair["prestate"] != pair["restored_prestate"] or not pair["identical_prestate"]:
        raise AssertionError(f"W07 {case} pre-state was not restored")
    expected = OracleStatus.PASS if case == "good" else OracleStatus.FAIL
    if oracle_score(fixture, artifact).status != expected or pair["oracle_status"] != expected.value:
        raise AssertionError(f"W07 {case} protected oracle result changed")
    # The HTTP buyer buys delivery of this record. Oracle truth is intentionally
    # absent; a private correctness check occurs only in the W09 verifier.
    return {
        "schema_version": 1,
        "resource_type": "invoice_reconciliation_record",
        "public_task": fixture.public_task(),
        "submitted_artifact": {
            "task_id": artifact.task_id,
            "submitted_amount_cents": artifact.submitted_amount_cents,
        },
        "artifact_sha256": digest,
        "auditor_decision": decision,
        "auditor_decision_sha256": pair["frozen_decision_sha256"],
        "decision_origin": "SCRIPTED_UNCHECKED_CONTROL",
    }


def _erc_consequence(pair: dict[str, Any]) -> dict[str, Any]:
    before = pair["prestate"]["token_state"]["balances_minor_units"]
    unguarded = pair["arms"]["unguarded"]
    guarded = pair["arms"]["guarded"]
    paid = unguarded["final_state"]["token_state"]["balances_minor_units"]
    guarded_state = guarded["final_state"]["token_state"]["balances_minor_units"]
    tx = unguarded["transactions"][0]
    if pair["prestate"]["job"]["status"] != "Submitted":
        raise AssertionError("ERC pre-state must be Submitted")
    if unguarded["final_state"]["job"]["status"] != "Completed":
        raise AssertionError("ERC unguarded evaluator approval did not complete job")
    if tx["status"] != 1 or tx["raw_receipt"]["status"] != "0x1":
        raise AssertionError("ERC completion lacks a successful native receipt")
    if paid["provider"] - before["provider"] != 17_000_000:
        raise AssertionError("ERC provider payment differs from receipt-tested W07 amount")
    if paid["escrow"] - before["escrow"] != -20_000_000:
        raise AssertionError("ERC escrow delta differs from W07 funded job")
    if guarded["application_guard"]["origin"] != "APPLICATION_IDEAL_ORACLE_UPPER_BOUND":
        raise AssertionError("W07 guard provenance changed")
    return {
        "native_trigger": "designated_evaluator_complete_on_submitted_job",
        "job_id": pair["job_id"],
        "submitted_artifact_digest": pair["artifact_digest"],
        "prestate_block_hash": pair["prestate"]["block_hash"],
        "unguarded_completion_transaction": tx["transaction_hash"],
        "unguarded_terminal_state": unguarded["final_state"]["job"]["status"],
        "unguarded_provider_delta_minor_units": paid["provider"] - before["provider"],
        "unguarded_escrow_delta_minor_units": paid["escrow"] - before["escrow"],
        "guarded_application_origin": guarded["application_guard"]["origin"],
        "guarded_terminal_state": guarded["final_state"]["job"]["status"],
        "guarded_provider_delta_minor_units": guarded_state["provider"] - before["provider"],
        "guarded_client_delta_minor_units": guarded_state["client"] - before["client"],
        "native_evaluator_role": True,
    }


def _x402_consequence(native: dict[str, Any], expected_record: dict[str, Any]) -> dict[str, Any]:
    if native["workOrder"] != "W08" or native["status"] != "PASS":
        raise AssertionError("x402 native runner did not pass")
    if native["upstream"]["commit"] != X402_PIN:
        raise AssertionError("x402 source pin changed")
    if native["upstream"]["protocol"] != "x402 v2" or native["upstream"]["scheme"] != "exact":
        raise AssertionError("x402 native scheme changed")
    if native["modelExecutionTier"] != "SCRIPTED_SIMULATION":
        raise AssertionError("x402 behavior was not the scripted control")
    if native["transactionExecutionTier"] != "NATIVE_LOCAL_PROTOCOL":
        raise AssertionError("x402 payment was not local native evidence")
    if native["http"]["resourceBody"] != expected_record or native["http"]["paidStatus"] != 200:
        raise AssertionError("the paid HTTP response did not deliver the frozen record")
    if native["http"]["challenge"]["x402Version"] != 2:
        raise AssertionError("paid resource lacked an x402 v2 challenge")
    if not native["verify"]["result"]["isValid"] or not native["settle"]["result"]["success"]:
        raise AssertionError("x402 authorization did not verify and settle")
    if native["verify"]["before"] != native["verify"]["after"]:
        raise AssertionError("x402 verify changed native token state")
    if native["transaction"]["status"] != "success":
        raise AssertionError("x402 settlement transaction failed")
    if native["transaction"]["hash"] != native["settle"]["result"]["transaction"]:
        raise AssertionError("x402 HTTP settlement and chain receipt disagree")
    if native["balances"]["nonceUsedAfterSettle"] is not True:
        raise AssertionError("x402 payment nonce was not consumed")
    challenge = native["http"]["challenge"]["accepts"][0]
    amount = int(challenge["amount"])
    balances = native["balances"]
    buyer_delta = int(balances["finalBuyer"]) - int(balances["initialBuyer"])
    seller_delta = int(balances["finalSeller"]) - int(balances["initialSeller"])
    if buyer_delta != -amount or seller_delta != amount:
        raise AssertionError("x402 buyer/seller balance changes do not match price")
    logs = [log for log in native["transaction"]["logs"]
            if log["address"].lower() == native["chain"]["tokenAddress"].lower()
            and log["topics"][0].lower() == TRANSFER_TOPIC]
    if len(logs) != 1 or int(logs[0]["data"], 16) != amount:
        raise AssertionError("x402 payment lacks one exact native Transfer log")
    from_address = "0x" + logs[0]["topics"][1][-40:]
    to_address = "0x" + logs[0]["topics"][2][-40:]
    if from_address.lower() != native["actors"]["buyer"].lower():
        raise AssertionError("x402 Transfer payer differs from buyer")
    if to_address.lower() != native["actors"]["seller"].lower():
        raise AssertionError("x402 Transfer recipient differs from seller")
    phases = [event["phase"] for event in native["trace"]]
    if phases != ["CHALLENGE", "SIGNED_AUTHORIZATION", "VERIFY", "RESOURCE_EXECUTE", "SETTLE", "RESPONSE"]:
        raise AssertionError("x402 native event order changed")
    return {
        "native_trigger": "verified_eip3009_authorization_after_successful_http_resource_execution",
        "resource_url": native["http"]["resourceUrl"],
        "http_status": native["http"]["paidStatus"],
        "resource_record_sha256": canonical_sha256(expected_record),
        "settlement_transaction": native["transaction"]["hash"],
        "settlement_block_hash": native["transaction"]["blockHash"],
        "settlement_block_number": native["transaction"]["blockNumber"],
        "buyer_delta_minor_units": buyer_delta,
        "seller_delta_minor_units": seller_delta,
        "transfer_log_index": logs[0]["logIndex"],
        "nonce_consumed": True,
        "native_evaluator_role": False,
        "resource_body_signed_by_eip3009": False,
    }


def run(*, w07_path: Path, output: Path, port_base: int) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite W09 evidence: {output}")
    if not 1024 < port_base < 65480:
        raise ValueError("port base is outside the safe loopback range")
    w07 = _load_w07(w07_path)
    records = {case: _record(case, w07["pairs"][case]) for case in ("good", "bad")}
    output.mkdir(parents=True)
    cases: dict[str, Any] = {}
    for index, case in enumerate(("good", "bad")):
        case_dir = output / case
        case_dir.mkdir()
        record_path = case_dir / "resource-record.json"
        record_path.write_text(json.dumps(records[case], indent=2, sort_keys=True) + "\n", encoding="utf-8")
        x402_path = case_dir / "x402-native.json"
        result = subprocess.run(
            ["node", str(X402_RUNNER), "--port", str(port_base + 20 * index),
             "--resource-record-file", str(record_path), "--output", str(x402_path)],
            cwd=ROOT, capture_output=True, text=True, timeout=90, check=False,
        )
        (case_dir / "x402.stdout.txt").write_text(result.stdout, encoding="utf-8")
        (case_dir / "x402.stderr.txt").write_text(result.stderr, encoding="utf-8")
        if result.returncode != 0:
            raise RuntimeError(f"native x402 {case} run failed; inspect {case_dir / 'x402.stderr.txt'}")
        x402_native = json.loads(x402_path.read_text(encoding="utf-8"))
        erc = _erc_consequence(w07["pairs"][case])
        x402 = _x402_consequence(x402_native, records[case])
        oracle_status = oracle_score(*FIXTURES[case]).status.value
        cases[case] = {
            "task_id": FIXTURES[case][0].task_id,
            "artifact_sha256": FIXTURES[case][1].digest(),
            "frozen_decision_sha256": records[case]["auditor_decision_sha256"],
            "oracle_status": oracle_status,
            "resource_record_path": str(record_path.relative_to(output)),
            "resource_record_file_sha256": file_sha256(record_path),
            "x402_evidence_path": str(x402_path.relative_to(output)),
            "x402_evidence_file_sha256": file_sha256(x402_path),
            "erc8183": erc,
            "x402": x402,
            "application_outcomes": {
                "erc_unguarded_bad_work_paid": oracle_status == "FAIL" and erc["unguarded_provider_delta_minor_units"] > 0,
                "x402_incorrect_record_delivered_and_paid": oracle_status == "FAIL" and x402["seller_delta_minor_units"] > 0,
                "x402_native_payment_rule_satisfied": True,
            },
        }
    evidence = {
        "schema_version": 1,
        "work_order": "W09",
        "gate": "G3",
        "status": "PASS",
        "model_behavior_tier": "SCRIPTED_SIMULATION",
        "payment_tier": "NATIVE_LOCAL_PROTOCOL",
        "study_type": "fixed_decision_cross_flow_consequence_pilot",
        "source": {
            "w07_evidence_path": str(w07_path),
            "w07_evidence_file_sha256": file_sha256(w07_path),
            "erc8183_commit": ERC_PIN,
            "x402_commit": X402_PIN,
            "w09_runner_sha256": file_sha256(Path(__file__)),
            "x402_runner_sha256": file_sha256(X402_RUNNER),
        },
        "flow_semantics": {
            "erc8183": "client-funded worker job; designated evaluator ACCEPT releases escrow",
            "x402": "buyer pays seller for delivery of the submitted invoice report as an HTTP resource",
            "shared_application_inputs": ["public task", "submitted artifact", "scripted unchecked ACCEPT", "decision SHA-256"],
            "x402_signature_binds_http_resource_or_artifact": False,
            "x402_has_native_evaluator_or_semantic_oracle": False,
            "w07_guard_is_native_erc_rule": False,
            "amounts_comparable_across_flows": False,
            "security_ranking_supported": False,
        },
        "cases": cases,
    }
    (output / "evidence.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--w07-evidence", type=Path, default=W07_DEFAULT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port-base", type=int, default=18620)
    args = parser.parse_args()
    result = run(w07_path=args.w07_evidence, output=args.output, port_base=args.port_base)
    print(json.dumps({"status": result["status"], "cases": list(result["cases"]),
                      "output": str(args.output / "evidence.json")}))
