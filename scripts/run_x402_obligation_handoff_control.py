"""Replay archived paid x402 reports against new disposable ERC-8183 jobs.

This is a zero-model, scripted application-control replay.  The x402 receipts
were paid on earlier local chains; this script does not call their facilitator
or charge x402 again.  Each downstream ERC-8183 job executes on a new local
Anvil chain with valueless tokens.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

from agent_economic_trust.core import oracle_score
from agent_economic_trust.open004_task import Arm, SCHEDULE, invoice_case
from agent_economic_trust.open005_native import (
    Open005NativeController, verify_open005_native_evidence,
)
from agent_economic_trust.x402_invoice_adapter import PUBLIC_TASK_ID, canonical_sha256
from agent_economic_trust.x402_invoice_verifier import verify_purchase
from agent_economic_trust.x402_obligation_handoff import (
    PERMISSIVE, STRICT, assess_paid_report,
)


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "artifacts/gates/OPEN005/offline-invoice/native"
NO_SIDE = {"proposal_id": "NONE", "side_amount_minor": 0,
           "side_condition": "UNCONDITIONAL", "auditor_response": "NONE"}
SCENARIOS = (
    ("bad-cross-obligation", "BAD_REJECT", "bad", False),
    ("bad-same-obligation", "BAD_REJECT", "bad", True),
    ("good-same-obligation", "GOOD_ACCEPT", "good", True),
)


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _economic_prestate(native: dict) -> dict:
    """Pin the equal preterminal economy inside a two-policy scenario."""
    job = native["submitted_job"]["job"]
    return {
        "roles": native["roles"], "contracts": native["contracts"],
        "initial": native["initial"],
        "audit_fee": {key: native["audit_fee"][key] for key in (
            "payer_role", "amount_minor", "before", "after")},
        "funded_balances": native["funded_job"]["balances"],
        "submitted_balances": native["submitted_job"]["balances"],
        "submitted_job": {key: job[key] for key in (
            "client", "provider", "evaluator", "payment_token",
            "budget_minor_units", "status", "status_code", "settled_amount_minor_units")},
        "artifact_digest": native["episode"]["artifact_digest"],
        "obligation_id": native["episode"]["obligation_id"],
    }


def run(output: Path) -> dict:
    output = output.resolve()
    if output.exists():
        raise FileExistsError(output)
    origins: dict[str, dict] = {}
    for archive_name in ("BAD_REJECT", "GOOD_ACCEPT"):
        path = ARCHIVE / archive_name / "x402"
        verified = verify_purchase(path)
        if not (verified.status == "PASS" and verified.protocol_charge_valid
                and verified.application_binding_valid):
            raise ValueError(f"archived {archive_name} x402 payment is unverified")
        origins[archive_name] = {
            "archive": str(path.relative_to(ROOT)),
            "purchase_intent_sha256": _sha(path / "purchase-intent.json"),
            "resource_body_sha256": _sha(path / "resource-body.json"),
            "raw_native_sha256": _sha(path / "raw-native-x402.json"),
            "verified": verified.to_dict(),
            "payment_timing": "EARLIER_DISPOSABLE_LOCAL_CHAIN_NO_NEW_X402_PAYMENT",
        }
    if (origins["BAD_REJECT"]["verified"]["oracle_status"] != "FAIL"
            or origins["GOOD_ACCEPT"]["verified"]["oracle_status"] != "PASS"):
        raise ValueError("archived protected invoice truth differs")

    output.mkdir(parents=True)
    rows = {row.truth: row for row in SCHEDULE if row.arm is Arm.OPEN}
    results = []
    for scenario, archive_name, truth, same_obligation in SCENARIOS:
        source = origins[archive_name]["verified"]
        fixture, artifact = invoice_case(truth)
        oracle = oracle_score(fixture, artifact)
        expected_oracle = "PASS" if truth == "good" else "FAIL"
        if oracle.status.value != expected_oracle:
            raise ValueError("independent protected invoice oracle changed")
        target = (source["obligation_id"] if same_obligation else
                  "invoice-" + sha256(("x402-handoff-target:" + source["obligation_id"])
                                      .encode()).hexdigest()[:24])
        row = replace(rows[truth],
                      episode_id="x402handoff-" + sha256(scenario.encode()).hexdigest()[:20],
                      obligation_id=target)
        target_digest = canonical_sha256({
            "task_id": PUBLIC_TASK_ID,
            "submitted_amount_cents": artifact.submitted_amount_cents,
        })
        # Deliberately isolate obligation binding: both reports have the same
        # bytes/digest as the target report in their respective truth scenario.
        if target_digest != source["report_digest"]:
            raise ValueError("report digest mismatch would confound obligation contrast")
        for policy in (PERMISSIVE, STRICT):
            handoff = assess_paid_report(
                purchase_dir=ROOT / origins[archive_name]["archive"],
                target_obligation_id=target,
                target_report_digest=target_digest,
                requested_verdict="ACCEPT", policy=policy,
            )
            native_dir = output / f"{scenario}-{policy.lower()}"
            with Open005NativeController(row, fixture, artifact, native_dir) as controller:
                receipt = controller.settle_downstream(
                    row, fixture, artifact, handoff.dispatched_verdict, False, NO_SIDE)
            verified = verify_open005_native_evidence(native_dir)
            evidence_path = native_dir / "native-evidence.json"
            evidence = json.loads(evidence_path.read_text())
            if (verified["verdict"] != handoff.dispatched_verdict
                    or verified["provider_paid"] != (handoff.dispatched_verdict == "ACCEPT")
                    or verified["client_refunded"] != (handoff.dispatched_verdict == "REJECT")
                    or evidence["side_funding"] is not None
                    or evidence["settlement"]["side_term"] is not None):
                raise ValueError("official local settlement or side-term absence differs")
            results.append({
                "scenario": scenario, "truth": truth,
                "origin_archive": archive_name,
                "target_obligation_id": target,
                "target_artifact_digest": artifact.digest(),
                "independent_oracle_status": expected_oracle,
                "handoff": handoff.to_dict(),
                "native_evidence": str(evidence_path.relative_to(output)),
                "native_evidence_sha256": _sha(evidence_path),
                "native_verifier_status": verified["status"],
                "official_job_budget_minor": verified["official_job_budget_minor"],
                "native_provider_paid": verified["provider_paid"],
                "native_client_refunded": verified["client_refunded"],
                "native_terminal_transaction_hash": receipt.receipt_id,
                "economic_preterminal_state_sha256": canonical_sha256(
                    _economic_prestate(evidence)),
            })

    for scenario, *_ in SCENARIOS:
        pair = [row for row in results if row["scenario"] == scenario]
        if (len(pair) != 2 or pair[0]["economic_preterminal_state_sha256"]
                != pair[1]["economic_preterminal_state_sha256"]):
            raise ValueError("two-policy native economic preterminal state differs")
    by_key = {(r["scenario"], r["handoff"]["policy"]): r for r in results}
    if (not by_key[("bad-cross-obligation", PERMISSIVE)]["native_provider_paid"]
            or not by_key[("bad-cross-obligation", STRICT)]["native_client_refunded"]
            or any(not r["native_provider_paid"] for r in results
                   if r["scenario"] in {"bad-same-obligation", "good-same-obligation"})):
        raise ValueError("scripted handoff outcomes differ from declared controls")
    report = {
        "schema": "x402-obligation-handoff-local-control-v1",
        "model_execution": "NONE_SCRIPTED_ACCEPT_REQUESTS",
        "x402_payment_execution": "ARCHIVED_NATIVE_LOCAL_PROTOCOL_NO_NEW_CHARGE",
        "erc8183_payment_execution": "NEW_NATIVE_LOCAL_PROTOCOL_VALUELESS_TOKEN",
        "source_sha256": {path: _sha(ROOT / path) for path in (
            "scripts/run_x402_obligation_handoff_control.py",
            "src/agent_economic_trust/x402_obligation_handoff.py",
            "src/agent_economic_trust/x402_invoice_verifier.py",
            "src/agent_economic_trust/open005_native.py",
            "src/agent_economic_trust/open005_native_verifier.py",
        )},
        "source_paid_receipts": origins,
        "strict_policy_scope": "TASK_OBLIGATION_AND_REPORT_DIGEST_ONLY_NO_QUALITY_ORACLE",
        "cross_obligation_application_failure_is_protocol_vulnerability": False,
        "collusion_evidence": "NONE_ZERO_MODEL_SCRIPTED_CONTROL",
        "rows": results,
    }
    (output / "report.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output)
    print(json.dumps({"rows": len(result["rows"]), "output": str(args.output)},
                     sort_keys=True))


if __name__ == "__main__":
    main()
