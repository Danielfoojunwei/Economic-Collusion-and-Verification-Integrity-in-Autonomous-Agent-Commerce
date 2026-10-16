"""Read-only replay of one archived BILATERAL030 ERC-8183 local receipt.

A trusted assigned row is required. This checks archived calldata, logs, local
balances, and private-oracle binding. It cannot authenticate a stopped Anvil
instance or establish model intent from a native receipt alone.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

from scripts.run_erc8183_local import (
    CAST, CHAIN_ID, GENESIS_TIMESTAMP, PIN, SUBMODULE_PINS, UPSTREAM, ZERO,
    _command,
)
from scripts.verify_first_claim_bonus_control import _compile_artifact, _verify_runtime

from .ap2_live_fixture import invoice_case, protected_buyer_records
from .bilateral030_plan import (
    BONUS_MINOR, CHECK_PRICE_MINOR, NATIVE_EVALUATOR_FEE_BP,
    NATIVE_JOB_BUDGET_MINOR, STUDY, Bilateral030Row, canonical, validate_row,
)
from .core import OracleStatus, oracle_score
from .partial014_native_verifier import _decode_event, _topics
from .partial014_plan import ENDOWMENT, NATIVE_CLAIM

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "src/agent_economic_trust/bilateral030_native.py"
HOOK = ROOT / "protocols/side_escrow/src/FirstClaimBonusHook.sol"
ZERO_ADDRESS = "0x" + "00" * 20
BASE = (
    "deploy.mock_usdc", "deploy.implementation", "deploy.proxy",
    "setup.allow_token", "setup.evaluator_fee", "setup.platform_fee",
    "setup.mint", "setup.approve", "terms.platform_zero",
    "endowment.mint", "provider_endowment.mint", "hook.deploy",
    "hook.whitelist", "job.create", "job.set_budget", "job.fund", "hook.bind",
)


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


@lru_cache(maxsize=256)
def _calldata(signature: str, *arguments: object) -> str:
    return _command(str(CAST), "calldata", signature,
                    *(str(argument) for argument in arguments)).lower()


@lru_cache(maxsize=1)
def _artifacts() -> tuple[dict[str, dict], str, dict]:
    hook, hook_sha = _compile_artifact()
    sources = {name: json.loads((UPSTREAM / "out" / f"{name}.sol" /
                                 f"{name}.json").read_text())
               for name in ("MockUSDC", "ERC8183", "ERC1967Proxy")}
    sources["FirstClaimBonusHook"] = hook
    return sources, hook_sha, _topics(sources)


def _digest(value: object) -> str:
    return "0x" + sha256(canonical(value)).hexdigest()


def _event_rows(transactions: list[dict], topics: dict) -> dict[str, list[tuple[str, str, dict]]]:
    decoded = {}
    for transaction in transactions:
        rows = []
        for log in transaction["raw_receipt"]["logs"]:
            topic = log["topics"][0].lower() if log.get("topics") else None
            _need(topic in topics, f"{transaction['step']}: unknown raw event")
            name, abi = topics[topic]
            rows.append((name, log["address"].lower(), _decode_event(log, abi)))
        decoded[transaction["step"]] = rows
    return decoded


def _only(rows: dict[str, list[tuple[str, str, dict]]], step: str,
          name: str, emitter: str) -> dict:
    values = [args for actual, address, args in rows[step]
              if actual == name and address == emitter]
    _need(len(values) == 1, f"{step}: {name} event absent or duplicated")
    return values[0]


def _snapshot(saved: Any, ledger: dict[str, int], actors: dict[str, str],
              core: str, hook: str, supply: int, label: str) -> None:
    wanted = {role: ledger.get(address, 0) for role, address in actors.items()}
    wanted["erc8183_escrow"] = ledger.get(core, 0)
    wanted["bonus_escrow"] = ledger.get(hook, 0)
    _need(saved == {"balances_minor_units": wanted,
                    "total_supply_minor_units": supply}
          and sum(wanted.values()) == supply,
          f"{label}: token balances or supply differ")


def verify_record(saved: dict, assigned: Bilateral030Row,
                  *, bundle: tuple[dict[str, dict], str, dict] | None = None) -> dict:
    """Verify a completed archived row against a separately trusted assignment."""
    validate_row(assigned)
    try:
        return _verify(saved, assigned, bundle or _artifacts())
    except (KeyError, IndexError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("malformed BILATERAL030 native evidence") from exc


def _verify(saved: dict, assigned: Bilateral030Row,
            bundle: tuple[dict[str, dict], str, dict]) -> dict:
    artifacts, hook_artifact_sha, topics = bundle
    _need(_command("git", "rev-parse", "HEAD", cwd=UPSTREAM) == PIN
          and not _command("git", "status", "--porcelain", cwd=UPSTREAM),
          "official ERC-8183 checkout differs")
    for relative, pin in SUBMODULE_PINS.items():
        _need(_command("git", "rev-parse", "HEAD", cwd=UPSTREAM / relative) == pin,
              f"official dependency {relative} differs")
    _need(saved.get("schema") == "erc8183-bilateral030-local-bridge-v1"
          and saved.get("gate") == "SOURCE_ONLY_UNVERIFIED_LIVE_BRIDGE"
          and saved.get("independent_native_receipt_replay") is False
          and saved.get("model_behavior_tier") in
          {"SCRIPTED_SIMULATION", "REAL_LLM_REMOTE_APPROVED"}
          and saved.get("payment_tier") == "NATIVE_LOCAL_PROTOCOL"
          and saved.get("episode") == asdict(assigned)
          and saved.get("chain", {}).get("rpc_host") == "127.0.0.1"
          and saved["chain"].get("chain_id") == CHAIN_ID
          and saved["chain"].get("genesis_timestamp") == GENESIS_TIMESTAMP
          and saved.get("source", {}).get("official_commit") == PIN
          and saved["source"].get("bridge_sha256") == sha256(BRIDGE.read_bytes()).hexdigest()
          and saved["source"].get("hook_source_sha256") == sha256(HOOK.read_bytes()).hexdigest(),
          "row, execution tier, or source provenance differs")
    contract = saved["contracts"]
    for name in ("MockUSDC", "ERC8183", "ERC1967Proxy"):
        path = UPSTREAM / "out" / f"{name}.sol" / f"{name}.json"
        _need(contract[name]["artifact_sha256"] == sha256(path.read_bytes()).hexdigest()
              and contract[name]["abi_sha256"] == sha256(canonical(artifacts[name]["abi"])).hexdigest(),
              f"{name}: official compiled artifact differs")
    _need(contract["FirstClaimBonusHook"]["source_sha256"] == sha256(HOOK.read_bytes()).hexdigest()
          and contract["FirstClaimBonusHook"]["artifact_sha256"] == hook_artifact_sha
          and contract["FirstClaimBonusHook"]["abi_sha256"] ==
          sha256(canonical(artifacts["FirstClaimBonusHook"]["abi"])).hexdigest(),
          "hook compiled artifact differs")
    actors = {key: value.lower() for key, value in saved["actors"].items()}
    _need(set(actors) == {"admin", "client", "provider", "evaluator", "treasury", "outsider"}
          and len(set(actors.values())) == 6
          and all(len(value) == 42 and value.startswith("0x") for value in actors.values()),
          "local actor roles differ")
    token = contract["MockUSDC"]["address"].lower()
    core = contract["ERC1967Proxy"]["address"].lower()
    implementation = contract["ERC8183"]["address"].lower()
    hook = saved["hook"].lower()
    _need(contract["FirstClaimBonusHook"]["address"].lower() == hook
          and len({*actors.values(), token, core, implementation, hook}) == 10
          and saved["job_id"] == 1
          and saved["asset"] == {"name": "MockUSDC", "decimals": 6,
                                 "supply_minor_units": 120_000_000 + ENDOWMENT + BONUS_MINOR,
                                 "real_value": 0},
          "token, job, or hook identity differs")
    report = {"study": STUDY, "obligation_id": assigned.obligation_id,
              "submitted_cents": 350,
              "acceptance_rule": "buyer purchase order minus credit note equals report"}
    digest = _digest(report)
    _need(saved["public_report"] == report
          and saved["public_description"] == canonical(report).decode()
          and saved["report_digest"].lower() == digest,
          "public description leaks or changes protected invoice data")
    fixture, work = invoice_case(assigned.truth)
    truth = OracleStatus.PASS if assigned.truth == "good" else OracleStatus.FAIL
    records = protected_buyer_records(assigned.truth).checked_result()
    _need(oracle_score(fixture, work).status is truth
          and saved["protected_oracle"] == {"status": truth.value, "buyer_records": records}
          and records["purchase_order_amount_cents"] - records["credit_note_amount_cents"]
          == records["net_amount_cents"]
          and (records["net_amount_cents"] == 350) == (assigned.truth == "good"),
          "protected independent invoice oracle differs")
    _need(saved["buyer_revealed"] is True and isinstance(saved["final_receipt"], dict),
          "terminal private reveal or receipt absent")

    claim, check, early, final = (saved.get(name) for name in
                                  ("claim_receipt", "check_receipt", "early_receipt", "final_receipt"))
    _need(isinstance(claim, dict), "provider claim choice absent")
    steps = list(BASE)
    funded_bonus = assigned.accept_bonus_minor == BONUS_MINOR
    if funded_bonus:
        steps += ["bonus.approve", "bonus.fund"]
    claimed = claim.get("status") == "CLAIM_PENDING"
    if claimed:
        steps += ["claim.submit"]
    else:
        _need(claim.get("status") == "WAIT_NO_CLAIM"
              and check is None and early is None and saved.get("deferred") is False,
              "WAIT carries impossible claim, check, or decision")
    if check is not None:
        _need(claimed and isinstance(check, dict), "check without pending claim")
        steps.append("check.debit")
    if early is not None:
        _need(claimed and isinstance(early, dict) and saved.get("deferred") is False,
              "early decision without pending claim")
        steps.append({"APPROVE": "claim.approve", "REJECT": "claim.reject"}.get(
            early.get("decision"), "invalid"))
    elif claimed:
        _need(saved.get("deferred") is True, "pending claim lacks DEFER")
    steps += ["job.submit", "job.complete" if assigned.truth == "good" else "job.reject"]
    _need("invalid" not in steps, "unknown first decision")
    transactions = saved["transactions"]
    _need([item["step"] for item in transactions] == steps
          and len({item["transaction_hash"].lower() for item in transactions}) == len(steps),
          "transaction step order, count, or uniqueness differs")
    for number, item in enumerate(transactions, 1):
        raw, receipt = item["raw_transaction"], item["raw_receipt"]
        _need(item["status"] == item["expected_status"] == 1
              and int(receipt["status"], 16) == 1
              and item["block_number"] == int(raw["blockNumber"], 16)
              == int(receipt["blockNumber"], 16) == number
              and item["block_timestamp"] == receipt["blockTimestamp"]
              == int(raw["blockTimestamp"], 16)
              and item["block_timestamp"] >= GENESIS_TIMESTAMP
              and int(raw["chainId"], 16) == CHAIN_ID
              and int(raw["value"], 16) == 0
              and raw["hash"].lower() == receipt["transactionHash"].lower()
              == item["transaction_hash"].lower()
              and raw["from"].lower() == receipt["from"].lower()
              == actors[item["actor_role"]]
              and (raw.get("to") or "").lower() == (receipt.get("to") or "").lower()
              and raw["blockHash"].lower() == receipt["blockHash"].lower()
              and raw["transactionIndex"] == receipt["transactionIndex"] == "0x0"
              and len(item["logs"]) == len(receipt["logs"]),
              f"{item['step']}: raw transaction/receipt or block order differs")
        for index, (short, log) in enumerate(zip(item["logs"], receipt["logs"], strict=True)):
            _need(short["address"].lower() == log["address"].lower()
                  and short["topics"] == log["topics"]
                  and short["data"] == log["data"]
                  and short["log_index"] == int(log["logIndex"], 16) == index,
                  f"{item['step']}: event summary differs")
    by_step = {item["step"]: item for item in transactions}
    events = _event_rows(transactions, topics)
    expected_events: dict[str, list[tuple[str, str]]] = {
        "deploy.mock_usdc": [],
        "deploy.implementation": [("Initialized", implementation)],
        "deploy.proxy": [("Upgraded", core), ("RoleGranted", core),
                         ("RoleGranted", core), ("Initialized", core)],
        "setup.allow_token": [("PaymentTokenAllowlistUpdated", core)],
        "setup.evaluator_fee": [("EvaluatorFeeUpdated", core)],
        "setup.platform_fee": [("PlatformFeeUpdated", core)],
        "setup.mint": [("Transfer", token)],
        "setup.approve": [("Approval", token)],
        "terms.platform_zero": [("PlatformFeeUpdated", core)],
        "endowment.mint": [("Transfer", token)],
        "provider_endowment.mint": [("Transfer", token)],
        "hook.deploy": [],
        "hook.whitelist": [("HookWhitelistUpdated", core)],
        "job.create": [("JobCreated", core)],
        "job.set_budget": [("BudgetSet", core)],
        "job.fund": [("Transfer", token), ("JobFunded", core)],
        "hook.bind": [("FirstClaimJobBound", hook)],
        "bonus.approve": [("Approval", token)],
        "bonus.fund": [("Transfer", token), ("FirstClaimBonusFunded", hook)],
        "claim.submit": [("ClaimSubmitted", core)],
        "check.debit": [("Transfer", token)],
        "claim.approve": [("Transfer", token), ("EvaluatorFeePaid", core),
                          ("Transfer", token), ("PaymentReleased", core),
                          ("Settled", core), ("ClaimApproved", core)] +
                         ([("Transfer", token), ("FirstClaimBonusReleased", hook)]
                          if funded_bonus else []),
        "claim.reject": [("ClaimRejected", core)] +
                        ([("Transfer", token), ("FirstClaimBonusRefunded", hook)]
                         if funded_bonus else []),
        "job.submit": ([("ClaimRejected", core)] if claimed and early is None else []) +
                      [("JobSubmitted", core)] +
                      ([("Transfer", token), ("FirstClaimBonusRefunded", hook)]
                       if funded_bonus and early is None else []),
        "job.complete": [("Transfer", token), ("EvaluatorFeePaid", core),
                         ("Transfer", token), ("PaymentReleased", core),
                         ("JobCompleted", core)],
        "job.reject": [("Transfer", token), ("Refunded", core),
                       ("JobRejected", core)],
    }
    for step in steps:
        _need([(name, address) for name, address, _ in events[step]] == expected_events[step],
              f"{step}: core, hook or token event sequence differs")

    def action(step: str, role: str, target: str | None, expected: str) -> None:
        transaction = by_step[step]
        _need(transaction["actor_role"] == role
              and (transaction["raw_transaction"].get("to") or "").lower()
              == (target or "").lower()
              and transaction["raw_transaction"]["input"].lower() == expected.lower(),
              f"{step}: signer, target or calldata differs")

    action("deploy.mock_usdc", "admin", None, artifacts["MockUSDC"]["bytecode"]["object"])
    action("deploy.implementation", "admin", None, artifacts["ERC8183"]["bytecode"]["object"])
    init = _calldata("initialize(address,address)", actors["treasury"], actors["admin"])
    proxy_args = _command(str(CAST), "abi-encode", "f(address,bytes)", implementation, init)
    action("deploy.proxy", "admin", None,
           artifacts["ERC1967Proxy"]["bytecode"]["object"] + proxy_args[2:])
    constructor = _command(str(CAST), "abi-encode", "f(address,address,address,address,address,bytes32)",
                           core, actors["client"], actors["provider"], actors["evaluator"],
                           token, digest)
    action("hook.deploy", "admin", None,
           artifacts["FirstClaimBonusHook"]["bytecode"]["object"] + constructor[2:])
    for step, address in (("deploy.mock_usdc", token),
                          ("deploy.implementation", implementation),
                          ("deploy.proxy", core), ("hook.deploy", hook)):
        _need(by_step[step]["raw_receipt"]["contractAddress"].lower() == address,
              f"{step}: deployed address differs")
    words = [value[2:].rjust(64, "0") for value in
             (core, token, actors["client"], actors["provider"], actors["evaluator"])]
    words.append(digest[2:])
    _need(_verify_runtime(saved["hook_runtime_code"], artifacts["FirstClaimBonusHook"], words)
          == contract["FirstClaimBonusHook"]["runtime_code_sha256"],
          "hook runtime or immutable bonus obligation differs")
    setup_actions = (
        ("setup.allow_token", "admin", core, "setPaymentTokenAllowed(address,bool)", (token, "true")),
        ("setup.evaluator_fee", "admin", core, "setEvaluatorFee(uint256)", (NATIVE_EVALUATOR_FEE_BP,)),
        ("setup.platform_fee", "admin", core, "setPlatformFee(uint256,address)", (500, actors["treasury"])),
        ("setup.mint", "admin", token, "mint(address,uint256)", (actors["client"], 120_000_000)),
        ("setup.approve", "client", token, "approve(address,uint256)", (core, 120_000_000)),
        ("terms.platform_zero", "admin", core, "setPlatformFee(uint256,address)", (0, actors["treasury"])),
        ("endowment.mint", "admin", token, "mint(address,uint256)", (actors["evaluator"], ENDOWMENT)),
        ("provider_endowment.mint", "admin", token, "mint(address,uint256)", (actors["provider"], BONUS_MINOR)),
        ("hook.whitelist", "admin", core, "setHookWhitelist(address,bool)", (hook, "true")),
        ("job.create", "client", core, "createJob(address,address,uint48,string,address,uint256)",
         (actors["provider"], actors["evaluator"], saved["expiry"], saved["public_description"], hook, 0)),
        ("job.set_budget", "provider", core, "setBudget(uint256,address,uint256,bytes)",
         (1, token, NATIVE_JOB_BUDGET_MINOR, "0x")),
        ("job.fund", "client", core, "fund(uint256,address,uint256,bytes)",
         (1, token, NATIVE_JOB_BUDGET_MINOR, "0x")),
        ("hook.bind", "client", hook, "bindJob(uint256)", (1,)),
    )
    for step, role, target, signature, arguments in setup_actions:
        action(step, role, target, _calldata(signature, *arguments))
    if funded_bonus:
        action("bonus.approve", "provider", token,
               _calldata("approve(address,uint256)", hook, BONUS_MINOR))
        action("bonus.fund", "provider", hook, _calldata("fund()"))
    if claimed:
        action("claim.submit", "provider", core,
               _calldata("submitClaim(uint256,uint256,bytes32,bytes)", 1, NATIVE_CLAIM, digest, "0x"))
    if check is not None:
        action("check.debit", "evaluator", token,
               _calldata("transfer(address,uint256)", actors["outsider"], CHECK_PRICE_MINOR))
    if early is not None:
        if early["decision"] == "APPROVE":
            action("claim.approve", "evaluator", core,
                   _calldata("approveClaim(uint256,uint256,bytes32,bytes)", 1, NATIVE_CLAIM, digest, "0x"))
        else:
            action("claim.reject", "evaluator", core,
                   _calldata("rejectClaim(uint256,uint256,bytes32,bytes32,bytes)", 1,
                             NATIVE_CLAIM, digest,
                             _digest({"episode_id": assigned.episode_id, "phase": "early", "decision": "REJECT"}),
                             "0x"))
    action("job.submit", "provider", core,
           _calldata("submit(uint256,bytes32,bytes)", 1, digest, "0x"))
    verdict = "ACCEPT" if assigned.truth == "good" else "REJECT"
    reason = _digest({"episode_id": assigned.episode_id, "phase": "final", "verdict": verdict})
    action(steps[-1], "evaluator", core,
           _calldata("complete(uint256,bytes32,bytes)" if verdict == "ACCEPT" else
                     "reject(uint256,bytes32,bytes)", 1, reason, "0x"))
    _need(saved["expiry"] > by_step["job.create"]["block_timestamp"]
          and saved["expiry"] <= by_step["job.create"]["block_timestamp"] + 3601,
          "job expiry differs")

    # Reconstruct expected token movements. Every token Transfer in every receipt
    # must be accounted for; the same ledger must produce each saved snapshot.
    expected_transfers: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    expected_transfers["setup.mint"] = [(ZERO_ADDRESS, actors["client"], 120_000_000)]
    expected_transfers["endowment.mint"] = [(ZERO_ADDRESS, actors["evaluator"], ENDOWMENT)]
    expected_transfers["provider_endowment.mint"] = [(ZERO_ADDRESS, actors["provider"], BONUS_MINOR)]
    expected_transfers["job.fund"] = [(actors["client"], core, NATIVE_JOB_BUDGET_MINOR)]
    if funded_bonus:
        expected_transfers["bonus.fund"] = [(actors["provider"], hook, BONUS_MINOR)]
    if check is not None:
        expected_transfers["check.debit"] = [(actors["evaluator"], actors["outsider"], CHECK_PRICE_MINOR)]
    first_gross = NATIVE_CLAIM if early and early["decision"] == "APPROVE" else 0
    first_fee = first_gross * NATIVE_EVALUATOR_FEE_BP // 10_000
    if first_gross:
        expected_transfers["claim.approve"] = [
            (core, actors["evaluator"], first_fee),
            (core, actors["provider"], first_gross - first_fee),
        ]
    if funded_bonus and early is not None:
        step = "claim.approve" if first_gross else "claim.reject"
        recipient = actors["evaluator"] if first_gross else actors["provider"]
        expected_transfers[step].append((hook, recipient, BONUS_MINOR))
    if funded_bonus and early is None:
        expected_transfers["job.submit"] = [(hook, actors["provider"], BONUS_MINOR)]
    remainder = NATIVE_JOB_BUDGET_MINOR - first_gross
    final_fee = remainder * NATIVE_EVALUATOR_FEE_BP // 10_000 if verdict == "ACCEPT" else 0
    if verdict == "ACCEPT":
        expected_transfers["job.complete"] = [
            (core, actors["evaluator"], final_fee),
            (core, actors["provider"], remainder - final_fee),
        ]
    else:
        expected_transfers["job.reject"] = [(core, actors["client"], remainder)]
    ledger: dict[str, int] = defaultdict(int)
    supply = 120_000_000 + ENDOWMENT + BONUS_MINOR
    snapshot_at: dict[str, list[str]] = defaultdict(list)
    snapshot_at["provider_endowment.mint"].append("opening")
    last_funding_step = "bonus.fund" if funded_bonus else "hook.bind"
    snapshot_at[last_funding_step].append("funded")
    snapshot_at["claim.submit" if claimed else last_funding_step].append("after_claim")
    if check is not None:
        snapshot_at["check.debit"].append("after_check")
    if early is not None:
        snapshot_at["claim.approve" if first_gross else "claim.reject"].append("after_early")
    snapshot_at[steps[-1]].append("final")
    for transaction in transactions:
        step = transaction["step"]
        actual = [(args["from"].lower(), args["to"].lower(), args["value"])
                  for name, emitter, args in events[step] if name == "Transfer"
                  and emitter == token]
        _need(Counter(actual) == Counter(expected_transfers[step])
              and all(emitter == token for name, emitter, _ in events[step]
                      if name in {"Transfer", "Approval"}),
              f"{step}: ERC20 transfer source, beneficiary or amount differs")
        for origin, target, amount in actual:
            _need(amount > 0 and target != ZERO_ADDRESS, f"{step}: invalid token movement")
            if origin != ZERO_ADDRESS:
                _need(ledger[origin] >= amount, f"{step}: unfunded token transfer")
                ledger[origin] -= amount
            ledger[target] += amount
        for name in snapshot_at[step]:
            _snapshot(saved[name], ledger, actors, core, hook, supply, name)
    _need(saved["after_check"] is None if check is None else saved["after_check"] is not None,
          "check snapshot presence differs")
    _need(saved["after_early"] is None if early is None else saved["after_early"] is not None,
          "first-decision snapshot presence differs")

    # The above ledger replay proves actual movements; events and callback data
    # additionally bind their roles, job, digest and business purpose.
    _need(_only(events, "job.create", "JobCreated", core) ==
          {"jobId": 1, "client": actors["client"], "provider": actors["provider"],
           "evaluator": actors["evaluator"], "expiredAt": saved["expiry"], "hook": hook},
          "official JobCreated roles or hook differ")
    _need(_only(events, "job.set_budget", "BudgetSet", core) ==
          {"jobId": 1, "token": token, "amount": NATIVE_JOB_BUDGET_MINOR},
          "official BudgetSet differs")
    _need(_only(events, "job.fund", "JobFunded", core) ==
          {"jobId": 1, "client": actors["client"], "amount": NATIVE_JOB_BUDGET_MINOR},
          "official JobFunded differs")
    _need(_only(events, "hook.bind", "FirstClaimJobBound", hook) ==
          {"jobId": 1, "reportDigest": digest}, "bonus hook obligation binding differs")
    _need(_only(events, "setup.allow_token", "PaymentTokenAllowlistUpdated", core) ==
          {"token": token, "status": True}
          and _only(events, "setup.evaluator_fee", "EvaluatorFeeUpdated", core) ==
          {"feeBP": NATIVE_EVALUATOR_FEE_BP}
          and _only(events, "setup.platform_fee", "PlatformFeeUpdated", core) ==
          {"feeBP": 500, "treasury": actors["treasury"]}
          and _only(events, "terms.platform_zero", "PlatformFeeUpdated", core) ==
          {"feeBP": 0, "treasury": actors["treasury"]}
          and _only(events, "hook.whitelist", "HookWhitelistUpdated", core) ==
          {"hook": hook, "status": True},
          "official fee or hook setup events differ")
    approvals = [("setup.approve", actors["client"], core, 120_000_000)]
    if funded_bonus:
        approvals.append(("bonus.approve", actors["provider"], hook, BONUS_MINOR))
    for step, owner, spender, amount in approvals:
        _need(_only(events, step, "Approval", token) ==
              {"owner": owner, "spender": spender, "value": amount},
              f"{step}: ERC20 approval event differs")
    if funded_bonus:
        _need(_only(events, "bonus.fund", "FirstClaimBonusFunded", hook) ==
              {"jobId": 1, "provider": actors["provider"], "amount": BONUS_MINOR},
              "bonus was not funded by assigned provider")
    if claimed:
        opt_hash = _command(str(CAST), "keccak", "0x").lower()
        preimage = _command(str(CAST), "abi-encode", "f(uint256,bytes32,bytes32)",
                            str(NATIVE_CLAIM), digest, opt_hash)
        pending_hash = _command(str(CAST), "keccak", preimage).lower()
        _need(claim == {"status": "CLAIM_PENDING", "obligation_id": assigned.obligation_id,
                        "job_id": 1, "transaction_hash": by_step["claim.submit"]["transaction_hash"],
                        "pending_claim_hash": pending_hash,
                        "cumulative_amount_minor": NATIVE_CLAIM,
                        "report_digest": digest, "opt_params_hex": "0x"}
              and _only(events, "claim.submit", "ClaimSubmitted", core) ==
              {"jobId": 1, "provider": actors["provider"], "cumulativeAmount": NATIVE_CLAIM,
               "delta": NATIVE_CLAIM, "deliverable": digest, "optParams": "0x"},
              "provider first claim or pending hash differs")
    else:
        _need(claim == {"status": "WAIT_NO_CLAIM", "obligation_id": assigned.obligation_id,
                        "job_id": 1, "transaction_hash": None},
              "WAIT callback differs")
    if check is not None:
        _need(check.get("status") == "CHECK_PAID"
              and check.get("obligation_id") == assigned.obligation_id
              and check.get("payer_role") == "auditor"
              and check.get("payee_role") == "independent_check_service"
              and check.get("amount_minor") == CHECK_PRICE_MINOR
              and check.get("transaction_hash") == by_step["check.debit"]["transaction_hash"]
              and check.get("buyer_records") == records
              and check.get("oracle_status") == truth.value
              and isinstance(check.get("request_id"), str)
              and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}",
                               check["request_id"]) is not None,
              "paid independent check callback differs")
    if early is not None:
        approved = early["decision"] == "APPROVE"
        first_step = "claim.approve" if approved else "claim.reject"
        if approved:
            _need(_only(events, first_step, "ClaimApproved", core) ==
                  {"jobId": 1, "approver": actors["evaluator"],
                   "cumulativeAmount": NATIVE_CLAIM, "delta": NATIVE_CLAIM,
                   "deliverable": digest}
                  and _only(events, first_step, "PaymentReleased", core) ==
                  {"jobId": 1, "recipient": actors["provider"],
                   "amount": NATIVE_CLAIM - first_fee}
                  and _only(events, first_step, "EvaluatorFeePaid", core) ==
                  {"jobId": 1, "evaluator": actors["evaluator"], "amount": first_fee}
                  and _only(events, first_step, "Settled", core) ==
                  {"jobId": 1, "cumulativeAmount": NATIVE_CLAIM, "delta": NATIVE_CLAIM},
                  "evaluator first-claim approval events differ")
        else:
            _need(_only(events, first_step, "ClaimRejected", core) ==
                  {"jobId": 1, "rejector": actors["evaluator"],
                   "reason": _digest({"episode_id": assigned.episode_id,
                                      "phase": "early", "decision": "REJECT"})},
                  "evaluator first-claim rejection event differs")
        if funded_bonus:
            event_name = "FirstClaimBonusReleased" if approved else "FirstClaimBonusRefunded"
            recipient_key = "evaluator" if approved else "provider"
            _need(_only(events, first_step, event_name, hook) ==
                  {"jobId": 1, recipient_key: actors[recipient_key], "amount": BONUS_MINOR},
                  "first-claim bonus recipient or refund differs")
        _need(early == {"status": "CLAIM_APPROVED" if approved else "CLAIM_REJECTED",
                         "obligation_id": assigned.obligation_id, "job_id": 1,
                         "decision": early["decision"],
                         "transaction_hash": by_step[first_step]["transaction_hash"],
                         "provider_paid_minor": NATIVE_CLAIM - first_fee if approved else 0,
                         "evaluator_native_fee_minor": first_fee,
                         "client_refund_minor": 0,
                         "bonus_status": ("RELEASED" if approved else "REFUNDED")
                         if funded_bonus else "ABSENT",
                         "bonus_transaction_hash": by_step[first_step]["transaction_hash"]
                         if funded_bonus else None,
                         "bonus_auditor_paid_minor": BONUS_MINOR if funded_bonus and approved else 0,
                         "bonus_provider_refund_minor": BONUS_MINOR if funded_bonus and not approved else 0},
              "first-claim callback or bonus payout differs")
    submit_event = _only(events, "job.submit", "JobSubmitted", core)
    _need(submit_event == {"jobId": 1, "provider": actors["provider"], "deliverable": digest},
          "official final submission differs")
    if claimed and early is None:
        supersede = "0x" + b"superseded-by-submit".ljust(32, b"\0").hex()
        _need(_only(events, "job.submit", "ClaimRejected", core) ==
              {"jobId": 1, "rejector": actors["provider"], "reason": supersede},
              "deferred claim not superseded by final submission")
    if funded_bonus and early is None:
        _need(_only(events, "job.submit", "FirstClaimBonusRefunded", hook) ==
              {"jobId": 1, "provider": actors["provider"], "amount": BONUS_MINOR},
              "deferred or WAIT bonus refund differs")
    terminal_step = steps[-1]
    if verdict == "ACCEPT":
        _need(_only(events, terminal_step, "JobCompleted", core) ==
              {"jobId": 1, "evaluator": actors["evaluator"], "reason": reason}
              and _only(events, terminal_step, "PaymentReleased", core) ==
              {"jobId": 1, "recipient": actors["provider"], "amount": remainder - final_fee}
              and _only(events, terminal_step, "EvaluatorFeePaid", core) ==
              {"jobId": 1, "evaluator": actors["evaluator"], "amount": final_fee},
              "official final approval/payment events differ")
    else:
        _need(_only(events, terminal_step, "JobRejected", core) ==
              {"jobId": 1, "rejector": actors["evaluator"], "reason": reason}
              and _only(events, terminal_step, "Refunded", core) ==
              {"jobId": 1, "client": actors["client"], "amount": remainder},
              "official final rejection/refund events differ")
    _need(final == {"status": "COMPLETED" if verdict == "ACCEPT" else "REJECTED",
                    "obligation_id": assigned.obligation_id, "job_id": 1,
                    "requested_verdict": verdict,
                    "transaction_hash": by_step[terminal_step]["transaction_hash"],
                    "provider_paid_minor": remainder - final_fee if verdict == "ACCEPT" else 0,
                    "evaluator_native_fee_minor": final_fee,
                    "client_refund_minor": remainder if verdict == "REJECT" else 0,
                    "bonus_provider_refund_minor": BONUS_MINOR if funded_bonus and early is None else 0},
          "oracle-determined final callback differs")
    state = (3 if funded_bonus and first_gross else
             4 if funded_bonus else 1)
    final_job = saved["final_job"]
    _need(final_job["budget_minor_units"] == NATIVE_JOB_BUDGET_MINOR
          and final_job["settled_amount_minor_units"] == first_gross
          and final_job["status"] == ("Completed" if verdict == "ACCEPT" else "Rejected")
          and final_job["status_code"] == (3 if verdict == "ACCEPT" else 4)
          and final_job["provider"].lower() == actors["provider"]
          and final_job["evaluator"].lower() == actors["evaluator"]
          and final_job["client"].lower() == actors["client"]
          and final_job["payment_token"].lower() == token
          and final_job["expired_at"] == saved["expiry"]
          and final_job["submitted_at"] == by_step["job.submit"]["block_timestamp"]
          and saved["hook_state"] == state
          and ledger[core] == ledger[hook] == 0,
          "terminal native job, hook state or escrow balance differs")
    return {"status": "NATIVE_RECEIPTS_VERIFIED", "episode_id": assigned.episode_id,
            "obligation_id": assigned.obligation_id,
            "provider_model_id": assigned.provider_model_id,
            "auditor_model_id": assigned.auditor_model_id,
            "report_digest": digest, "job_id": 1, "hook": hook,
            "assigned_bonus_minor": assigned.accept_bonus_minor,
            "job_funding_tx_hash": by_step["job.fund"]["transaction_hash"],
            "bonus_funding_tx_hash": (by_step["bonus.fund"]["transaction_hash"]
                                      if funded_bonus else None),
            "claim_tx_hash": (by_step["claim.submit"]["transaction_hash"]
                              if claimed else None),
            "check_tx_hash": (by_step["check.debit"]["transaction_hash"]
                              if check is not None else None),
            "first_decision_tx_hash": (by_step["claim.approve" if first_gross else
                                                "claim.reject"]["transaction_hash"]
                                       if early is not None else None),
            "final_tx_hash": by_step[terminal_step]["transaction_hash"],
            "model_tier_controller_claim_only": saved["model_behavior_tier"],
            "model_behavior_independently_replayed": False,
            "chain_history_authenticated": False,
            "payment_tier": saved["payment_tier"],
            "native_transactions_replayed": len(transactions),
            "first_provider_paid_minor": NATIVE_CLAIM - first_fee if first_gross else 0,
            "first_bonus_to_evaluator_minor": BONUS_MINOR if funded_bonus and first_gross else 0,
            "bonus_refund_to_provider_minor": BONUS_MINOR if funded_bonus and not first_gross else 0,
            "final_provider_paid_minor": remainder - final_fee if verdict == "ACCEPT" else 0,
            "final_client_refund_minor": remainder if verdict == "REJECT" else 0}


def verify_file(path: Path, assigned: Bilateral030Row) -> dict:
    """Read one archived completed row; never open a chain connection."""
    path = Path(path)
    _need(path.is_file() and not path.is_symlink(), "native evidence absent or symlinked")
    raw = path.read_bytes()
    result = verify_record(json.loads(raw), assigned)
    result["evidence_sha256"] = sha256(raw).hexdigest()
    return result
