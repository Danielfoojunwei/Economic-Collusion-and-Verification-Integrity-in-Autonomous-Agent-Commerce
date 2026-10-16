"""Four zero-model, valueless AP2 authorization/official ERC-8183 local controls."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

from agent_economic_trust.ap2_invoice_control import dispatch_invoice_verdict
from agent_economic_trust.core import oracle_score
from agent_economic_trust.open004_task import Arm, SCHEDULE, invoice_case
from agent_economic_trust.open005_native import (
    Open005NativeController, verify_open005_native_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
AP2_PYTHON = Path("/workspace/upstreams/ap2-w15/.venv/bin/python")
AP2_SOURCE = Path("/workspace/upstreams/ap2-w15")
AP2_PIN = "b4587ac1d055888a73b4b21750973cffba961793"
NO_SIDE = {"proposal_id": "NONE", "side_amount_minor": 0,
           "side_condition": "UNCONDITIONAL", "auditor_response": "NONE"}


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def economic_prestate(evidence: dict) -> dict:
    """Compare values and job binding; local block times and tx IDs may differ."""
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


def ap2_command(*args: str) -> None:
    environment = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1"}
    subprocess.run([str(AP2_PYTHON), "-m", "scripts.ap2_invoice_authorization", *args],
                   cwd=ROOT, env=environment, check=True, timeout=45)


def source_gate() -> dict:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=AP2_SOURCE,
                          check=True, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=AP2_SOURCE,
                           check=True, capture_output=True, text=True).stdout.strip()
    if head != AP2_PIN or dirty or not AP2_PYTHON.is_file():
        raise ValueError("official AP2 v0.2 checkout or SDK environment differs")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          check=True, capture_output=True, text=True).stdout.strip()
    return {"control_base_commit": base, "ap2_upstream_commit": head,
            "ap2_upstream_clean": True,
            "source_sha256": {str(path.relative_to(ROOT)): digest(path) for path in (
                ROOT / "scripts/ap2_invoice_authorization.py",
                ROOT / "scripts/run_ap2_invoice_erc8183_control.py",
                ROOT / "src/agent_economic_trust/ap2_invoice_control.py",
                ROOT / "src/agent_economic_trust/open005_native.py",
                ROOT / "src/agent_economic_trust/open005_native_verifier.py",
            )}}


def run(output: Path) -> dict:
    provenance = source_gate()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    rows = {row.truth: row for row in SCHEDULE if row.arm is Arm.OPEN}
    results = []
    for truth in ("good", "bad"):
        row = rows[truth]
        fixture, artifact = invoice_case(truth)
        other = rows["bad" if truth == "good" else "good"]
        ap2_path = output / f"ap2-{truth}.json"
        ap2_command("issue", "--obligation", row.obligation_id,
                    "--artifact-digest", artifact.digest(),
                    "--cross-obligation", other.obligation_id,
                    "--output", str(ap2_path))
        ap2_command("verify", str(ap2_path))
        ap2 = json.loads(ap2_path.read_text())
        if (ap2["purchase_intent"]["invoice_obligation_id"] != row.obligation_id
                or ap2["purchase_intent"]["invoice_artifact_digest"] != artifact.digest()
                or not ap2["verification"]["valid_in_scope"]
                or not ap2["verification"]["cross_obligation_rejected"]):
            raise ValueError("signed purchase authorization is not bound to this invoice")
        oracle = oracle_score(fixture, artifact)
        for adapter in ("permissive", "strict"):
            native_path = output / f"erc8183-{truth}-{adapter}"
            dispatch = dispatch_invoice_verdict(
                requested_verdict="ACCEPT", ap2_purchase_authorized=True,
                oracle_status=oracle.status if adapter == "strict" else None,
                strict=adapter == "strict",
            )
            with Open005NativeController(row, fixture, artifact, native_path) as controller:
                receipt = controller.settle_downstream(
                    row, fixture, artifact, dispatch, False, NO_SIDE)
            verified = verify_open005_native_evidence(native_path)
            evidence = json.loads((native_path / "native-evidence.json").read_text())
            if (verified["verdict"] != dispatch
                    or verified["provider_paid"] != (dispatch == "ACCEPT")
                    or verified["client_refunded"] != (dispatch == "REJECT")
                    or evidence["side_funding"] is not None
                    or evidence["settlement"]["side_term"] is not None):
                raise ValueError("native verifier or absence of side term differs")
            results.append({
                "truth": truth, "adapter": adapter,
                "obligation_id": row.obligation_id,
                "artifact_digest": artifact.digest(),
                "ap2_evidence": ap2_path.name, "ap2_evidence_sha256": digest(ap2_path),
                "ap2_authorization_reference": ap2["authorization_reference"],
                "ap2_authorized_audit_service_purchase": True,
                "ap2_authorized_invoice_quality": False,
                "scripted_requested_verdict": "ACCEPT",
                "application_oracle_status": oracle.status.value if adapter == "strict" else "NOT_CONSULTED",
                "application_dispatched_verdict": dispatch,
                "native_evidence": str(native_path.relative_to(output) / "native-evidence.json"),
                "native_evidence_sha256": digest(native_path / "native-evidence.json"),
                "native_verifier_status": verified["status"],
                "official_erc8183_job_budget_minor": verified["official_job_budget_minor"],
                "native_provider_paid": verified["provider_paid"],
                "native_client_refunded": verified["client_refunded"],
                "native_terminal_transaction_hash": receipt.receipt_id,
                "economic_preterminal_state_sha256": sha256(json.dumps(
                    economic_prestate(evidence), sort_keys=True,
                    separators=(",", ":")).encode()).hexdigest(),
            })
    for truth in ("good", "bad"):
        pair = [item for item in results if item["truth"] == truth]
        if (len(pair) != 2 or pair[0]["economic_preterminal_state_sha256"]
                != pair[1]["economic_preterminal_state_sha256"]):
            raise ValueError("counterfactual native economic preterminal states differ")
    if not (all(r["native_provider_paid"] for r in results if r["truth"] == "good")
            and next(r for r in results if r["truth"] == "bad" and r["adapter"] == "permissive")["native_provider_paid"]
            and next(r for r in results if r["truth"] == "bad" and r["adapter"] == "strict")["native_client_refunded"]):
        raise ValueError("expected local control outcomes differ")
    report = {
        "schema": "ap2-invoice-erc8183-local-control-v1",
        "provenance": provenance,
        "model_execution": "NONE; scripted ACCEPT requests only",
        "ap2_payment_execution": "NONE; signed purchase authorization only",
        "transaction_execution_tier": "NATIVE_LOCAL_PROTOCOL",
        "erc8183_asset": "valueless disposable local MockUSDC",
        "ap2_invoice_quality_authority": "NONE",
        "strict_guard_origin": "APPLICATION_ORACLE_BOUND_COUNTERFACTUAL",
        "ap2_vs_erc8183_boundary": "valid audit-service purchase authorization does not certify invoice quality",
        "causal_or_named_protocol_vulnerability_claim": "NONE",
        "rows": results,
    }
    (output / "report.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.output)
    print(json.dumps({"rows": len(report["rows"]), "output": str(args.output)}, sort_keys=True))


if __name__ == "__main__":
    main()
