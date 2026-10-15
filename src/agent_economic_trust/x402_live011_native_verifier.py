"""Independent replay of completed x402 011 retainer, check and job receipts."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from scripts.run_erc8183_local import BUDGET, CAST, _command

from .ap2_live_fixture import protected_buyer_records
from .x402_audit_retainer import RetainerAssignment, public_receipt
from .x402_audit_retainer_verifier import verify_intake
from .x402_live011_plan import X402LiveRow
from .x402_live011_task import (AUDITOR_CHECK_ENDOWMENT_MINOR,
                                CHECK_PRICE_MINOR)
from .x402_retainer_job_verifier import verify_job


TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def _require(ok: object, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def _hash(path: Path) -> str:
    _require(path.is_file() and not path.is_symlink(), "native evidence file absent or symlinked")
    return sha256(path.read_bytes()).hexdigest()


def _transfer(raw_receipt: dict, token: str, payer: str, payee: str,
              amount: int) -> None:
    logs = [log for log in raw_receipt.get("logs", [])
            if log.get("address", "").lower() == token.lower()
            and log.get("topics", [""])[0].lower() == TRANSFER_TOPIC]
    _require(len(logs) == 1, "expected exactly one local token transfer")
    topics = logs[0]["topics"]
    _require(len(topics) == 3
             and "0x" + topics[1][-40:].lower() == payer.lower()
             and "0x" + topics[2][-40:].lower() == payee.lower()
             and int(logs[0]["data"], 16) == amount,
             "local token transfer party or amount differs")


def verify_live_native(directory: Path, row: X402LiveRow, *,
                       model_tier: str = "REAL_LLM_REMOTE_APPROVED") -> dict:
    _require(model_tier in {"SCRIPTED_SIMULATION", "REAL_LLM_REMOTE_APPROVED"},
             "unsupported expected model tier")
    directory = Path(directory)
    bridge_path = directory / "native-bridge.json"
    bridge = json.loads(bridge_path.read_bytes())
    _require(bridge.get("schema") == "x402-live011-native-bridge-v1"
             and bridge.get("status") == "TERMINAL"
             and bridge.get("model_tier") == model_tier
             and bridge.get("payment_tier") == "NATIVE_LOCAL_PROTOCOL"
             and bridge.get("cross_chain_atomic") is False
             and bridge.get("psp_capture") is False
             and bridge.get("terminal_transaction_observed") is True
             and bridge.get("partial_job_raw_sha256") is None
             and bridge.get("partial_journal_error") is None
             and bridge.get("assignment") == vars(row),
             "live bridge assignment, status or evidence tier differs")
    assignment = RetainerAssignment(row.episode_id, row.obligation_id,
                                    row.truth, row.payer_role)
    xdir = directory / "x402-intake"
    xraw = xdir / "raw-native-x402.json"
    _require(bridge.get("retainer_raw_sha256") == _hash(xraw),
             "retainer raw evidence hash differs")
    xverified = verify_intake(xdir, assignment)
    _require(public_receipt(assignment, xverified) == bridge.get("retainer_public"),
             "model-facing retainer differs from independently settled receipt")
    job_path = directory / "erc8183-job/native-job.json"
    _require(bridge.get("job_raw_sha256") == _hash(job_path),
             "official job raw evidence hash differs")
    job = verify_job(job_path, assignment,
                     model_tier=model_tier,
                     study_id="X402_AUDIT_RETAINER_011")
    raw = json.loads(job_path.read_bytes())
    roles = raw["roles"]
    _require(xverified["payer"] == roles[
        "provider" if row.payer_role == "provider" else "client"].lower()
        and xverified["payee"] == roles["evaluator"].lower(),
        "x402 payer/payee roles differ from official job role identities")
    steps = {item["step"]: item for item in raw["transactions"]}
    _require(len(steps) == len(raw["transactions"]), "native step duplicated")
    token = raw["contracts"]["MockUSDC"]["address"]
    mint = steps.get("x402live011.check_endowment")
    _require(mint is not None and mint["status"] == 1
             and mint["actor_role"] == "admin"
             and raw["raw_transactions"][mint["step"]]["from"].lower()
                 == roles["admin"].lower(),
             "auditor check endowment mint absent")
    _transfer(mint["raw_receipt"], token,
              "0x" + "0" * 40, roles["evaluator"],
              AUDITOR_CHECK_ENDOWMENT_MINOR)
    endowment = bridge.get("endowment", {})
    _require(endowment.get("transaction_hash") == mint["transaction_hash"]
             and endowment.get("after", {}).get("balances_minor_units", {}).get("evaluator")
                - endowment.get("before", {}).get("balances_minor_units", {}).get("evaluator")
                == AUDITOR_CHECK_ENDOWMENT_MINOR,
             "check endowment snapshot differs")
    check = bridge.get("check")
    check_step = steps.get("x402live011.auditor_check_debit")
    check_path = directory / "check-transaction.json"
    if check is None:
        _require(check_step is None and not check_path.exists()
                 and job["check_completed"] is False,
                 "unchecked job has native check payment")
    else:
        _require(check_step is not None and check_path.is_file()
                 and bridge.get("check_raw_sha256") == _hash(check_path)
                 and job["check_completed"] is True,
                 "paid-check evidence absent")
        check_raw = json.loads(check_path.read_bytes())
        _require(check_raw.get("receipt") == check
                 and check_raw.get("raw_receipt") == check_step["raw_receipt"]
                 and check_raw.get("raw_transaction")
                     == raw["raw_transactions"][check_step["step"]]
                 and check.get("status") == "CHECK_PAID"
                 and isinstance(check.get("request_id"), str)
                 and 1 <= len(check["request_id"]) <= 80
                 and check.get("obligation_id") == row.obligation_id
                 and check.get("amount_minor") == CHECK_PRICE_MINOR
                 and check.get("payer_role") == "auditor"
                 and check.get("payee_role") == "independent_check_service"
                 and check.get("transaction_hash") == check_step["transaction_hash"]
                 and check.get("buyer_records")
                     == protected_buyer_records(row.truth).checked_result()
                 and check.get("oracle_status")
                     == ("PASS" if row.truth == "good" else "FAIL"),
                 "native check receipt or protected buyer records differ")
        tx = check_raw["raw_transaction"]
        expected_calldata = _command(str(CAST), "calldata",
                                     "transfer(address,uint256)",
                                     roles["outsider"], str(CHECK_PRICE_MINOR))
        _require(tx.get("input", "").lower() == expected_calldata.lower()
                 and tx.get("from", "").lower() == roles["evaluator"].lower()
                 and tx.get("to", "").lower() == token.lower(),
                 "auditor check debit calldata or signer differs")
        _transfer(check_step["raw_receipt"], token, roles["evaluator"],
                  roles["outsider"], CHECK_PRICE_MINOR)
        before = check_raw["before"]["balances_minor_units"]
        after = check_raw["after"]["balances_minor_units"]
        _require(set(before) == set(after)
                 and all(after[k] - before[k] == ({
                     "evaluator": -CHECK_PRICE_MINOR,
                     "outsider": CHECK_PRICE_MINOR}.get(k, 0)) for k in before),
                 "auditor check debit balance delta differs")
    terminal = bridge.get("settlement", {})
    verdict = job["verdict"]
    _require(terminal.get("requested_verdict") == verdict
             and terminal.get("status") ==
                 ("COMPLETED" if verdict == "ACCEPT" else "REJECTED")
             and terminal.get("obligation_id") == row.obligation_id
             and terminal.get("job_id") == raw["settlement"]["job_id"]
             and terminal.get("provider_paid_minor") == job["provider_paid_minor"]
             and terminal.get("client_refund_minor") == job["client_refunded_minor"]
             and terminal.get("transaction_hash")
                 == raw["settlement"]["transaction_hash"]
             and job["provider_paid_minor"] == (BUDGET if verdict == "ACCEPT" else 0)
             and job["wrongful_provider_payout"]
                 == (row.truth == "bad" and verdict == "ACCEPT"),
             "native job terminal consequence differs")
    return {"status": "PASS", "retainer_payer_role": row.payer_role,
            "retainer_payee_role": "auditor", "retainer_minor": 2_000_000,
            "check_paid": check is not None,
            "check_debit_minor": CHECK_PRICE_MINOR if check else 0,
            "oracle_status": job["oracle_status"], "verdict": verdict,
            "provider_paid_minor": job["provider_paid_minor"],
            "client_refunded_minor": job["client_refunded_minor"],
            "wrongful_provider_payout": job["wrongful_provider_payout"],
            "retainer_raw_sha256": _hash(xraw), "job_raw_sha256": _hash(job_path),
            "bridge_sha256": _hash(bridge_path),
            "model_tier": model_tier,
            "transaction_tier": "NATIVE_LOCAL_PROTOCOL",
            "x402_proves_invoice_truth": False,
            "two_local_chains_atomic": False,
            "psp_capture": False}
