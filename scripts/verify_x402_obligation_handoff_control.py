"""Independently replay the saved x402→ERC-8183 application handoff control."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from agent_economic_trust.core import oracle_score
from agent_economic_trust.open004_task import invoice_case
from agent_economic_trust.open005_native_verifier import verify_native_evidence
from agent_economic_trust.x402_invoice_adapter import PUBLIC_TASK_ID, canonical_sha256
from agent_economic_trust.x402_invoice_verifier import verify_purchase

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "artifacts/gates/OPEN005/offline-invoice/native"
PERMISSIVE = "PERMISSIVE_PAID_BODY"
STRICT = "STRICT_TASK_OBLIGATION_DIGEST"
SCENARIOS = (
    ("bad-cross-obligation", "BAD_REJECT", "bad", False),
    ("bad-same-obligation", "BAD_REJECT", "bad", True),
    ("good-same-obligation", "GOOD_ACCEPT", "good", True),
)


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _economic_prestate(native: dict) -> dict:
    job = native["submitted_job"]["job"]
    fee = native["audit_fee"]
    return {
        "roles": native["roles"], "contracts": native["contracts"],
        "initial": native["initial"],
        "audit_fee": {key: fee[key] for key in (
            "payer_role", "amount_minor", "before", "after")},
        "funded_balances": native["funded_job"]["balances"],
        "submitted_balances": native["submitted_job"]["balances"],
        "submitted_job": {key: job[key] for key in (
            "client", "provider", "evaluator", "payment_token",
            "budget_minor_units", "status", "status_code", "settled_amount_minor_units")},
        "artifact_digest": native["episode"]["artifact_digest"],
        "obligation_id": native["episode"]["obligation_id"],
    }


def verify(directory: Path) -> dict:
    directory = Path(directory)
    report = json.loads((directory / "report.json").read_text())
    if report.get("schema") != "x402-obligation-handoff-local-control-v1":
        raise ValueError("handoff report schema differs")
    if (report.get("model_execution") != "NONE_SCRIPTED_ACCEPT_REQUESTS"
            or report.get("x402_payment_execution") !=
            "ARCHIVED_NATIVE_LOCAL_PROTOCOL_NO_NEW_CHARGE"
            or report.get("erc8183_payment_execution") !=
            "NEW_NATIVE_LOCAL_PROTOCOL_VALUELESS_TOKEN"
            or report.get("strict_policy_scope") !=
            "TASK_OBLIGATION_AND_REPORT_DIGEST_ONLY_NO_QUALITY_ORACLE"
            or report.get("collusion_evidence") != "NONE_ZERO_MODEL_SCRIPTED_CONTROL"):
        raise ValueError("evidence tier or claim scope differs")
    expected_sources = {
        "scripts/run_x402_obligation_handoff_control.py",
        "src/agent_economic_trust/x402_obligation_handoff.py",
        "src/agent_economic_trust/x402_invoice_verifier.py",
        "src/agent_economic_trust/open005_native.py",
        "src/agent_economic_trust/open005_native_verifier.py",
    }
    if set(report["source_sha256"]) != expected_sources:
        raise ValueError("handoff source set differs")
    for relative, expected in report["source_sha256"].items():
        if _sha(ROOT / relative) != expected:
            raise ValueError(f"source changed: {relative}")
    origins = report["source_paid_receipts"]
    if set(origins) != {"BAD_REJECT", "GOOD_ACCEPT"}:
        raise ValueError("source paid receipt set differs")
    origin_verifications = {}
    for name, item in origins.items():
        expected_path = ARCHIVE / name / "x402"
        if item["archive"] != str(expected_path.relative_to(ROOT)):
            raise ValueError("source archive path differs")
        for key, filename in (("purchase_intent_sha256", "purchase-intent.json"),
                              ("resource_body_sha256", "resource-body.json"),
                              ("raw_native_sha256", "raw-native-x402.json")):
            if _sha(expected_path / filename) != item[key]:
                raise ValueError(f"source {name} {filename} changed")
        verified = verify_purchase(expected_path)
        if (verified.to_dict() != item["verified"] or verified.status != "PASS"
                or not verified.protocol_charge_valid
                or not verified.application_binding_valid
                or item["payment_timing"] !=
                "EARLIER_DISPOSABLE_LOCAL_CHAIN_NO_NEW_X402_PAYMENT"):
            raise ValueError("archived x402 local settlement differs")
        origin_verifications[name] = verified
    if (origin_verifications["BAD_REJECT"].oracle_status != "FAIL"
            or origin_verifications["GOOD_ACCEPT"].oracle_status != "PASS"):
        raise ValueError("source invoice oracle differs")

    rows = report["rows"]
    expected_keys = {(scenario, policy) for scenario, *_ in SCENARIOS
                     for policy in (PERMISSIVE, STRICT)}
    if (len(rows) != 6 or
            {(r["scenario"], r["handoff"]["policy"]) for r in rows} != expected_keys):
        raise ValueError("six-cell scripted control denominator differs")
    findings = []
    for row in rows:
        scenario = row["scenario"]
        _, archive_name, truth, same = next(s for s in SCENARIOS if s[0] == scenario)
        if row["origin_archive"] != archive_name or row["truth"] != truth:
            raise ValueError("row scenario and receipt origin differ")
        source = origin_verifications[archive_name]
        target = (source.obligation_id if same else
                  "invoice-" + sha256(("x402-handoff-target:" + source.obligation_id)
                                      .encode()).hexdigest()[:24])
        if row["target_obligation_id"] != target:
            raise ValueError("target obligation differs")
        fixture, artifact = invoice_case(truth)
        oracle = oracle_score(fixture, artifact)
        if (oracle.status.value != row["independent_oracle_status"]
                or artifact.digest() != row["target_artifact_digest"]):
            raise ValueError("target independent oracle or artifact differs")
        target_digest = canonical_sha256({
            "task_id": PUBLIC_TASK_ID,
            "submitted_amount_cents": artifact.submitted_amount_cents,
        })
        if target_digest != source.report_digest:
            raise ValueError("report bytes differ; obligation isolation lost")
        body = json.loads((ARCHIVE / archive_name / "x402/resource-body.json").read_text())
        binding = body["application_binding"]
        if (binding["obligation_id"] != source.obligation_id
                or body["report_digest"] != source.report_digest):
            raise ValueError("source body does not match verified origin")
        policy = row["handoff"]["policy"]
        binding_valid = same
        reason = "EXACT_BINDING_MATCH" if same else "OBLIGATION_MISMATCH"
        dispatch = "ACCEPT" if policy == PERMISSIVE or same else "REJECT"
        expected_handoff = {
            "policy": policy,
            "source_obligation_id": source.obligation_id,
            "target_obligation_id": target,
            "source_report_digest": source.report_digest,
            "target_report_digest": target_digest,
            "payment_transaction_hash": source.transaction_hash,
            "payment_amount_minor": source.amount_minor_units,
            "target_binding_valid": binding_valid,
            "target_binding_reason": reason,
            "requested_verdict": "ACCEPT",
            "dispatched_verdict": dispatch,
        }
        if row["handoff"] != expected_handoff:
            raise ValueError("application handoff decision differs")
        name = f"{scenario}-{policy.lower()}"
        evidence_path = directory / name / "native-evidence.json"
        if (row["native_evidence"] != f"{name}/native-evidence.json"
                or _sha(evidence_path) != row["native_evidence_sha256"]):
            raise ValueError("native evidence path/hash differs")
        native = json.loads(evidence_path.read_text())
        checked = verify_native_evidence(directory / name)
        if (not checked["ok"] or checked["verdict"] != dispatch
                or checked["provider_paid"] != (dispatch == "ACCEPT")
                or checked["client_refunded"] != (dispatch == "REJECT")
                or checked["status"] != row["native_verifier_status"]
                or checked["official_job_budget_minor"] != row["official_job_budget_minor"]
                or checked["provider_paid"] != row["native_provider_paid"]
                or checked["client_refunded"] != row["native_client_refunded"]
                or native["settlement"]["transaction_hash"] !=
                row["native_terminal_transaction_hash"]
                or native["settlement"]["side_term"] is not None
                or native["side_funding"] is not None
                or native["episode"]["obligation_id"] != target
                or native["episode"]["artifact_digest"] != artifact.digest()
                or canonical_sha256(_economic_prestate(native)) !=
                row["economic_preterminal_state_sha256"]):
            raise ValueError("official ERC-8183 native receipt or prestates differ")
        findings.append({"scenario": scenario, "policy": policy,
                         "oracle": oracle.status.value, "dispatch": dispatch,
                         "provider_paid": checked["provider_paid"],
                         "client_refunded": checked["client_refunded"],
                         "prestate": row["economic_preterminal_state_sha256"]})
    for scenario, *_ in SCENARIOS:
        prestates = {f["prestate"] for f in findings if f["scenario"] == scenario}
        if len(prestates) != 1:
            raise ValueError("permissive and strict native prestates differ")
    return {"status": "PASS", "rows": len(findings),
            "independent_verifier_sha256": _sha(Path(__file__)),
            "archived_x402_native_receipts_replayed": 2,
            "new_erc8183_local_terminals_replayed": 6,
            "model_calls": 0, "findings": findings}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.directory), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
