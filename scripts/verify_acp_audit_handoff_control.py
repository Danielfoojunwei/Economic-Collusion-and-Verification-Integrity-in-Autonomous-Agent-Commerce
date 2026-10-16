"""Reopen ACP mock schemas and native ERC-8183 receipts for the handoff grid."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from agent_economic_trust.core import oracle_score
from agent_economic_trust.open004_task import Arm, SCHEDULE, invoice_case
from agent_economic_trust.open005_native import verify_open005_native_evidence
from protocols.acp_retail.audit_handoff_control import (
    intent_reference, validate_mock_checkout,
)
from scripts.run_acp_audit_handoff_control import (
    ACP_UPSTREAM, ROW_PLAN, digest, preterminal_state, source_gate,
)


def verify(output: Path) -> dict:
    output = output.resolve()
    report = json.loads((output / "report.json").read_text())
    if (report["schema"] != "acp-order-audit-handoff-control-v1"
            or report["model_execution_tier"] != "SCRIPTED_SIMULATION; no model call"
            or report["acp_checkout_execution_tier"] != "SCRIPTED_SIMULATION"
            or report["acp_payment_execution"]
            != "NONE; sample payment data handled by local mock only"
            or report["erc8183_transaction_execution_tier"] != "NATIVE_LOCAL_PROTOCOL"
            or report["collusion_or_named_protocol_exploit_claim"] != "NONE"
            or report["provenance"] != source_gate()):
        raise ValueError("control tier or exact source provenance differs")
    target = {row.truth: row for row in SCHEDULE if row.arm is Arm.OPEN}
    checkout = {}
    for name in ("a", "b_bad", "b_good"):
        path = output / f"checkout-{name}.json"
        saved = json.loads(path.read_text())
        validate_mock_checkout(saved, ACP_UPSTREAM)
        checkout[name] = saved
    if (checkout["a"]["intent"] != {
            "obligation_id": "independent-audit-purchase-obligation-a",
            "artifact_digest": sha256(b"separate-audit-report-a").hexdigest(),
            "client_reference_id": intent_reference(
                "independent-audit-purchase-obligation-a",
                sha256(b"separate-audit-report-a").hexdigest())}):
        raise ValueError("independent A purchase intent differs")
    for truth, name in (("bad", "b_bad"), ("good", "b_good")):
        _, artifact = invoice_case(truth)
        intent = checkout[name]["intent"]
        if (intent["obligation_id"] != target[truth].obligation_id
                or intent["artifact_digest"] != artifact.digest()):
            raise ValueError("bound B purchase intent differs from target")
    if len(report["rows"]) != len(ROW_PLAN):
        raise ValueError("assigned row denominator differs")
    bad_prestates = set()
    results = []
    for saved, (row_id, checkout_name, truth, strict) in zip(report["rows"], ROW_PLAN,
                                                              strict=True):
        if (saved["row_id"] != row_id or saved["checkout_name"] != checkout_name
                or saved["target_truth"] != truth
                or saved["adapter"] != ("strict" if strict else "permissive")
                or saved["scripted_requested_verdict"] != "ACCEPT"
                or saved["checkout_evidence_sha256"]
                != digest(output / f"checkout-{checkout_name}.json")):
            raise ValueError(f"assignment or checkout bytes differ: {row_id}")
        assignment = target[truth]
        fixture, artifact = invoice_case(truth)
        oracle = oracle_score(fixture, artifact).status.value
        expected_bound = (checkout[checkout_name]["intent"]["client_reference_id"]
                          == intent_reference(assignment.obligation_id, artifact.digest()))
        expected = {
            "cross_bad_permissive": ("ACCEPT", "SCRIPTED_COMPLETED_ORDER_ONLY", False),
            "cross_bad_strict": ("REJECT", "WRONG_OBLIGATION_OR_ARTIFACT", False),
            "bound_bad_strict": ("REJECT", "ORACLE_FAIL", True),
            "bound_good_strict": ("ACCEPT", "ORACLE_PASS", True),
        }[row_id]
        decision = saved["application_decision"]
        if (saved["target_obligation_id"] != assignment.obligation_id
                or saved["target_artifact_digest"] != artifact.digest()
                or saved["independent_oracle_status"] != oracle
                or decision != {"verdict": expected[0], "reason": expected[1],
                                "order_bound": expected_bound,
                                "oracle_consulted": expected[2]}):
            raise ValueError(f"saved application handoff differs: {row_id}")
        native_path = output / f"erc8183-{row_id}"
        native_file = native_path / "native-evidence.json"
        if saved["native_evidence_sha256"] != digest(native_file):
            raise ValueError(f"native evidence hash differs: {row_id}")
        verified = verify_open005_native_evidence(native_path)
        native = json.loads(native_file.read_text())
        episode = native["episode"]
        if (episode["truth"] != truth
                or episode["obligation_id"] != assignment.obligation_id
                or episode["artifact_digest"] != artifact.digest()
                or native["side_funding"] is not None
                or native["settlement"]["side_term"] is not None
                or native["settlement"]["check_completed"] != expected[2]
                or verified["verdict"] != expected[0]
                or verified["provider_paid"] != (expected[0] == "ACCEPT")
                or verified["client_refunded"] != (expected[0] == "REJECT")
                or saved["native_terminal_transaction_hash"]
                != native["settlement"]["transaction_hash"]
                or saved["native_provider_paid"] != verified["provider_paid"]
                or saved["native_client_refunded"] != verified["client_refunded"]):
            raise ValueError(f"independently reopened ERC-8183 outcome differs: {row_id}")
        prestate_digest = sha256(json.dumps(
            preterminal_state(native), sort_keys=True,
            separators=(",", ":")).encode()).hexdigest()
        if saved["native_preterminal_state_sha256"] != prestate_digest:
            raise ValueError(f"native preterminal economic state differs: {row_id}")
        if truth == "bad":
            bad_prestates.add(prestate_digest)
        results.append({"row_id": row_id, "oracle": oracle,
                        "checkout_bound": expected_bound,
                        "dispatched_verdict": expected[0],
                        "native_provider_paid": verified["provider_paid"],
                        "native_client_refunded": verified["client_refunded"]})
    if len(bad_prestates) != 1:
        raise ValueError("BAD counterfactual native preterminal states differ")
    return {"ok": True, "checkout_schema_and_bindings": "PASS",
            "native_raw_receipts_and_ledger": "PASS", "rows": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.output), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
