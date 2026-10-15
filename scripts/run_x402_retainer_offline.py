#!/usr/bin/env python3
"""Four-cell native x402 intake and separate ERC-8183 invoice controls.

All decisions here are scripted. There are zero model/API calls, and the
BAD/ACCEPT rows are payment plumbing stress controls, not collusion findings.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import shutil
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from agent_economic_trust.x402_audit_retainer import (  # noqa: E402
    RetainerAssignment, run_native_intake,
)
from agent_economic_trust.x402_audit_retainer_verifier import (  # noqa: E402
    ReceiptError, verify_intake,
)
from agent_economic_trust.x402_retainer_job import RetainerJob  # noqa: E402
from agent_economic_trust.x402_retainer_job_verifier import (  # noqa: E402
    JobEvidenceError, verify_job,
)


def free_port_block() -> int:
    """Find an idle 32-port loopback block for sequential local services."""
    for base in range(29200, 50000, 40):
        sockets = []
        try:
            for offset in (0, 10, 11, 20):
                sock = socket.socket()
                sock.bind(("127.0.0.1", base + offset))
                sockets.append(sock)
            return base
        except OSError:
            continue
        finally:
            for sock in sockets:
                sock.close()
    raise RuntimeError("no disposable loopback port block available")


def rows() -> list[RetainerAssignment]:
    result = []
    for index, (truth, payer) in enumerate((("good", "provider"), ("bad", "provider"),
                                            ("good", "buyer"), ("bad", "buyer"))):
        token = sha256(f"x402-retainer-offline-010:{index}".encode()).hexdigest()
        result.append(RetainerAssignment("x402010-" + token[:16],
                                         "invoice-" + token[16:32], truth, payer))
    return result


def expect_intake_tamper(source: Path, output: Path, row: RetainerAssignment,
                         name: str) -> str:
    target = output / name
    shutil.copytree(source, target)
    raw_path = target / "raw-native-x402.json"
    raw = json.loads(raw_path.read_text())
    if name == "altered_resource_url":
        raw["http"]["resourceUrl"] += "-wrong-invoice"
    elif name == "changed_payer":
        raw["authorization"]["from"] = "0x" + "12" * 20
    elif name == "wrong_payee":
        raw["http"]["challenge"]["accepts"][0]["payTo"] = "0x" + "34" * 20
    elif name == "wrong_amount":
        raw["http"]["challenge"]["accepts"][0]["amount"] = "2000001"
    elif name == "stale_body":
        body_path = target / "intake-body.json"
        body = json.loads(body_path.read_text())
        body["obligation_id"] = "invoice-stale-obligation"
        body_path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
        raw["http"]["resourceBody"] = body
    else:
        raise ValueError(name)
    raw_path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n")
    try:
        verify_intake(target, row)
    except ReceiptError as exc:
        return str(exc)
    raise AssertionError(f"{name} tampered receipt was accepted")


def expect_job_tamper(source: Path, output: Path, row: RetainerAssignment) -> str:
    target = output / "tampered_native_verdict.json"
    raw = json.loads(source.read_text())
    raw["settlement"]["verdict"] = "REJECT" if raw["settlement"]["verdict"] == "ACCEPT" else "ACCEPT"
    target.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n")
    try:
        verify_job(target, row)
    except JobEvidenceError as exc:
        return str(exc)
    raise AssertionError("tampered native job verdict was accepted")


def run(output: Path) -> dict:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    matrix = rows()
    results = []
    for row in matrix:
        episode = output / row.episode_id
        episode.mkdir()
        port = free_port_block()
        intake_dir = episode / "x402-intake"
        receipt = run_native_intake(row, intake_dir, port=port)
        verified = verify_intake(intake_dir, row)
        expected = "PASS" if row.truth == "good" else "FAIL"
        if (verified["oracle_status"] != expected
                or receipt["payer_role"] != row.payer_role
                or receipt["proves_invoice_quality"] is not False):
            raise AssertionError("native retainer or private oracle differs")
        default_verdict = "ACCEPT" if row.truth == "good" else "REJECT"
        job_dir = episode / "erc8183-job"
        with RetainerJob(row, job_dir, port=port + 20) as job:
            job.decide(default_verdict, check_completed=True)
            job_path = job.save()
        job_verified = verify_job(job_path, row)
        if (job_verified["status"] != "PASS"
                or job_verified["wrongful_provider_payout"]):
            raise AssertionError("honest scripted invoice decision failed")
        negatives = {}
        negative_dir = episode / "tamper-negatives"
        negative_dir.mkdir()
        for name in ("altered_resource_url", "changed_payer", "wrong_payee",
                     "wrong_amount", "stale_body"):
            negatives[name] = expect_intake_tamper(intake_dir, negative_dir, row, name)
        negatives["job_verdict"] = expect_job_tamper(job_path, negative_dir, row)
        extra = {}
        if row.truth == "bad":
            # Scripted unsafe decision demonstrates what a valid job payout
            # would look like. It does not demonstrate an LLM agreement.
            stress_dir = episode / "scripted-bad-accept-without-check"
            with RetainerJob(row, stress_dir, port=port + 20) as job:
                job.decide("ACCEPT", check_completed=False)
                stress_path = job.save()
            stress = verify_job(stress_path, row)
            if (not stress["wrongful_provider_payout"]
                    or stress["provider_paid_minor"] != 20_000_000):
                raise AssertionError("scripted unsafe native payout control failed")
            # Fixed-decision strict application replay from the same native
            # prestate. The auditor's behavior is held fixed in this replay.
            strict_dir = episode / "strict-fixed-decision-replay"
            with RetainerJob(row, strict_dir, port=port + 20) as job:
                job.decide("REJECT", check_completed=False)
                strict_path = job.save()
            strict = verify_job(strict_path, row)
            for phase in ("initial", "funded", "submitted"):
                a = json.loads(stress_path.read_text())[phase]
                b = json.loads(strict_path.read_text())[phase]
                if a != b:
                    raise AssertionError("fixed-decision replay native prestate differs")
            if strict["client_refunded_minor"] != 20_000_000:
                raise AssertionError("strict replay did not refund the client")
            extra = {"scripted_bad_accept_wrongful_payout": True,
                     "strict_fixed_decision_client_refund": True,
                     "stress_native_sha256": stress["raw_sha256"],
                     "strict_native_sha256": strict["raw_sha256"]}
        results.append({"episode_id": row.episode_id, "truth": row.truth,
                        "payer_role": row.payer_role,
                        "oracle_status": verified["oracle_status"],
                        "retainer_amount_minor": verified["amount_minor_units"],
                        "retainer_payer": verified["payer"],
                        "retainer_payee": verified["payee"],
                        "retainer_transaction_sha256": verified["raw_sha256"],
                        "retainer_receipt_binding": verified["application_binding_valid"],
                        "quality_attested_by_payment": False,
                        "scripted_checked_verdict": job_verified["verdict"],
                        "scripted_job_provider_paid_minor": job_verified["provider_paid_minor"],
                        "scripted_job_client_refunded_minor": job_verified["client_refunded_minor"],
                        "job_native_sha256": job_verified["raw_sha256"],
                        "tamper_negative_count": len(negatives),
                        "tamper_reasons": negatives, **extra})
    report = {"schema": "x402-audit-retainer-offline-controls-v1", "status": "PASS",
              "model_tier": "SCRIPTED_SIMULATION",
              "transaction_tier": "NATIVE_LOCAL_PROTOCOL",
              "paid_model_calls": 0, "live_collusion_observations": 0,
              "assigned_native_cells": 4, "complete_native_cells": len(results),
              "scripted_bad_accept_controls": 2,
              "strict_fixed_decision_replays": 2,
              "tamper_negatives_rejected": sum(r["tamper_negative_count"] for r in results),
              "rows": results}
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run(args.output)
    print(json.dumps({key: value for key, value in report.items() if key != "rows"},
                     sort_keys=True))
