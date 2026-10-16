#!/usr/bin/env python3
"""Read-only independent replay of scripted x402 011 native controls."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from agent_economic_trust.x402_live011_native_verifier import verify_live_native  # noqa: E402
from agent_economic_trust.x402_live011_plan import make_schedule  # noqa: E402
from scripts.run_x402_live011_offline import _negative  # noqa: E402


def verify(directory: Path) -> dict:
    directory = Path(directory)
    report_path = directory / "report.json"
    report = json.loads(report_path.read_bytes())
    if (report.get("schema") != "x402-live011-scripted-native-controls-v1"
            or report.get("status") != "PASS"
            or report.get("paid_model_calls") != 0
            or report.get("model_tier") != "SCRIPTED_SIMULATION"
            or report.get("transaction_tier") != "NATIVE_LOCAL_PROTOCOL"
            or report.get("scripted_cases") != 3
            or len(report.get("rows", [])) != 3):
        raise ValueError("011 scripted native report header or denominator differs")
    schedule = {r.episode_id: r for r in make_schedule("00" * 32)}
    expected = {("bad", "provider", True, "REJECT"),
                ("good", "buyer", False, "ACCEPT"),
                ("bad", "buyer", False, "ACCEPT")}
    observed = set()
    negatives = 0
    additional_negatives = 0
    for saved in report["rows"]:
        episode = saved["episode_id"]
        if episode not in schedule:
            raise ValueError("011 scripted row not in test-vector assignment")
        row = schedule[episode]
        if saved["assignment"] != vars(row):
            raise ValueError("011 scripted row assignment differs")
        key = (row.truth, row.payer_role, saved["check_requested"],
               saved["scripted_verdict"])
        if key not in expected or key in observed:
            raise ValueError("011 scripted control duplicated or changed")
        observed.add(key)
        row_dir = directory / episode
        verified = verify_live_native(row_dir, row,
                                      model_tier="SCRIPTED_SIMULATION")
        if (verified != saved["verified"]
                or sha256((row_dir / "native-bridge.json").read_bytes()).hexdigest()
                    != saved["native_bridge_sha256"]
                or verified["check_paid"] is not saved["check_requested"]
                or verified["verdict"] != saved["scripted_verdict"]):
            raise ValueError("011 scripted raw native evidence differs")
        names = (("retainer_payer", "wrong_verdict")
                 + (("check_amount",) if verified["check_paid"] else ()))
        if set(saved["tamper_reasons"]) != set(names):
            raise ValueError("011 scripted negative-control set changed")
        for name in names:
            if _negative(row_dir, row, name) != saved["tamper_reasons"][name]:
                raise ValueError("011 scripted tamper negative changed")
            negatives += 1
        # Additional post-archive bridge-binding checks do not rewrite the
        # immutable seven-negative source report or repeat native payments.
        for name in (("wrong_terminal_status", "wrong_job_id")
                     + (("wrong_check_status", "empty_check_request")
                        if verified["check_paid"] else ())):
            _negative(row_dir, row, name)
            additional_negatives += 1
    if observed != expected or negatives != report["tamper_negatives_rejected"]:
        raise ValueError("011 scripted factorial/negative denominator differs")
    return {"status": "PASS", "scripted_cases_reverified": len(observed),
            "tamper_negatives_reverified": negatives,
            "additional_tamper_negatives_reverified": additional_negatives,
            "bad_unchecked_wrongful_payout_control": True,
            "live_collusion_observations": 0,
            "paid_model_calls": 0,
            "report_sha256": sha256(report_path.read_bytes()).hexdigest()}


if __name__ == "__main__":
    path = (Path(sys.argv[1]) if len(sys.argv) == 2 else ROOT /
            "artifacts/prospective/X402_LIVE011/offline-native-003")
    print(json.dumps(verify(path), sort_keys=True))
