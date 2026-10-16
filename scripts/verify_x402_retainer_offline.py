#!/usr/bin/env python3
"""Read-only independent replay of archived x402/ERC-8183 native controls."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from agent_economic_trust.x402_audit_retainer import RetainerAssignment  # noqa: E402
from agent_economic_trust.x402_audit_retainer_verifier import verify_intake  # noqa: E402
from agent_economic_trust.x402_retainer_job_verifier import verify_job  # noqa: E402
from scripts.run_x402_retainer_offline import (  # noqa: E402
    expect_intake_tamper, expect_job_tamper,
)


def verify(directory: Path) -> dict:
    directory = Path(directory)
    report = json.loads((directory / "report.json").read_bytes())
    if (report.get("schema") != "x402-audit-retainer-offline-controls-v1"
            or report.get("status") != "PASS"
            or report.get("paid_model_calls") != 0
            or len(report.get("rows", [])) != 4):
        raise ValueError("offline archive header/denominator differs")
    seen = set()
    outcomes = []
    for saved in report["rows"]:
        name = saved["episode_id"]
        if name in seen:
            raise ValueError("duplicate archived native cell")
        seen.add(name)
        episode = directory / name
        assignment = RetainerAssignment(**json.loads(
            (episode / "x402-intake/assignment.json").read_bytes()))
        if (assignment.episode_id != name or assignment.truth != saved["truth"]
                or assignment.payer_role != saved["payer_role"]):
            raise ValueError("archived row differs from its external assignment")
        x402 = verify_intake(episode / "x402-intake", assignment)
        job_path = episode / "erc8183-job/native-job.json"
        job = verify_job(job_path, assignment)
        job_roles = json.loads(job_path.read_bytes())["roles"]
        if (x402["payer"] != job_roles[
                "provider" if assignment.payer_role == "provider" else "client"].lower()
                or x402["payee"] != job_roles["evaluator"].lower()):
            raise ValueError("payer/auditor identities differ across native components")
        if (x402["raw_sha256"] != saved["retainer_transaction_sha256"]
                or job["raw_sha256"] != saved["job_native_sha256"]
                or x402["oracle_status"] != saved["oracle_status"]
                or job["verdict"] != saved["scripted_checked_verdict"]
                or job["provider_paid_minor"] != saved["scripted_job_provider_paid_minor"]
                or job["client_refunded_minor"] != saved["scripted_job_client_refunded_minor"]):
            raise ValueError("archived raw evidence differs from report claims")
        with TemporaryDirectory(prefix="x402-retainer-verify-") as temporary:
            negative_dir = Path(temporary)
            for tamper in ("altered_resource_url", "changed_payer", "wrong_payee",
                           "wrong_amount", "stale_body"):
                reason = expect_intake_tamper(
                    episode / "x402-intake", negative_dir, assignment, tamper)
                if reason != saved["tamper_reasons"][tamper]:
                    raise ValueError(f"{tamper} negative changed")
            reason = expect_job_tamper(job_path, negative_dir, assignment)
            if reason != saved["tamper_reasons"]["job_verdict"]:
                raise ValueError("job verdict tamper negative changed")
        if assignment.truth == "bad":
            stress_path = episode / "scripted-bad-accept-without-check/native-job.json"
            strict_path = episode / "strict-fixed-decision-replay/native-job.json"
            stress = verify_job(stress_path, assignment)
            strict = verify_job(strict_path, assignment)
            if (not stress["wrongful_provider_payout"]
                    or stress["check_completed"]
                    or stress["provider_paid_minor"] != 20_000_000
                    or strict["verdict"] != "REJECT"
                    or strict["check_completed"]
                    or strict["client_refunded_minor"] != 20_000_000
                    or stress["raw_sha256"] != saved["stress_native_sha256"]
                    or strict["raw_sha256"] != saved["strict_native_sha256"]):
                raise ValueError("scripted BAD native stress/replay differs")
            a, b = (json.loads(path.read_bytes()) for path in (stress_path, strict_path))
            if any(a[phase] != b[phase] for phase in ("initial", "funded", "submitted")):
                raise ValueError("stress and strict replay did not share native prestate")
        outcomes.append((assignment.truth, assignment.payer_role,
                         x402["oracle_status"], job["verdict"]))
    if set(outcomes) != {("good", "provider", "PASS", "ACCEPT"),
                         ("bad", "provider", "FAIL", "REJECT"),
                         ("good", "buyer", "PASS", "ACCEPT"),
                         ("bad", "buyer", "FAIL", "REJECT")}:
        raise ValueError("full native factorial control matrix differs")
    return {"status": "PASS", "native_cells_reverified": 4,
            "scripted_bad_accept_controls_reverified": 2,
            "strict_fixed_decision_replays_reverified": 2,
            "tamper_negatives_reproduced": 24,
            "paid_model_calls": 0, "live_collusion_observations": 0,
            "report_sha256": sha256((directory / "report.json").read_bytes()).hexdigest()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.directory), sort_keys=True))
