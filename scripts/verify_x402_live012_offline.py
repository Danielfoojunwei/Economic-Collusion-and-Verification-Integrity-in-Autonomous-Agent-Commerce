#!/usr/bin/env python3
"""Read-only replay of scripted 012 native receipts and tamper controls."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from agent_economic_trust.x402_live012_native_verifier import verify_live_native  # noqa: E402
from agent_economic_trust.x402_live012_native_verifier import verify_incomplete_native  # noqa: E402
from agent_economic_trust.x402_live012_plan import make_schedule  # noqa: E402
from scripts.run_x402_live012_offline import (  # noqa: E402
    CASES, INCOMPLETE_CASES, INCOMPLETE_TAMPER_REASON,
    _incomplete_negative, _negative, negative_names,
)


def verify(directory: Path) -> dict:
    directory = Path(directory)
    report_path = directory / "report.json"
    report = json.loads(report_path.read_bytes())
    if (report.get("schema") != "x402-live012-scripted-native-controls-v1"
            or report.get("status") != "PASS"
            or report.get("paid_model_calls") != 0
            or report.get("model_tier") != "SCRIPTED_SIMULATION"
            or report.get("transaction_tier") != "NATIVE_LOCAL_PROTOCOL"
            or report.get("scripted_cases") != len(CASES)
            or report.get("matched_assignment_cells") != 4
            or report.get("mechanics_stress_cases") != 2
            or report.get("live_collusion_observations") != 0
            or report.get("payer_effect_inferred_from_scripted_cases") is not False
            or len(report.get("rows", [])) != len(CASES)):
        raise ValueError("012 scripted native report header or denominator differs")
    schedule = {(r.truth, r.payer_role): r for r in make_schedule("00" * 32)}
    expected = {item[0]: item[1:] for item in CASES}
    observed = set()
    negatives = 0
    matched_artifact_digests: dict[str, set[str]] = {"bad": set(), "good": set()}
    for saved in report["rows"]:
        case_id = saved["case_id"]
        if case_id not in expected or case_id in observed:
            raise ValueError("012 scripted case duplicated or changed")
        observed.add(case_id)
        truth, payer, checked, verdict = expected[case_id]
        row = schedule[truth, payer]
        if (saved["episode_id"] != row.episode_id
                or saved["assignment"] != vars(row)
                or saved["check_requested"] is not checked
                or saved["scripted_verdict"] != verdict):
            raise ValueError("012 scripted row assignment or decision differs")
        row_dir = directory / case_id
        verified = verify_live_native(row_dir, row,
                                      model_tier="SCRIPTED_SIMULATION")
        if (verified != saved["verified"]
                or sha256((row_dir / "native-bridge.json").read_bytes()).hexdigest()
                    != saved["native_bridge_sha256"]
                or verified["check_paid"] is not checked
                or verified["verdict"] != verdict
                or verified["oracle_status"] != ("FAIL" if truth == "bad" else "PASS")
                or verified["x402_intake_component_model_tier"]
                    != "SCRIPTED_SIMULATION"
                or verified["wrongful_provider_payout"]
                    is not (truth == "bad" and verdict == "ACCEPT")):
            raise ValueError("012 scripted raw native evidence or oracle differs")
        if case_id.endswith("-stress"):
            pass
        else:
            native_job = json.loads(
                (row_dir / "erc8183-job/native-job.json").read_bytes())
            matched_artifact_digests[truth].add(native_job["artifact_digest"])
        names = negative_names(case_id, checked)
        if set(saved["tamper_reasons"]) != set(names):
            raise ValueError("012 scripted negative-control set changed")
        for name in names:
            if _negative(row_dir, row, name) != saved["tamper_reasons"][name]:
                raise ValueError("012 scripted tamper negative changed")
            negatives += 1
    if (observed != set(expected)
            or negatives != report["tamper_negatives_rejected"]
            or any(len(digests) != 1 for digests in matched_artifact_digests.values())
            or matched_artifact_digests["bad"] == matched_artifact_digests["good"]):
        raise ValueError("012 scripted factorial, invoice facts or tamper count differs")
    return {"status": "PASS", "scripted_cases_reverified": len(observed),
            "matched_assignment_cells_reverified": 4,
            "mechanics_stress_cases_reverified": 2,
            "tamper_negatives_reverified": negatives,
            "bad_unchecked_wrongful_payout_control": True,
            "x402_exact_eip3009_and_replay_reverified": True,
            "live_collusion_observations": 0, "paid_model_calls": 0,
            "report_sha256": sha256(report_path.read_bytes()).hexdigest()}


def verify_incomplete(directory: Path) -> dict:
    """Reopen all saved native receipts; no new local chain or model request."""
    directory = Path(directory)
    report_path = directory / "report.json"
    report = json.loads(report_path.read_bytes())
    if (report.get("schema")
            != "x402-live012-scripted-incomplete-native-controls-v1"
            or report.get("status") != "PASS"
            or report.get("model_tier") != "SCRIPTED_SIMULATION"
            or report.get("transaction_tier") != "NATIVE_LOCAL_PROTOCOL"
            or report.get("paid_model_calls") != 0
            or report.get("live_collusion_observations") != 0
            or report.get("scripted_no_verdict_cases") != len(INCOMPLETE_CASES)
            or report.get("native_state_scope") != "SAVED_LOCAL_CHAIN_HEAD_ONLY"
            or len(report.get("rows", [])) != len(INCOMPLETE_CASES)):
        raise ValueError("012 incomplete native report header differs")
    schedule = {(r.truth, r.payer_role): r for r in make_schedule("00" * 32)}
    expected = {case_id: (truth, payer, checked)
                for case_id, truth, payer, checked, _port in INCOMPLETE_CASES}
    observed = set()
    negative_count = 0
    for saved in report["rows"]:
        case_id = saved["case_id"]
        if case_id not in expected or case_id in observed:
            raise ValueError("012 incomplete native case duplicated or changed")
        observed.add(case_id)
        truth, payer, checked = expected[case_id]
        row = schedule[truth, payer]
        if (saved["episode_id"] != row.episode_id
                or saved["assignment"] != vars(row)
                or saved["check_requested"] is not checked):
            raise ValueError("012 incomplete native row assignment differs")
        case_dir = directory / case_id
        verified = verify_incomplete_native(case_dir, row,
                                            model_tier="SCRIPTED_SIMULATION")
        if (verified != saved["verified"]
                or sha256((case_dir / "native-bridge.json").read_bytes()).hexdigest()
                    != saved["native_bridge_sha256"]
                or verified["check_paid"] is not checked
                or verified["provider_paid_minor"] != 0
                or verified["client_refunded_minor"] != 0
                or verified["terminal_transaction_observed"] is not False):
            raise ValueError("012 incomplete raw native evidence differs")
        names = set(INCOMPLETE_TAMPER_REASON)
        if not checked:
            names.remove("check_amount")
        if set(saved["tamper_reasons"]) != names:
            raise ValueError("012 incomplete negative-control set changed")
        for name in sorted(names):
            if _incomplete_negative(case_dir, row, name) != saved[
                    "tamper_reasons"][name]:
                raise ValueError("012 incomplete tamper negative changed")
            negative_count += 1
    if observed != set(expected) or negative_count != report[
            "tamper_negatives_rejected"]:
        raise ValueError("012 incomplete case or tamper denominator differs")
    return {
        "status": "PASS", "scripted_no_verdict_cases_reverified": len(observed),
        "check_paid_cases_reverified": sum(item[2] for item in expected.values()),
        "tamper_negatives_reverified": negative_count,
        "paid_model_calls": 0, "live_collusion_observations": 0,
        "report_sha256": sha256(report_path.read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--incomplete":
        path = (Path(sys.argv[2]) if len(sys.argv) == 3 else ROOT /
                "artifacts/prospective/X402_LIVE012/offline-incomplete-001")
        print(json.dumps(verify_incomplete(path), sort_keys=True))
    else:
        path = (Path(sys.argv[1]) if len(sys.argv) == 2 else ROOT /
                "artifacts/prospective/X402_LIVE012/offline-native-001")
        print(json.dumps(verify(path), sort_keys=True))
