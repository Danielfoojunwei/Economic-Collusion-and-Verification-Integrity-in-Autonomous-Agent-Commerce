"""Zero-model ACP mock checkout to native ERC-8183 audit handoff control."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from agent_economic_trust.core import oracle_score
from agent_economic_trust.open004_task import Arm, SCHEDULE, invoice_case
from agent_economic_trust.open005_native import Open005NativeController
from protocols.acp_retail.audit_handoff_control import (
    dispatch_invoice_verdict, execute_mock_checkout,
)


ROOT = Path(__file__).resolve().parents[1]
ACP_UPSTREAM = Path("/workspace/upstreams/w17-acp-retail")
ACP_PIN = "7fdd78df677a94dce04c770644b0fbbb1401272b"
ACP_SCHEMA_SHA256 = "d0e4290617d66bf05d002b8ace388732be2b3eb9a92a1003db7a2daa1e0436f2"
ACP_EXAMPLE_SHA256 = "989e4bc7ccbdb789ea362450963821a368da63d20a2000186455fa7fbcaac8e7"
NO_SIDE = {"proposal_id": "NONE", "side_amount_minor": 0,
           "side_condition": "UNCONDITIONAL", "auditor_response": "NONE"}
ROW_PLAN = (
    ("cross_bad_permissive", "a", "bad", False),
    ("cross_bad_strict", "a", "bad", True),
    ("bound_bad_strict", "b_bad", "bad", True),
    ("bound_good_strict", "b_good", "good", True),
)


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def source_gate() -> dict:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ACP_UPSTREAM,
                          check=True, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ACP_UPSTREAM,
                           check=True, capture_output=True, text=True).stdout.strip()
    schema = ACP_UPSTREAM / "spec/2026-04-17/json-schema/schema.agentic_checkout.json"
    examples = ACP_UPSTREAM / "examples/2026-04-17/examples.agentic_checkout.json"
    if (head != ACP_PIN or dirty or digest(schema) != ACP_SCHEMA_SHA256
            or digest(examples) != ACP_EXAMPLE_SHA256):
        raise ValueError("released ACP checkout source or schema differs from pin")
    return {
        "acp_upstream_commit": head,
        "acp_schema_sha256": digest(schema),
        "acp_examples_sha256": digest(examples),
        "source_sha256": {str(path.relative_to(ROOT)): digest(path) for path in (
            ROOT / "protocols/acp_retail/audit_handoff_control.py",
            ROOT / "protocols/acp_retail/local_checkout.py",
            ROOT / "scripts/run_acp_audit_handoff_control.py",
            ROOT / "scripts/verify_acp_audit_handoff_control.py",
            ROOT / "src/agent_economic_trust/open005_native.py",
            ROOT / "src/agent_economic_trust/open005_native_verifier.py",
        )},
    }


def preterminal_state(evidence: dict) -> dict:
    """Discard only varying local timestamps and transaction identifiers."""
    job = evidence["submitted_job"]["job"]
    return {
        "roles": evidence["roles"], "contracts": evidence["contracts"],
        "initial": evidence["initial"],
        "audit_fee_payer": evidence["audit_fee"]["payer_role"],
        "audit_fee_amount_minor": evidence["audit_fee"]["amount_minor"],
        "audit_fee_after": evidence["audit_fee"]["after"],
        "funded_balances": evidence["funded_job"]["balances"],
        "submitted_balances": evidence["submitted_job"]["balances"],
        "submitted_job": {key: job[key] for key in (
            "client", "provider", "evaluator", "payment_token",
            "budget_minor_units", "status", "status_code", "settled_amount_minor_units",
        )},
        "artifact_digest": evidence["episode"]["artifact_digest"],
        "obligation_id": evidence["episode"]["obligation_id"],
    }


def run(output: Path) -> dict:
    provenance = source_gate()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    target = {row.truth: row for row in SCHEDULE if row.arm is Arm.OPEN}
    bad_fixture, bad_artifact = invoice_case("bad")
    good_fixture, good_artifact = invoice_case("good")
    purchase_intents = {
        "a": ("independent-audit-purchase-obligation-a",
              sha256(b"separate-audit-report-a").hexdigest()),
        "b_bad": (target["bad"].obligation_id, bad_artifact.digest()),
        "b_good": (target["good"].obligation_id, good_artifact.digest()),
    }
    checkout: dict[str, dict] = {}
    for name, (obligation_id, artifact_digest) in purchase_intents.items():
        evidence = execute_mock_checkout(ACP_UPSTREAM, obligation_id=obligation_id,
                                         artifact_digest=artifact_digest)
        path = output / f"checkout-{name}.json"
        path.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n")
        checkout[name] = evidence

    rows = []
    for row_id, checkout_name, truth, strict in ROW_PLAN:
        assignment = target[truth]
        fixture, artifact = invoice_case(truth)
        oracle = oracle_score(fixture, artifact)
        decision = dispatch_invoice_verdict(
            checkout=checkout[checkout_name],
            target_obligation_id=assignment.obligation_id,
            target_artifact_digest=artifact.digest(),
            oracle_status=oracle.status.value if strict else None,
            strict=strict,
        )
        native_dir = output / f"erc8183-{row_id}"
        with Open005NativeController(assignment, fixture, artifact, native_dir) as native:
            receipt = native.settle_downstream(
                assignment, fixture, artifact, decision["verdict"],
                decision["oracle_consulted"], NO_SIDE)
        evidence = json.loads((native_dir / "native-evidence.json").read_text())
        prestate = preterminal_state(evidence)
        rows.append({
            "row_id": row_id, "target_truth": truth,
            "target_obligation_id": assignment.obligation_id,
            "target_artifact_digest": artifact.digest(),
            "checkout_name": checkout_name,
            "checkout_evidence_sha256": digest(output / f"checkout-{checkout_name}.json"),
            "adapter": "strict" if strict else "permissive",
            "scripted_requested_verdict": "ACCEPT",
            "independent_oracle_status": oracle.status.value,
            "application_decision": decision,
            "native_evidence_sha256": digest(native_dir / "native-evidence.json"),
            "native_terminal_transaction_hash": receipt.receipt_id,
            "native_provider_paid": evidence["settlement"]["provider_paid"],
            "native_client_refunded": evidence["settlement"]["client_refunded"],
            "native_preterminal_state_sha256": sha256(json.dumps(
                prestate, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        })
    if len({r["native_preterminal_state_sha256"] for r in rows
            if r["target_truth"] == "bad"}) != 1:
        raise ValueError("BAD counterfactual ERC-8183 preterminal states differ")
    report = {
        "schema": "acp-order-audit-handoff-control-v1",
        "provenance": provenance,
        "model_execution_tier": "SCRIPTED_SIMULATION; no model call",
        "acp_checkout_execution_tier": "SCRIPTED_SIMULATION",
        "acp_payment_execution": "NONE; sample payment data handled by local mock only",
        "erc8183_transaction_execution_tier": "NATIVE_LOCAL_PROTOCOL",
        "erc8183_asset": "valueless disposable local MockUSDC",
        "policy_origin": "SCRIPTED_APPLICATION_ADAPTER_NOT_PROTOCOL_GUARANTEE",
        "collusion_or_named_protocol_exploit_claim": "NONE",
        "rows": rows,
    }
    (output / "report.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.output)
    print(json.dumps({"rows": len(report["rows"]), "output": str(args.output)},
                     sort_keys=True))


if __name__ == "__main__":
    main()
