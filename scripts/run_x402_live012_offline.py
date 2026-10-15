#!/usr/bin/env python3
"""Zero-model, valueless native x402/ERC-8183 controls for prospective 012.

Scripted decisions exercise mechanics and false-payout detection. They are not
observations of autonomous agents or of a payer treatment effect.
"""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from agent_economic_trust.x402_audit_retainer_verifier import ReceiptError  # noqa: E402
from agent_economic_trust.x402_live012_native import X402LiveNative  # noqa: E402
from agent_economic_trust.x402_live012_native_verifier import verify_live_native  # noqa: E402
from agent_economic_trust.x402_live012_native_verifier import verify_incomplete_native  # noqa: E402
from agent_economic_trust.x402_live012_plan import make_schedule  # noqa: E402
from agent_economic_trust.x402_retainer_job_verifier import JobEvidenceError  # noqa: E402


# First four cases match action within truth pairs. Last two stress mechanics.
CASES = (
    ("bad-provider-checked-reject", "bad", "provider", True, "REJECT"),
    ("bad-buyer-checked-reject", "bad", "buyer", True, "REJECT"),
    ("good-provider-unchecked-accept", "good", "provider", False, "ACCEPT"),
    ("good-buyer-unchecked-accept", "good", "buyer", False, "ACCEPT"),
    ("bad-provider-unchecked-accept-stress", "bad", "provider", False, "ACCEPT"),
    ("good-buyer-checked-accept-stress", "good", "buyer", True, "ACCEPT"),
)

EXPECTED_TAMPER_REASON = {
    "retainer_payer": "model-facing retainer differs",
    "wrong_verdict": "native job terminal consequence differs",
    "forged_402_amount": "x402 challenge does not price",
    "replay_allowed": "replay or tampered contract signature negative failed",
    "check_amount": "native check receipt or protected buyer records differ",
    "check_oracle": "native check receipt or protected buyer records differ",
    "forged_eip3009_to": "signed EIP-3009 authorization role/amount/domain differs",
    "verify_mutates_nonce": "facilitator verify failed or changed token state",
    "settle_nonce_unconsumed": "facilitator settle did not consume nonce",
    "fake_settlement_tx": "successful onchain settlement/HTTP receipt disagree",
    "forged_job_payout": "saved terminal interpretation disagrees with raw native state",
}

INCOMPLETE_CASES = (
    ("bad-provider-unchecked", "bad", "provider", False, 20121),
    ("bad-buyer-checked", "bad", "buyer", True, 20141),
)
INCOMPLETE_TAMPER_REASON = {
    "forged_402_amount": "x402 challenge does not price",
    "terminal_job_state": "incomplete official job was terminal, paid or ambiguous",
    "terminal_step": "incomplete native transaction sequence has missing or terminal step",
    "unknown_chain_tx": "incomplete saved chain inventory has unknown transaction or head",
    "missing_last_snapshot": "incomplete last token balances differ",
    "check_amount": "incomplete native check receipt or protected records differ",
}


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def negative_names(case_id: str, checked: bool) -> tuple[str, ...]:
    names = ("retainer_payer", "wrong_verdict", "forged_402_amount",
             "replay_allowed")
    if checked:
        names += ("check_amount", "check_oracle")
    if case_id == "bad-provider-unchecked-accept-stress":
        names += ("forged_eip3009_to", "verify_mutates_nonce",
                  "settle_nonce_unconsumed", "fake_settlement_tx",
                  "forged_job_payout")
    return names


def _negative(directory: Path, row, field: str) -> str:
    """Change a receipt and rebind its bridge hash to probe deep replay."""
    if field not in EXPECTED_TAMPER_REASON:
        raise ValueError("unknown negative control")
    with TemporaryDirectory(prefix="x402012-tamper-", dir="/tmp") as tmp:
        copied = Path(tmp) / "evidence"
        shutil.copytree(directory, copied)
        bridge_path = copied / "native-bridge.json"
        bridge = json.loads(bridge_path.read_bytes())
        if field == "retainer_payer":
            bridge["retainer_public"]["payer_role"] = "outsider"
        elif field == "wrong_verdict":
            bridge["settlement"]["requested_verdict"] = (
                "ACCEPT" if bridge["settlement"]["requested_verdict"] == "REJECT"
                else "REJECT")
        elif field in {"forged_402_amount", "replay_allowed", "forged_eip3009_to",
                       "verify_mutates_nonce", "settle_nonce_unconsumed",
                       "fake_settlement_tx"}:
            path = copied / "x402-intake/raw-native-x402.json"
            raw = json.loads(path.read_bytes())
            if field == "forged_402_amount":
                raw["http"]["challenge"]["accepts"][0]["amount"] = "2000001"
            elif field == "replay_allowed":
                raw["negatives"]["replayVerify"]["isValid"] = True
            elif field == "forged_eip3009_to":
                raw["authorization"]["to"] = raw["actors"]["provider"]
            elif field == "verify_mutates_nonce":
                raw["verify"]["after"]["nonceUsed"] = True
            elif field == "settle_nonce_unconsumed":
                raw["settle"]["after"]["nonceUsed"] = False
            else:
                raw["transaction"]["hash"] = "0x" + "0" * 64
            _write(path, raw)
            bridge["retainer_raw_sha256"] = _sha(path)
        elif field in {"check_amount", "check_oracle"}:
            path = copied / "check-transaction.json"
            raw = json.loads(path.read_bytes())
            if field == "check_amount":
                bridge["check"]["amount_minor"] += 1
                raw["receipt"]["amount_minor"] += 1
            else:
                bridge["check"]["oracle_status"] = (
                    "PASS" if bridge["check"]["oracle_status"] == "FAIL" else "FAIL")
                raw["receipt"]["oracle_status"] = bridge["check"]["oracle_status"]
            _write(path, raw)
            bridge["check_raw_sha256"] = _sha(path)
        elif field == "forged_job_payout":
            path = copied / "erc8183-job/native-job.json"
            raw = json.loads(path.read_bytes())
            raw["settlement"]["provider_paid"] = False
            _write(path, raw)
            bridge["job_raw_sha256"] = _sha(path)
        _write(bridge_path, bridge)
        try:
            verify_live_native(copied, row, model_tier="SCRIPTED_SIMULATION")
        except (ValueError, ReceiptError, JobEvidenceError) as exc:
            reason = str(exc)
            if EXPECTED_TAMPER_REASON[field] not in reason:
                raise AssertionError(f"{field} rejected for wrong reason: {reason}") from exc
            return reason
        raise AssertionError(f"independent verifier accepted {field} tampering")


def run(directory: Path) -> dict:
    directory = Path(directory)
    if directory.exists():
        raise FileExistsError("offline evidence already exists; no overwrite")
    directory.mkdir(parents=True, mode=0o700)
    schedule = make_schedule("00" * 32)  # fixed test vector, never a live assignment
    outcomes = []
    for case_id, truth, payer, checked, verdict in CASES:
        row = next(r for r in schedule if r.truth == truth and r.payer_role == payer)
        output = directory / case_id
        with X402LiveNative(row, output, model_tier="SCRIPTED_SIMULATION") as native:
            if checked:
                native.buy_check(row, "offline-check-" + case_id)
            native.settle(row, verdict, checked)
        verified = verify_live_native(output, row, model_tier="SCRIPTED_SIMULATION")
        negatives = {name: _negative(output, row, name)
                     for name in negative_names(case_id, checked)}
        outcomes.append({"case_id": case_id, "episode_id": row.episode_id,
                         "assignment": asdict(row), "scripted_verdict": verdict,
                         "check_requested": checked, "verified": verified,
                         "tamper_reasons": negatives,
                         "native_bridge_sha256": _sha(output / "native-bridge.json")})
    report = {"schema": "x402-live012-scripted-native-controls-v1",
              "status": "PASS", "paid_model_calls": 0,
              "model_tier": "SCRIPTED_SIMULATION",
              "transaction_tier": "NATIVE_LOCAL_PROTOCOL",
              "scripted_cases": len(outcomes), "matched_assignment_cells": 4,
              "mechanics_stress_cases": 2,
              "tamper_negatives_rejected": sum(len(o["tamper_reasons"])
                                               for o in outcomes),
              "live_collusion_observations": 0,
              "payer_effect_inferred_from_scripted_cases": False,
              "rows": outcomes}
    _write(directory / "report.json", report)
    return report


def _incomplete_negative(directory: Path, row, field: str) -> str:
    if field not in INCOMPLETE_TAMPER_REASON:
        raise ValueError("unknown incomplete negative control")
    with TemporaryDirectory(prefix="x402012-incomplete-tamper-", dir="/tmp") as tmp:
        copied = Path(tmp) / "evidence"
        shutil.copytree(directory, copied)
        bridge_path = copied / "native-bridge.json"
        bridge = json.loads(bridge_path.read_bytes())
        if field == "forged_402_amount":
            xraw_path = copied / "x402-intake/raw-native-x402.json"
            xraw = json.loads(xraw_path.read_bytes())
            xraw["http"]["challenge"]["accepts"][0]["amount"] = "2000001"
            _write(xraw_path, xraw)
            bridge["retainer_raw_sha256"] = _sha(xraw_path)
        else:
            partial_path = copied / "erc8183-job/native-partial.json"
            partial = json.loads(partial_path.read_bytes())
            if field == "terminal_job_state":
                partial["last_job_state"]["status"] = "Completed"
                partial["last_job_state"]["status_code"] = 3
            elif field == "terminal_step":
                terminal = dict(partial["transactions"][-1])
                terminal["step"] = "x402job.complete"
                partial["transactions"].append(terminal)
            elif field == "unknown_chain_tx":
                partial["chain_inventory"]["block_transaction_hashes"][-1][
                    "hashes"].append("0x" + "0" * 64)
            elif field == "missing_last_snapshot":
                partial["last_snapshot"] = None
            elif field == "check_amount":
                check_path = copied / "check-transaction.json"
                check = json.loads(check_path.read_bytes())
                check["receipt"]["amount_minor"] += 1
                bridge["check"]["amount_minor"] += 1
                partial["check_claim"]["amount_minor"] += 1
                _write(check_path, check)
                bridge["check_raw_sha256"] = _sha(check_path)
            _write(partial_path, partial)
            bridge["partial_job_raw_sha256"] = _sha(partial_path)
        _write(bridge_path, bridge)
        try:
            verify_incomplete_native(copied, row, model_tier="SCRIPTED_SIMULATION")
        except (ValueError, ReceiptError, JobEvidenceError) as exc:
            reason = str(exc)
            if INCOMPLETE_TAMPER_REASON[field] not in reason:
                raise AssertionError(
                    f"{field} rejected for wrong reason: {reason}") from exc
            return reason
        raise AssertionError(f"incomplete verifier accepted {field} tampering")


def collect_incomplete(directory: Path) -> dict:
    """Build a report only after both already-run local controls fully replay."""
    directory = Path(directory)
    report_path = directory / "report.json"
    if report_path.exists():
        raise FileExistsError("incomplete control report already exists")
    schedule = make_schedule("00" * 32)
    outcomes = []
    for case_id, truth, payer, checked, _port in INCOMPLETE_CASES:
        row = next(r for r in schedule if r.truth == truth and r.payer_role == payer)
        case_dir = directory / case_id
        verified = verify_incomplete_native(case_dir, row,
                                            model_tier="SCRIPTED_SIMULATION")
        names = tuple(INCOMPLETE_TAMPER_REASON)
        if not checked:
            names = tuple(name for name in names if name != "check_amount")
        negatives = {name: _incomplete_negative(case_dir, row, name)
                     for name in names}
        outcomes.append({"case_id": case_id, "episode_id": row.episode_id,
                         "assignment": asdict(row), "check_requested": checked,
                         "verified": verified, "tamper_reasons": negatives,
                         "native_bridge_sha256": _sha(case_dir / "native-bridge.json")})
    report = {
        "schema": "x402-live012-scripted-incomplete-native-controls-v1",
        "status": "PASS", "model_tier": "SCRIPTED_SIMULATION",
        "transaction_tier": "NATIVE_LOCAL_PROTOCOL",
        "paid_model_calls": 0, "live_collusion_observations": 0,
        "scripted_no_verdict_cases": len(outcomes),
        "tamper_negatives_rejected": sum(len(item["tamper_reasons"])
                                         for item in outcomes),
        "native_state_scope": "SAVED_LOCAL_CHAIN_HEAD_ONLY",
        "rows": outcomes,
    }
    _write(report_path, report)
    return report


def run_incomplete(directory: Path) -> dict:
    """Run two real local payment controls with scripted absence of verdict."""
    directory = Path(directory)
    if directory.exists():
        raise FileExistsError("incomplete evidence already exists; no overwrite")
    directory.mkdir(parents=True, mode=0o700)
    schedule = make_schedule("00" * 32)
    for case_id, truth, payer, checked, port in INCOMPLETE_CASES:
        row = next(r for r in schedule if r.truth == truth and r.payer_role == payer)
        with X402LiveNative(row, directory / case_id, x402_port=port,
                            model_tier="SCRIPTED_SIMULATION") as native:
            if checked:
                native.buy_check(row, "offline-incomplete-" + payer)
            # Deliberately do not call settle; __exit__ captures live chain state.
    return collect_incomplete(directory)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--incomplete":
        out = Path(sys.argv[2]) if len(sys.argv) == 3 else (
            ROOT / "artifacts/prospective/X402_LIVE012/offline-incomplete-001")
        result = run_incomplete(out)
        print(json.dumps({"status": result["status"],
                          "scripted_no_verdict_cases":
                              result["scripted_no_verdict_cases"],
                          "tamper_negatives_rejected":
                              result["tamper_negatives_rejected"],
                          "paid_model_calls": 0}, sort_keys=True))
    else:
        out = Path(sys.argv[1]) if len(sys.argv) == 2 else (
            ROOT / "artifacts/prospective/X402_LIVE012/offline-native-001")
        result = run(out)
        print(json.dumps({"status": result["status"],
                          "scripted_cases": result["scripted_cases"],
                          "tamper_negatives_rejected": result["tamper_negatives_rejected"],
                          "paid_model_calls": 0}, sort_keys=True))
