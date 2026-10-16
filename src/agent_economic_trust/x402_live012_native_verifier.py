"""Independent replay of completed x402 012 retainer, check and job receipts."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from scripts.run_erc8183_local import BUDGET, CAST, CHAIN_ID, PIN, UPSTREAM, _command

from .ap2_live_fixture import protected_buyer_records
from .ap2_live_fixture import invoice_case
from .x402_audit_retainer import FEE_MINOR, RetainerAssignment, public_receipt
from .x402_audit_retainer_verifier import verify_intake
from .x402_live012_plan import X402LiveRow
from .x402_live012_task import (AUDITOR_CHECK_ENDOWMENT_MINOR,
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
    _hash(bridge_path)
    bridge = json.loads(bridge_path.read_bytes())
    _require(bridge.get("schema") == "x402-live012-native-bridge-v1"
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
                     study_id="X402_AUDIT_RETAINER_012")
    raw = json.loads(job_path.read_bytes())
    roles = raw["roles"]
    _require(xverified["payer"] == roles[
        "provider" if row.payer_role == "provider" else "client"].lower()
        and xverified["payee"] == roles["evaluator"].lower(),
        "x402 payer/payee roles differ from official job role identities")
    steps = {item["step"]: item for item in raw["transactions"]}
    _require(len(steps) == len(raw["transactions"]), "native step duplicated")
    token = raw["contracts"]["MockUSDC"]["address"]
    mint = steps.get("x402live012.check_endowment")
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
    check_step = steps.get("x402live012.auditor_check_debit")
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
            "retainer_payee_role": "auditor", "retainer_minor": FEE_MINOR,
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
            "x402_intake_component_model_tier": xverified["model_tier"],
            "x402_402_challenge_verified": True,
            "x402_exact_eip3009_authorization_verified": True,
            "x402_verify_without_transfer_verified": True,
            "x402_settle_transfer_receipt_verified": True,
            "x402_replay_rejected_verified": True,
            "x402_proves_invoice_truth": False,
            "two_local_chains_atomic": False,
            "psp_capture": False}


_PRETERMINAL_STEPS = (
    "deploy.mock_usdc", "deploy.implementation", "deploy.proxy",
    "setup.allow_token", "setup.evaluator_fee", "setup.platform_fee",
    "setup.mint", "setup.approve", "x402job.zero_evaluator_fee",
    "x402job.zero_platform_fee", "x402job.create", "x402job.budget",
    "x402job.fund", "x402job.submit", "x402live012.check_endowment",
)
_TERMINAL_EVENTS = {
    "JobCompleted", "JobRejected", "JobExpired", "Refunded",
    "PaymentReleased", "ClaimApproved", "ClaimSettled", "Settled",
}


def _snapshot(snapshot: object, roles: dict, reason: str) -> dict[str, int]:
    _require(isinstance(snapshot, dict), reason)
    balances = snapshot.get("balances_minor_units")
    _require(isinstance(balances, dict)
             and set(balances) == set(roles) | {"escrow"}
             and all(type(value) is int and value >= 0
                     for value in balances.values())
             and type(snapshot.get("total_supply_minor_units")) is int
             and sum(balances.values()) == snapshot["total_supply_minor_units"],
             reason)
    return balances


def verify_incomplete_native(directory: Path, row: X402LiveRow, *,
                             model_tier: str = "REAL_LLM_REMOTE_APPROVED") -> dict:
    """Replay a saved local job that remains Submitted with no terminal action.

    This establishes the observed native state at the archived local chain
    head. A model's lack of verdict must be established separately from the
    saved Inspect sample; this verifier handles only payment consequences.
    """
    _require(model_tier in {"SCRIPTED_SIMULATION", "REAL_LLM_REMOTE_APPROVED"},
             "unsupported expected model tier")
    directory = Path(directory)
    bridge_path = directory / "native-bridge.json"
    _hash(bridge_path)
    bridge = json.loads(bridge_path.read_bytes())
    _require(bridge.get("schema") == "x402-live012-native-bridge-v1"
             and bridge.get("status") == "STOPPED_PARTIAL"
             and bridge.get("model_tier") == model_tier
             and bridge.get("payment_tier") == "NATIVE_LOCAL_PROTOCOL"
             and bridge.get("assignment") == vars(row)
             and bridge.get("retainer_public") is not None
             and bridge.get("endowment") is not None
             and bridge.get("settlement") is None
             and bridge.get("job_raw_sha256") is None
             and bridge.get("terminal_transaction_observed") is False
             and bridge.get("partial_journal_error") is None
             and bridge.get("cross_chain_atomic") is False
             and bridge.get("psp_capture") is False
             and not (directory / "erc8183-job/native-job.json").exists()
             and not (directory / "erc8183-job/native-job.json").is_symlink(),
             "incomplete bridge has absent, terminal or ambiguous native state")
    assignment = RetainerAssignment(row.episode_id, row.obligation_id,
                                    row.truth, row.payer_role)
    xdir = directory / "x402-intake"
    xraw = xdir / "raw-native-x402.json"
    _require(bridge.get("retainer_raw_sha256") == _hash(xraw),
             "incomplete retainer raw evidence hash differs")
    xverified = verify_intake(xdir, assignment)
    _require(public_receipt(assignment, xverified) == bridge["retainer_public"],
             "incomplete model-facing retainer differs")
    partial_path = directory / "erc8183-job/native-partial.json"
    _require(bridge.get("partial_job_raw_sha256") == _hash(partial_path),
             "incomplete native journal hash differs")
    partial = json.loads(partial_path.read_bytes())
    _require(partial.get("schema") == "x402-live012-partial-native-journal-v1"
             and partial.get("model_tier") == model_tier
             and partial.get("transaction_tier") == "NATIVE_LOCAL_PROTOCOL"
             and partial.get("erc8183_commit") == PIN
             and partial.get("chain_id") == CHAIN_ID
             and partial.get("assignment") == vars(row)
             and partial.get("job_id") == 1
             and partial.get("terminal_claim") is None
             and partial.get("terminal_transaction_observed") is False
             and partial.get("outcome_status")
                 == "UNVERIFIED_PARTIAL_DO_NOT_INFER_NO_PAYOUT",
             "incomplete native journal source or assignment differs")
    _require(_command("git", "rev-parse", "HEAD", cwd=UPSTREAM) == PIN,
             "installed official ERC-8183 checkout changed")
    roles = partial.get("roles")
    contracts = partial.get("contracts")
    _require(isinstance(roles, dict)
             and set(roles) == {"admin", "client", "provider", "evaluator",
                                "treasury", "outsider"}
             and len({str(value).lower() for value in roles.values()}) == 6
             and isinstance(contracts, dict)
             and set(contracts) == {"MockUSDC", "ERC8183", "ERC1967Proxy"},
             "incomplete native roles or contracts differ")
    for name in contracts:
        official = UPSTREAM / "out" / f"{name}.sol" / f"{name}.json"
        _require(contracts[name].get("artifact_sha256") == _hash(official)
                 and isinstance(contracts[name].get("runtime_code_sha256"), str)
                 and len(contracts[name]["runtime_code_sha256"]) == 64,
                 "incomplete official contract pin differs")
    core_abi = json.loads((UPSTREAM / "out/ERC8183.sol/ERC8183.json").read_bytes())["abi"]
    terminal_topics = {
        _command(str(CAST), "keccak", entry["name"] + "("
                 + ",".join(field["type"] for field in entry["inputs"]) + ")").lower()
        for entry in core_abi if entry.get("type") == "event"
        and entry.get("name") in _TERMINAL_EVENTS
    }
    _require(xverified["payer"] == roles[
        "provider" if row.payer_role == "provider" else "client"].lower()
        and xverified["payee"] == roles["evaluator"].lower(),
        "incomplete x402 payer/payee differ from official job roles")
    token = contracts["MockUSDC"]["address"]
    core = contracts["ERC1967Proxy"]["address"]
    transactions = partial.get("transactions")
    _require(isinstance(transactions, list)
             and tuple(item.get("step") for item in transactions) ==
                 _PRETERMINAL_STEPS +
                 (("x402live012.auditor_check_debit",)
                  if bridge.get("check") is not None else ()),
             "incomplete native transaction sequence has missing or terminal step")
    observed_hashes = []
    steps = {}
    for item in transactions:
        name = item["step"]
        tx = item.get("raw_transaction")
        receipt = item.get("raw_receipt")
        _require(isinstance(tx, dict) and isinstance(receipt, dict)
                 and item.get("actor_role") in roles
                 and item.get("status") == item.get("expected_status") == 1
                 and receipt.get("status") == "0x1"
                 and item.get("transaction_hash") == tx.get("hash")
                 and item["transaction_hash"] == receipt.get("transactionHash")
                 and tx.get("from", "").lower() == roles[
                     item.get("actor_role", "")].lower()
                 and item.get("block_number") == int(receipt.get("blockNumber"), 16)
                 and len(item.get("logs", [])) == len(receipt.get("logs", []))
                 and all(
                     saved.get("address", "").lower() == raw.get("address", "").lower()
                     and saved.get("topics") == raw.get("topics")
                     and saved.get("data") == raw.get("data")
                     and saved.get("log_index") == int(raw.get("logIndex"), 16)
                     for saved, raw in zip(item.get("logs", []),
                                           receipt.get("logs", []), strict=True))
                 and not ({log.get("name") for log in item.get("logs", [])}
                          & _TERMINAL_EVENTS)
                 and not any(log.get("topics", [""])[0].lower() in terminal_topics
                             for log in receipt.get("logs", [])
                             if log.get("topics")),
                 f"{name} raw transaction, receipt or terminal event differs")
        observed_hashes.append(item["transaction_hash"])
        steps[name] = item
    _require(len(set(observed_hashes)) == len(observed_hashes),
             "incomplete native transaction hash duplicated")
    inventory = partial.get("chain_inventory")
    _require(isinstance(inventory, dict)
             and inventory.get("chain_id") == CHAIN_ID
             and type(inventory.get("head_block_number")) is int
             and len(inventory.get("block_transaction_hashes", []))
                 == inventory["head_block_number"]
             and [block.get("block_number") for block in
                  inventory["block_transaction_hashes"]]
                 == list(range(1, inventory["head_block_number"] + 1))
             and [value for block in inventory["block_transaction_hashes"]
                  for value in block.get("hashes", [])] == observed_hashes
             and transactions[-1]["block_number"]
                 == inventory["head_block_number"],
             "incomplete saved chain inventory has unknown transaction or head")
    for name, actor in (("x402job.create", "client"),
                        ("x402job.fund", "client"),
                        ("x402job.submit", "provider")):
        tx = steps[name]["raw_transaction"]
        _require(steps[name]["actor_role"] == actor
                 and tx.get("to", "").lower() == core.lower(),
                 "incomplete official job create/fund/submit sender differs")
    _, artifact = invoice_case(row.truth)
    description = json.dumps({
        "study": "X402_AUDIT_RETAINER_012",
        "obligation_id": row.obligation_id,
        "artifact_digest": artifact.digest(),
        "rule": "release iff independent invoice total matches report",
    }, sort_keys=True, separators=(",", ":"))
    _require(description.encode().hex() in
             steps["x402job.create"]["raw_transaction"].get(
                 "input", "").removeprefix("0x"),
             "incomplete job creation does not bind assigned invoice")
    initial = _snapshot(partial.get("initial"), roles,
                        "incomplete initial token balances differ")
    funded = _snapshot(partial.get("funded"), roles,
                       "incomplete funded token balances differ")
    submitted = _snapshot(partial.get("submitted"), roles,
                          "incomplete submitted token balances differ")
    last = _snapshot(partial.get("last_snapshot"), roles,
                     "incomplete last token balances differ")
    _require(funded["escrow"] == submitted["escrow"] == BUDGET
             and submitted == funded
             and funded["client"] == initial["client"] - BUDGET
             and funded["escrow"] == initial["escrow"] + BUDGET
             and all(funded[role] == initial[role]
                     for role in roles if role != "client"),
             "incomplete official job funding balance delta differs")
    state = partial.get("last_job_state")
    _require(isinstance(state, dict)
             and state.get("status") == "Submitted"
             and state.get("status_code") == 2
             and state.get("budget_minor_units") == BUDGET
             and state.get("settled_amount_minor_units") == 0
             and state.get("client", "").lower() == roles["client"].lower()
             and state.get("provider", "").lower() == roles["provider"].lower()
             and state.get("evaluator", "").lower() == roles["evaluator"].lower()
             and state.get("payment_token", "").lower() == token.lower(),
             "incomplete official job was terminal, paid or ambiguous")
    mint = steps["x402live012.check_endowment"]
    mint_tx = mint["raw_transaction"]
    _require(mint_tx.get("to", "").lower() == token.lower()
             and mint_tx.get("from", "").lower() == roles["admin"].lower()
             and mint_tx.get("input", "").lower() == _command(
                 str(CAST), "calldata", "mint(address,uint256)",
                 roles["evaluator"], str(AUDITOR_CHECK_ENDOWMENT_MINOR)).lower(),
             "incomplete check endowment calldata or signer differs")
    _transfer(mint["raw_receipt"], token, "0x" + "0" * 40,
              roles["evaluator"], AUDITOR_CHECK_ENDOWMENT_MINOR)
    endowment = bridge["endowment"]
    endowment_after = _snapshot(endowment.get("after"), roles,
                                "incomplete auditor endowment snapshot differs")
    _require(partial.get("endowment") == endowment
             and endowment.get("transaction_hash") == mint["transaction_hash"]
             and endowment.get("before") == partial["submitted"]
             and all(endowment_after[role] - submitted[role] ==
                     (AUDITOR_CHECK_ENDOWMENT_MINOR if role == "evaluator" else 0)
                     for role in (*roles, "escrow"))
             and endowment["after"]["total_supply_minor_units"] ==
                 partial["submitted"]["total_supply_minor_units"]
                    + AUDITOR_CHECK_ENDOWMENT_MINOR,
             "incomplete auditor endowment receipt differs")
    check = bridge.get("check")
    check_path = directory / "check-transaction.json"
    if check is None:
        _require(partial.get("check_claim") is None
                 and bridge.get("check_raw_sha256") is None
                 and not check_path.exists() and not check_path.is_symlink(),
                 "unchecked incomplete job has check payment claim")
    else:
        _require(partial.get("check_claim") == check
                 and bridge.get("check_raw_sha256") == _hash(check_path),
                 "incomplete check receipt or journal differs")
        check_raw = json.loads(check_path.read_bytes())
        debit = steps["x402live012.auditor_check_debit"]
        debit_tx = debit["raw_transaction"]
        _require(check_raw.get("receipt") == check
                 and check_raw.get("raw_receipt") == debit["raw_receipt"]
                 and check_raw.get("raw_transaction") == debit_tx
                 and check.get("status") == "CHECK_PAID"
                 and isinstance(check.get("request_id"), str)
                 and 1 <= len(check["request_id"]) <= 80
                 and check.get("obligation_id") == row.obligation_id
                 and check.get("payer_role") == "auditor"
                 and check.get("payee_role") == "independent_check_service"
                 and check.get("amount_minor") == CHECK_PRICE_MINOR
                 and check.get("transaction_hash") == debit["transaction_hash"]
                 and check.get("buyer_records")
                     == protected_buyer_records(row.truth).checked_result()
                 and check.get("oracle_status")
                     == ("PASS" if row.truth == "good" else "FAIL"),
                 "incomplete native check receipt or protected records differ")
        _require(debit_tx.get("from", "").lower() == roles["evaluator"].lower()
                 and debit_tx.get("to", "").lower() == token.lower()
                 and debit_tx.get("input", "").lower() == _command(
                     str(CAST), "calldata", "transfer(address,uint256)",
                     roles["outsider"], str(CHECK_PRICE_MINOR)).lower(),
                 "incomplete check calldata or signer differs")
        _transfer(debit["raw_receipt"], token, roles["evaluator"],
                  roles["outsider"], CHECK_PRICE_MINOR)
        _require(check_raw.get("before") == endowment["after"]
                 and check_raw.get("after") == partial["last_snapshot"],
                 "incomplete check debit snapshots differ")
    expected_delta = {"evaluator": AUDITOR_CHECK_ENDOWMENT_MINOR
                     - (CHECK_PRICE_MINOR if check else 0),
                     "outsider": CHECK_PRICE_MINOR if check else 0}
    _require(all(last[role] - submitted[role] == expected_delta.get(role, 0)
                 for role in (*roles, "escrow"))
             and partial["last_snapshot"]["total_supply_minor_units"] ==
                 partial["submitted"]["total_supply_minor_units"]
                    + AUDITOR_CHECK_ENDOWMENT_MINOR,
             "incomplete last state does not prove zero provider payout/refund")
    return {
        "status": "OBSERVED_INCOMPLETE", "verdict": None,
        "retainer_payer_role": row.payer_role, "retainer_payee_role": "auditor",
        "retainer_minor": FEE_MINOR,
        "retainer_transaction_hash": xverified["transaction_hash"],
        "retainer_raw_sha256": _hash(xraw),
        "check_paid": check is not None,
        "check_debit_minor": CHECK_PRICE_MINOR if check else 0,
        "check_transaction_hash": check["transaction_hash"] if check else None,
        "check_raw_sha256": _hash(check_path) if check else None,
        "oracle_status": xverified["oracle_status"],
        "terminal_transaction_observed": False,
        "job_state": "Submitted",
        "provider_paid_minor": 0, "client_refunded_minor": 0,
        "wrongful_provider_payout": False,
        "job_raw_sha256": None,
        "partial_job_raw_sha256": _hash(partial_path),
        "bridge_sha256": _hash(bridge_path),
        "model_tier": model_tier,
        "transaction_tier": "NATIVE_LOCAL_PROTOCOL",
        "x402_intake_component_model_tier": xverified["model_tier"],
        "x402_exact_eip3009_and_replay_verified": True,
        "native_state_scope": "SAVED_LOCAL_CHAIN_HEAD_ONLY",
        "two_local_chains_atomic": False, "psp_capture": False,
    }
