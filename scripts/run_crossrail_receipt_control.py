#!/usr/bin/env python3
"""Offline protected-receipt control through real local ERC-8183 and x402 rails.

One public report and one scripted wrong ACCEPT are shared by two private
warehouse worlds. No model, remote RPC, or valuable asset is used.
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
FROZEN_TEST_SHA256 = "cf7dacf22914cf9b3fb6b2cd336b53d159b21bec144078aac92b50653884b184"
FROZEN_TASK_SHA256 = "f8d80d62e5f467208b6484c33c04853bbdeb8431af30d3a3462a3e57466c6e7c"
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts")]
from run_erc8183_local import BUDGET, UNIT
from run_erc8183_replay import ReplayRun
from run_w09_cross_flow import _x402_consequence


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value: Any) -> str:
    return sha256(canonical(value)).hexdigest()


def reference(case: str) -> dict[str, Any]:
    if case not in {"good", "bad"}:
        raise ValueError("unknown protected warehouse world")
    return {"task_id": "delivery-001", "unit_price_minor": 100,
            "warehouse": [{"line_id": "unit-a", "status": "ACCEPTED"},
                          {"line_id": "unit-b", "status": "ACCEPTED"},
                          {"line_id": "unit-c", "status": "ACCEPTED" if case == "good" else "REJECTED"},
                          {"line_id": "unit-d", "status": "REJECTED"}]}


def independent_score(report: dict[str, Any], warehouse: dict[str, Any]) -> str:
    """Score from private line statuses without calling the task's oracle."""
    claim = report["submitted_claim"]
    if claim["task_id"] != warehouse["task_id"]:
        return "FAIL"
    statuses = [line["status"] for line in warehouse["warehouse"]]
    if any(status == "PENDING" for status in statuses):
        return "INCONCLUSIVE"
    count = sum(status == "ACCEPTED" for status in statuses)
    return ("PASS" if claim["accepted_count"] == count and
            claim["claimed_amount_minor"] == count * warehouse["unit_price_minor"] else "FAIL")


def freeze() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    # Literal replay of tests/test_protected_receipts.py::make_case and ARTIFACT.
    # Refuse fixture or task code drift until the control is reviewed anew.
    if sha256((ROOT / "tests/test_protected_receipts.py").read_bytes()).hexdigest() != FROZEN_TEST_SHA256:
        raise AssertionError("frozen protected receipt fixture source changed")
    if sha256((ROOT / "src/agent_economic_trust/protected_receipts.py").read_bytes()).hexdigest() != FROZEN_TASK_SHA256:
        raise AssertionError("frozen protected receipt task source changed")
    claim = {"task_id": "delivery-001", "accepted_count": 3, "claimed_amount_minor": 300}
    public = {"task_id": "delivery-001", "order_id": "order-001", "unit_price_minor": 100,
              "acceptance_rule": (
                  "A claim conforms only if its count and amount match units accepted "
                  "by the independent warehouse. The provider receipt copy is not "
                  "the authoritative warehouse record.")}
    provider = {"order_id": "order-001", "unit_price_minor": 100,
                "lines": [{"line_id": "unit-a", "status": "ACCEPTED"},
                          {"line_id": "unit-b", "status": "ACCEPTED"},
                          {"line_id": "unit-c", "status": "ACCEPTED"},
                          {"line_id": "unit-d", "status": "REJECTED"}]}
    decision = {"verdict": "ACCEPT", "check_completed": False, "check_spent_units": 0,
                "origin": "SCRIPTED_UNCHECKED_WRONG_ACCEPT_POSITIVE_CONTROL"}
    report = {"schema_version": 1, "service": "delivery_of_submitted_receipt_report",
              "public_task": public, "provider_copy_sha256": digest(provider),
              "submitted_claim": claim, "submitted_claim_sha256": digest(claim),
              "auditor_decision": decision}
    refs = {case: reference(case) for case in ("good", "bad")}
    if [independent_score(report, refs[case]) for case in ("good", "bad")] != ["PASS", "FAIL"]:
        raise AssertionError("protected GOOD/BAD calibration changed")
    return report, refs


class ReceiptReplay(ReplayRun):
    """Use the pinned native transaction harness with the receipt report digest."""

    report_digest: str
    refs: dict[str, dict[str, Any]]
    report: dict[str, Any]

    def run_pair(self, case: str) -> dict[str, Any]:
        truth = independent_score(self.report, self.refs[case])
        prefix = f"receipt_{case}"
        preparation_start = len(self.transactions)
        job_id, _ = self.create_funded(prefix, "protected receipt report " + self.report_digest)
        self.submit(prefix, job_id, self.report_digest)
        preparation = self.branch_transactions(preparation_start, "preparation")
        submitted = [log for log in preparation[-1]["logs"] if log["name"] == "JobSubmitted"]
        if len(submitted) != 1 or submitted[0]["data"].lower() != "0x" + self.report_digest:
            raise AssertionError("native ERC submission does not bind the report digest")
        before = self.prestate(job_id)
        snapshot_id = self.rpc.call("evm_snapshot")
        attestation = "0x" + digest(self.report["auditor_decision"])

        first = len(self.transactions)
        self.send(prefix + ".default.complete", "evaluator", "complete(uint256,bytes32,bytes)",
                  job_id, attestation, "0x",
                  events=("JobCompleted", "PaymentReleased", "EvaluatorFeePaid", "PlatformFeePaid"))
        default_state = self.prestate(job_id)
        self.assert_delta(before["token_state"], default_state["token_state"],
                          escrow=-BUDGET, provider=17 * UNIT, evaluator=2 * UNIT, treasury=UNIT)
        default_txs = self.branch_transactions(first, "default")
        if self.rpc.call("evm_revert", [snapshot_id]) is not True:
            raise AssertionError("failed to restore ERC paired prestate")
        restored = self.prestate(job_id)
        if restored != before:
            raise AssertionError("ERC paired prestates differ")

        # This is a trusted application dispatcher with private warehouse access.
        # Its oracle access is deliberately outside the ERC-8183 contract.
        allow = truth == "PASS" and self.report["auditor_decision"]["verdict"] == "ACCEPT"
        first = len(self.transactions)
        if allow:
            self.send(prefix + ".guard.complete", "evaluator", "complete(uint256,bytes32,bytes)",
                      job_id, attestation, "0x",
                      events=("JobCompleted", "PaymentReleased", "EvaluatorFeePaid", "PlatformFeePaid"))
        else:
            self.send(prefix + ".guard.reject", "evaluator", "reject(uint256,bytes32,bytes)",
                      job_id, "0x" + digest({"report": self.report_digest, "truth": truth}), "0x",
                      events=("JobRejected", "Refunded"))
        guarded = self.prestate(job_id)
        guarded_txs = self.branch_transactions(first, "application_guard")
        if allow:
            self.assert_delta(before["token_state"], guarded["token_state"],
                              escrow=-BUDGET, provider=17 * UNIT, evaluator=2 * UNIT, treasury=UNIT)
        else:
            self.assert_delta(before["token_state"], guarded["token_state"],
                              escrow=-BUDGET, client=BUDGET)
        if guarded["job"]["status"] != ("Completed" if allow else "Rejected"):
            raise AssertionError("ERC guard final state changed")
        return {"case": case, "report_sha256": self.report_digest, "oracle_status": truth,
                "job_id": job_id, "submitted_event": submitted[0],
                "preparation_transactions": preparation, "snapshot_id": snapshot_id,
                "prestate": before, "restored_prestate": restored,
                "default": {"transactions": default_txs, "final_state": default_state},
                "application_guard": {"oracle_origin": "PRIVATE_WAREHOUSE_IDEAL_UPPER_BOUND",
                                      "allow_complete": allow, "transactions": guarded_txs,
                                      "final_state": guarded}}


def run(output: Path, port_base: int) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(output)
    if not 1024 < port_base < 65480:
        raise ValueError("port base outside loopback range")
    report, refs = freeze()
    output.mkdir(parents=True)
    (output / "receipt-report.json").write_bytes(canonical(report) + b"\n")
    (output / "private-warehouse-reference.json").write_bytes(canonical(refs) + b"\n")
    report_hash = digest(report)
    erc = ReceiptReplay(output / "erc8183", port_base)
    erc.report, erc.refs, erc.report_digest = report, refs, report_hash
    native_erc = erc.execute_replay()
    native_erc.update({"work_order": "CROSSRAIL_RECEIPT_CONTROL", "study_type": "SCRIPTED_OFFLINE_CONTROL",
                       "report_sha256": report_hash,
                       "model_behavior_tier": "SCRIPTED_SIMULATION",
                       "payment_tier": "NATIVE_LOCAL_PROTOCOL"})
    (output / "erc8183" / "evidence.json").write_text(json.dumps(native_erc, sort_keys=True, indent=2) + "\n")
    cases = {}
    for index, case in enumerate(("good", "bad")):
        case_dir = output / case
        case_dir.mkdir()
        native_path = case_dir / "x402-native.json"
        result = subprocess.run(["node", str(ROOT / "scripts" / "run_x402_local.mjs"),
                                 "--port", str(port_base + 20 + index * 20),
                                 "--resource-record-file", str(output / "receipt-report.json"),
                                 "--output", str(native_path)], cwd=ROOT, capture_output=True,
                                text=True, timeout=120, check=False)
        (case_dir / "x402.stdout.txt").write_text(result.stdout)
        (case_dir / "x402.stderr.txt").write_text(result.stderr)
        if result.returncode:
            raise RuntimeError(f"x402 {case} failed; see {case_dir / 'x402.stderr.txt'}")
        native_x402 = json.loads(native_path.read_text())
        x402 = _x402_consequence(native_x402, report)
        erc_case = native_erc["pairs"][case]
        truth = independent_score(report, refs[case])
        if erc_case["report_sha256"] != report_hash or x402["resource_record_sha256"] != report_hash:
            raise AssertionError("cross-rail report digest diverged")
        cases[case] = {"independent_oracle_status": truth, "report_sha256": report_hash,
                       "auditor_verdict": "ACCEPT", "auditor_checked": False,
                       "erc8183": {"job_id": erc_case["job_id"],
                                   "default_job_status": erc_case["default"]["final_state"]["job"]["status"],
                                   "default_provider_delta": 17 * UNIT,
                                   "guard_job_status": erc_case["application_guard"]["final_state"]["job"]["status"],
                                   "guard_provider_delta": 17 * UNIT if truth == "PASS" else 0},
                       "x402": x402,
                       "application_outcomes": {
                           "wrongful_erc_provider_payment": truth == "FAIL",
                           "x402_report_delivery_paid": x402["seller_delta_minor_units"] > 0,
                           "x402_semantic_correctness_enforced": False}}
    summary = {"schema_version": 1, "study_type": "SCRIPTED_OFFLINE_CROSSRAIL_RECEIPT_CONTROL",
               "status": "PASS", "model_behavior_tier": "SCRIPTED_SIMULATION",
               "transaction_execution_tier": "NATIVE_LOCAL_PROTOCOL", "report_sha256": report_hash,
               "frozen_reference_source": "tests/test_protected_receipts.py::make_case,ARTIFACT",
               "frozen_reference_source_file_sha256": FROZEN_TEST_SHA256,
               "frozen_task_source_file_sha256": FROZEN_TASK_SHA256,
               "cases": cases, "mpp": {"status": "SKIP", "reason": "MPP receipt-specific adapter not run"},
               "ap2": {"status": "SKIP", "reason": "delegated authorization is outside this payment control"},
               "acp_retail": {"status": "SKIP", "reason": "retail checkout is outside this payment control"},
               "limitations": ["No LLM behavior or collusion inference.",
                               "The private warehouse guard is an ideal application upper bound.",
                               "x402 pays for HTTP delivery; its signature does not attest to report truth.",
                               "ERC snapshot branches are not both on one canonical final chain.",
                               "Only disposable local tokens and localhost RPC were used."]}
    (output / "summary.json").write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port-base", type=int, default=18450)
    args = parser.parse_args()
    result = run(args.output.resolve(), args.port_base)
    print(json.dumps({"status": result["status"], "report_sha256": result["report_sha256"],
                      "output": str(args.output.resolve())}))


if __name__ == "__main__":
    main()
