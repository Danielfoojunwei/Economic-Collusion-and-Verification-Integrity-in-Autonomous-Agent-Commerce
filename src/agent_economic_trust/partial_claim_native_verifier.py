"""Independent replay of official local ERC-8183 milestone-claim receipts.

This verifies an archived local chain *transcript*: it does not authenticate an
Anvil chain after that chain has been destroyed, or turn scripted choices into
live-agent observations. In particular, the first payout is counted even if a
later job rejection refunds the remaining escrow.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from scripts.run_erc8183_local import CAST, PIN, UPSTREAM, ZERO

from .ap2_live_fixture import invoice_case, protected_buyer_records
from .partial_claim_plan import (CLIENT_PREPAID, MILESTONE, NATIVE_CONTINGENT,
                                 PartialClaimRow, STUDY, canonical, digest,
                                 terms as assigned_terms)


ROOT = Path(__file__).resolve().parents[2]
ROLES = {"admin", "client", "provider", "evaluator", "treasury", "outsider"}
HEX32 = re.compile(r"0x[0-9a-fA-F]{64}\Z")


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


@lru_cache(maxsize=256)
def _cast(*args: str) -> str:
    return subprocess.run([str(CAST), *args], check=True, text=True,
                          capture_output=True, timeout=10).stdout.strip().lower()


def _hex(data: str) -> bytes:
    _require(isinstance(data, str) and data.startswith("0x") and len(data) % 2 == 0,
             "malformed ABI hex")
    try:
        return bytes.fromhex(data[2:])
    except ValueError as exc:
        raise ValueError("malformed ABI hex") from exc


def _word(value: int | str) -> bytes:
    if isinstance(value, str) and value.startswith("0x"):
        value = int(value, 16)
    _require(type(value) is int and 0 <= value < 2**256, "invalid ABI word")
    return value.to_bytes(32, "big")


def _selector(signature: str) -> str:
    return _cast("sig", signature)


def _calldata(tx: dict, signature: str, fixed: list[int | str],
              tail: bytes | None = None) -> None:
    actual = _hex(tx["raw_transaction"]["input"])
    expected = bytes.fromhex(_selector(signature)[2:]) + b"".join(_word(x) for x in fixed)
    if tail is not None:
        # All claim methods here end in exactly one dynamic `bytes` argument.
        expected += _word(len(fixed) * 32 + 32)
        expected += _word(len(tail)) + tail + b"\0" * ((-len(tail)) % 32)
    _require(actual == expected, f"{tx['step']}: calldata differs")


def _dynamic_description(tx: dict, roles: dict[str, str], row: PartialClaimRow,
                         report_digest: str) -> None:
    description = canonical({"study": STUDY, "obligation_id": row.obligation_id,
                             "report_digest": report_digest,
                             "milestone_id": MILESTONE, "public_claim_cents": 350,
                             "acceptance_rule": "buyer PO minus credit equals report"})
    raw = _hex(tx["raw_transaction"]["input"])
    _require(raw[:4] == _hex(_selector("createJob(address,address,uint48,string,address,uint256)")),
             "job.create: selector differs")
    _require(len(raw) >= 4 + 6 * 32 + 32, "job.create: malformed ABI")
    words = [raw[4 + n * 32:4 + (n + 1) * 32] for n in range(6)]
    _require(int.from_bytes(words[0], "big") == int(roles["provider"], 16)
             and int.from_bytes(words[1], "big") == int(roles["evaluator"], 16)
             and int.from_bytes(words[4], "big") == 0
             and int.from_bytes(words[5], "big") == 0,
             "job.create: roles or hook differ")
    offset = int.from_bytes(words[3], "big")
    _require(offset == 192 and len(raw) >= 4 + offset + 32, "job.create: description offset differs")
    n = int.from_bytes(raw[4 + offset:4 + offset + 32], "big")
    body = raw[4 + offset + 32:]
    _require(n == len(description) and body == description + b"\0" * ((-n) % 32),
             "job.create: obligation description differs")


def _topics(artifacts: dict[str, dict]) -> dict[str, tuple[str, dict]]:
    result: dict[str, tuple[str, dict]] = {}
    for artifact in artifacts.values():
        for item in artifact["abi"]:
            if item["type"] == "event" and not item.get("anonymous"):
                signature = item["name"] + "(" + ",".join(
                    arg["type"] for arg in item["inputs"]) + ")"
                topic = _cast("keccak", signature)
                _require(topic not in result or result[topic][1] == item,
                         "ambiguous ABI event topic")
                result[topic] = (item["name"], item)
    return result


def _decode_event(log: dict, spec: dict) -> dict[str, Any]:
    inputs = spec["inputs"]
    indexed = [arg for arg in inputs if arg["indexed"]]
    plain = [arg for arg in inputs if not arg["indexed"]]
    _require(len(log["topics"]) == 1 + len(indexed), "event indexed-topic count differs")
    data = _hex(log["data"])
    _require(len(data) >= len(plain) * 32 and len(data) % 32 == 0,
             "event data is not ABI encoded")
    def parse(arg: dict, word: bytes, *, full: bytes | None = None) -> Any:
        typ = arg["type"]
        if typ.startswith("uint"):
            return int.from_bytes(word, "big")
        if typ == "address":
            _require(word[:12] == b"\0" * 12, "noncanonical ABI address")
            return "0x" + word[-20:].hex()
        if typ == "bytes32":
            return "0x" + word.hex()
        if typ == "bytes4":
            _require(word[4:] == b"\0" * 28, "noncanonical ABI bytes4")
            return "0x" + word[:4].hex()
        if typ == "bool":
            _require(int.from_bytes(word, "big") in {0, 1}, "noncanonical ABI bool")
            return bool(int.from_bytes(word, "big"))
        if typ == "bytes":
            _require(full is not None, "indexed dynamic ABI value")
            offset = int.from_bytes(word, "big")
            _require(offset >= len(plain) * 32 and offset % 32 == 0
                     and len(full) >= offset + 32, "event bytes offset differs")
            n = int.from_bytes(full[offset:offset + 32], "big")
            tail = full[offset + 32:]
            _require(len(tail) == ((n + 31) // 32) * 32 and tail[n:] == b"\0" * (len(tail) - n),
                     "event bytes padding differs")
            return "0x" + tail[:n].hex()
        raise ValueError(f"unsupported ABI event type: {typ}")
    values: dict[str, Any] = {}
    i, p = 1, 0
    for arg in inputs:
        if arg["indexed"]:
            values[arg["name"]] = parse(arg, _hex(log["topics"][i])); i += 1
        else:
            values[arg["name"]] = parse(arg, data[p * 32:(p + 1) * 32], full=data); p += 1
    return values


def _one(events: dict[str, list[dict]], step: str, name: str,
         *, required: bool = True) -> dict | None:
    logs = events[step].get(name, [])
    _require(len(logs) == (1 if required else 0), f"{step}: {name} event count differs")
    return logs[0] if required else None


def _snapshot(saved: dict | None, ledger: dict[str, int], roles: dict[str, str],
              core: str, supply: int, label: str) -> None:
    _require(isinstance(saved, dict), f"{label}: missing balance snapshot")
    expected = {role: ledger.get(address, 0) for role, address in roles.items()}
    expected["escrow"] = ledger.get(core, 0)
    _require(saved == {"balances_minor_units": expected,
                       "total_supply_minor_units": supply}
             and sum(expected.values()) == supply, f"{label}: balance/supply differs")


def _job(saved: dict | None, roles: dict[str, str], token: str,
         budget: int, status: str, settled: int, label: str) -> None:
    _require(isinstance(saved, dict) and saved.get("status") == status
             and saved.get("status_code") == {"Funded": 1, "Submitted": 2,
                                              "Completed": 3, "Rejected": 4}[status]
             and saved.get("settled_amount_minor_units") == settled
             and saved.get("budget_minor_units") == budget
             and saved.get("client", "").lower() == roles["client"]
             and saved.get("provider", "").lower() == roles["provider"]
             and saved.get("evaluator", "").lower() == roles["evaluator"]
             and saved.get("payment_token", "").lower() == token,
             f"{label}: job read differs")


def verify_record(e: dict, row: PartialClaimRow | None = None) -> dict:
    """Verify one native record, including first payout and later remainder."""
    try:
        return _verify_record(e, row)
    except (KeyError, TypeError, IndexError, OverflowError, AttributeError) as exc:
        raise ValueError("malformed native evidence") from exc


def _verify_record(e: dict, row: PartialClaimRow | None) -> dict:
    _require(e.get("schema") == "erc8183-partial-claim-native-v1"
             and e.get("model_behavior_tier") in {"SCRIPTED_SIMULATION", "REAL_LLM_REMOTE_APPROVED"}
             and e.get("payment_tier") == "NATIVE_LOCAL_PROTOCOL",
             "native tier/schema differs")
    supplied = PartialClaimRow(**e["episode"])
    _require(asdict(supplied) == e["episode"] and (row is None or supplied == row),
             "assigned row identity differs")
    row = supplied
    term = assigned_terms(row)
    _require(e["terms"] == {k: term[k] for k in (
                 "job_budget_minor", "evaluator_fee_bp", "platform_fee_bp",
                 "client_prepay_minor", "auditor_endowment_minor",
                 "check_price_minor", "claim_cumulative_minor")}
             and e["chain"]["host"] == "127.0.0.1"
             and e["chain"]["chain_id"] == 31337,
             "assigned economics or local chain differs")
    source = e["source"]
    _require(source["repository"] == "https://github.com/erc-8183/base-contracts"
             and source["commit"] == PIN
             and source["native_controller_sha256"] == sha256((ROOT / "src/agent_economic_trust/partial_claim_native.py").read_bytes()).hexdigest()
             and source["fixture_sha256"] == sha256((ROOT / "src/agent_economic_trust/ap2_live_fixture.py").read_bytes()).hexdigest(),
             "official source or controller hash differs")
    _require(subprocess.run(["git", "rev-parse", "HEAD"], cwd=UPSTREAM,
                            check=True, capture_output=True, text=True, timeout=10).stdout.strip() == PIN,
             "official ERC-8183 checkout differs")
    roles = {name: address.lower() for name, address in e["actors"].items()}
    _require(set(roles) == ROLES and len(set(roles.values())) == 6
             and all(re.fullmatch(r"0x[0-9a-f]{40}", address) for address in roles.values()),
             "native role addresses differ")
    artifacts = {}
    for name in ("MockUSDC", "ERC8183", "ERC1967Proxy"):
        saved = e["contracts"][name]
        path = UPSTREAM / "out" / f"{name}.sol" / f"{name}.json"
        _require(path.is_file() and saved["artifact_sha256"] == sha256(path.read_bytes()).hexdigest()
                 and Path(saved["artifact_path"]) == path,
                 f"{name}: compiled artifact differs")
        artifact = json.loads(path.read_text())
        abi_hash = sha256(json.dumps(artifact["abi"], sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()
        _require(saved["abi_sha256"] == abi_hash, f"{name}: ABI differs")
        artifacts[name] = artifact
    token = e["contracts"]["MockUSDC"]["address"].lower()
    core = e["contracts"]["ERC1967Proxy"]["address"].lower()
    _require(token != core and all(re.fullmatch(r"0x[0-9a-f]{40}", a) for a in (token, core)),
             "native contract addresses differ")
    _require(e["asset"] == {"name": "MockUSDC", "decimals": 6,
                            "supply_minor_units": 120_500_000, "real_value": 0},
             "valueless local asset differs")
    topics = _topics(artifacts)

    action, early, final = e["claim_action"], e["early_decision"], e["final_verdict"]
    _require(action in {"CLAIM", "WAIT"} and early in {"APPROVE", "REJECT", "DEFER", "NONE", None}
             and final in {"ACCEPT", "REJECT", None}, "native action enum differs")
    _require((action == "WAIT" and early in {"NONE", None}) or
             (action == "CLAIM" and early in {"APPROVE", "REJECT", "DEFER", None}),
             "early decision differs from claim action")
    _require(not (action == "CLAIM" and early is None and final is not None),
             "pending claim has no early decision before final verdict")
    checked = e["check_receipt"] is not None
    expected = ["deploy.mock_usdc", "deploy.implementation", "deploy.proxy",
                "setup.allow_token", "setup.evaluator_fee", "setup.platform_fee",
                "setup.mint", "setup.approve", "terms.platform_zero"]
    if row.fee_term == CLIENT_PREPAID:
        expected.append("terms.evaluator_zero")
    expected.append("endowment.mint")
    if row.fee_term == CLIENT_PREPAID:
        expected.append("terms.client_prepay")
    expected += ["job.create", "job.set_budget", "job.fund"]
    if action == "CLAIM":
        expected.append("claim.submit")
    if checked:
        expected.append("check.early_debit")
    if early in {"APPROVE", "REJECT"}:
        expected.append("claim.approve" if early == "APPROVE" else "claim.reject")
    if final is not None:
        expected += ["job.submit", "job.complete" if final == "ACCEPT" else "job.reject"]
    txs = e["transactions"]
    _require([tx["step"] for tx in txs] == expected
             and len({tx["transaction_hash"].lower() for tx in txs}) == len(txs),
             "native transaction sequence differs")
    by_step = {tx["step"]: tx for tx in txs}
    event_by_step: dict[str, dict[str, list[dict]]] = {}
    ledger: defaultdict[str, int] = defaultdict(int)
    checkpoints: dict[str, dict[str, int]] = {}
    supply = 0
    actor_by_step = {"deploy.mock_usdc": "admin", "deploy.implementation": "admin",
                     "deploy.proxy": "admin", "setup.allow_token": "admin",
                     "setup.evaluator_fee": "admin", "setup.platform_fee": "admin",
                     "setup.mint": "admin", "setup.approve": "client",
                     "terms.platform_zero": "admin", "terms.evaluator_zero": "admin",
                     "endowment.mint": "admin", "terms.client_prepay": "client",
                     "job.create": "client", "job.set_budget": "provider",
                     "job.fund": "client", "claim.submit": "provider",
                     "check.early_debit": "evaluator", "claim.approve": "evaluator",
                     "claim.reject": "evaluator", "job.submit": "provider",
                     "job.complete": "evaluator", "job.reject": "evaluator"}
    token_steps = {"setup.mint", "setup.approve", "endowment.mint",
                   "terms.client_prepay", "check.early_debit"}
    for tx in txs:
        step, raw, receipt = tx["step"], tx["raw_transaction"], tx["raw_receipt"]
        destination = None if step.startswith("deploy.") else token if step in token_steps else core
        _require(tx["status"] == tx["expected_status"] == int(receipt["status"], 16) == 1
                 and tx["actor_role"] == actor_by_step[step]
                 and raw["from"].lower() == roles[actor_by_step[step]]
                 and (raw["to"] or "").lower() == (destination or "")
                 and raw["hash"].lower() == receipt["transactionHash"].lower() == tx["transaction_hash"].lower()
                 and raw["blockNumber"] == receipt["blockNumber"]
                 and raw["blockHash"].lower() == receipt["blockHash"].lower()
                 and raw["transactionIndex"] == receipt["transactionIndex"]
                 and tx["block_number"] == int(receipt["blockNumber"], 16)
                 and tx["gas_used"] == int(receipt["gasUsed"], 16)
                 and (tx["contract_address"] or "").lower() ==
                 (receipt["contractAddress"] or "").lower()
                 and len(tx["logs"]) == len(receipt["logs"]),
                 f"{step}: raw transaction/receipt differs")
        seen: dict[str, list[dict]] = defaultdict(list)
        for saved, log in zip(tx["logs"], receipt["logs"], strict=True):
            _require(saved["topics"] == log["topics"] and saved["data"] == log["data"]
                     and saved["address"].lower() == log["address"].lower()
                     and saved["log_index"] == int(log["logIndex"], 16)
                     and log["transactionHash"].lower() == tx["transaction_hash"].lower()
                     and log["blockHash"].lower() == receipt["blockHash"].lower(),
                     f"{step}: raw event differs")
            topic = log["topics"][0].lower() if log["topics"] else None
            _require(topic in topics and saved["name"] == topics[topic][0],
                     f"{step}: ABI event signature differs")
            name, spec = topics[topic]
            if name in {"Transfer", "Approval"}:
                _require(log["address"].lower() == token, "foreign token Transfer")
            else:
                emitter = (e["contracts"]["ERC8183"]["address"].lower()
                           if step == "deploy.implementation" else core)
                _require(log["address"].lower() == emitter, "event emitter differs")
            values = _decode_event(log, spec)
            seen[name].append(values)
            if name == "Transfer":
                sender, recipient, amount = values["from"], values["to"], values["value"]
                _require(amount >= 0, "negative ERC-20 Transfer")
                if sender != ZERO:
                    ledger[sender] -= amount
                else:
                    supply += amount
                ledger[recipient] += amount
        event_by_step[step] = seen
        checkpoints[step] = dict(ledger)
    _require(supply == e["asset"]["supply_minor_units"], "minted token supply differs")
    allowed_events = {
        "deploy.mock_usdc": set(), "deploy.implementation": {"Initialized"},
        "deploy.proxy": {"Upgraded", "RoleGranted", "Initialized"},
        "setup.allow_token": {"PaymentTokenAllowlistUpdated"},
        "setup.evaluator_fee": {"EvaluatorFeeUpdated"},
        "setup.platform_fee": {"PlatformFeeUpdated"},
        "setup.mint": {"Transfer"}, "setup.approve": {"Approval"},
        "terms.platform_zero": {"PlatformFeeUpdated"},
        "terms.evaluator_zero": {"EvaluatorFeeUpdated"},
        "endowment.mint": {"Transfer"}, "terms.client_prepay": {"Transfer"},
        "job.create": {"JobCreated"}, "job.set_budget": {"BudgetSet"},
        "job.fund": {"Transfer", "JobFunded"},
        "claim.submit": {"ClaimSubmitted"},
        "check.early_debit": {"Transfer"},
        "claim.approve": {"Transfer", "PaymentReleased", "EvaluatorFeePaid",
                          "Settled", "ClaimApproved"},
        "claim.reject": {"ClaimRejected"},
        "job.submit": {"JobSubmitted", "ClaimRejected"},
        "job.complete": {"Transfer", "PaymentReleased", "EvaluatorFeePaid",
                         "JobCompleted"},
        "job.reject": {"Transfer", "Refunded", "JobRejected"},
    }
    for step, observed in event_by_step.items():
        _require(set(observed) <= allowed_events[step],
                 f"{step}: unexpected native event")

    def at(step: str) -> defaultdict[str, int]:
        return defaultdict(int, checkpoints[step])

    _snapshot(e["opening"], at("endowment.mint"), roles, core, supply, "opening")
    _snapshot(e["after_prepay"], at("terms.client_prepay" if row.fee_term == CLIENT_PREPAID
                                     else "endowment.mint"), roles, core, supply, "after_prepay")
    _snapshot(e["funded"], at("job.fund"), roles, core, supply, "funded")
    _snapshot(e["after_claim_submit"], at("claim.submit" if action == "CLAIM" else "job.fund"),
              roles, core, supply, "after_claim_submit")
    if checked:
        _snapshot(e["after_early_check"], at("check.early_debit"),
                  roles, core, supply, "after_early_check")
    else:
        _require(e["after_early_check"] is None, "unbought check has balance snapshot")
    after_early_step = ("claim.approve" if early == "APPROVE" else
                        "claim.reject" if early == "REJECT" else
                        "check.early_debit" if checked else
                        "claim.submit" if action == "CLAIM" else "job.fund")
    if early in {"APPROVE", "REJECT", "DEFER"}:
        _snapshot(e["after_early_decision"], at(after_early_step), roles, core, supply,
                  "after_early_decision")
    else:
        _require(e["after_early_decision"] is None, "no early decision has balance snapshot")
    if final is not None:
        _snapshot(e["after_full_submit"], at("job.submit"), roles, core, supply,
                  "after_full_submit")
    else:
        _require(e["after_full_submit"] is None, "unsubmitted job has full-submission snapshot")
    if final is not None:
        _snapshot(e["final"], at("job.complete" if final == "ACCEPT" else "job.reject"),
                  roles, core, supply, "final")
    else:
        _require(e["final"] is None, "unsettled record claims final balance")

    fixture, artifact = invoice_case(row.truth)
    report_digest = digest({"task_prompt": fixture.public_task()["task_prompt"],
                            "submitted_amount_cents": artifact.submitted_amount_cents})
    buyer = protected_buyer_records(row.truth).checked_result()
    _require(e["invoice"]["public_report_digest"] == report_digest
             and e["invoice"]["submitted_cents"] == 350
             and e["invoice"]["oracle_status"] == ("PASS" if row.truth == "good" else "FAIL")
             and type(e["invoice"]["buyer_revealed"]) is bool
             and (final is None or e["invoice"]["buyer_revealed"])
             and e["invoice"]["buyer_records"] ==
                 (buyer if checked or e["invoice"]["buyer_revealed"] else None),
             "independent invoice/report oracle differs")
    _dynamic_description(by_step["job.create"], roles, row, report_digest)
    _require(by_step["deploy.mock_usdc"]["contract_address"].lower() == token
             and by_step["deploy.implementation"]["contract_address"].lower() ==
             e["contracts"]["ERC8183"]["address"].lower()
             and by_step["deploy.proxy"]["contract_address"].lower() == core,
             "deployed contract address differs")
    _calldata(by_step["setup.allow_token"], "setPaymentTokenAllowed(address,bool)",
              [token, 1])
    _calldata(by_step["setup.evaluator_fee"], "setEvaluatorFee(uint256)", [1000])
    _calldata(by_step["setup.platform_fee"], "setPlatformFee(uint256,address)",
              [500, roles["treasury"]])
    _calldata(by_step["terms.platform_zero"], "setPlatformFee(uint256,address)",
              [0, roles["treasury"]])
    _calldata(by_step["setup.mint"], "mint(address,uint256)",
              [roles["client"], 120_000_000])
    _calldata(by_step["setup.approve"], "approve(address,uint256)",
              [core, 120_000_000])
    _require(_one(event_by_step, "setup.allow_token", "PaymentTokenAllowlistUpdated") ==
             {"token": token, "status": True}
             and _one(event_by_step, "setup.evaluator_fee", "EvaluatorFeeUpdated") ==
             {"feeBP": 1000}
             and _one(event_by_step, "setup.platform_fee", "PlatformFeeUpdated") ==
             {"feeBP": 500, "treasury": roles["treasury"]}
             and _one(event_by_step, "terms.platform_zero", "PlatformFeeUpdated") ==
             {"feeBP": 0, "treasury": roles["treasury"]}
             and _one(event_by_step, "setup.approve", "Approval") ==
             {"owner": roles["client"], "spender": core, "value": 120_000_000},
             "native setup event values differ")
    if row.fee_term == CLIENT_PREPAID:
        _calldata(by_step["terms.evaluator_zero"], "setEvaluatorFee(uint256)", [0])
        _require(_one(event_by_step, "terms.evaluator_zero", "EvaluatorFeeUpdated") ==
                 {"feeBP": 0}, "zero evaluator fee event differs")
    _calldata(by_step["job.set_budget"], "setBudget(uint256,address,uint256,bytes)",
              [e["job_id"], token, term["job_budget_minor"]], b"")
    _calldata(by_step["job.fund"], "fund(uint256,address,uint256,bytes)",
              [e["job_id"], token, term["job_budget_minor"]], b"")
    _calldata(by_step["endowment.mint"], "mint(address,uint256)",
              [roles["evaluator"], term["auditor_endowment_minor"]])
    if row.fee_term == CLIENT_PREPAID:
        _calldata(by_step["terms.client_prepay"], "transfer(address,uint256)",
                  [roles["evaluator"], term["client_prepay_minor"]])
    if checked:
        _calldata(by_step["check.early_debit"], "transfer(address,uint256)",
                  [roles["outsider"], term["check_price_minor"]])
        check = e["check_receipt"]
        _require(isinstance(check.get("request_id"), str)
                 and 0 < len(check["request_id"]) <= 80
                 and check == {"status": "CHECK_PAID", "request_id": check["request_id"],
                               "obligation_id": row.obligation_id, "payer_role": "auditor",
                               "payee_role": "independent_check_service",
                               "amount_minor": term["check_price_minor"],
                               "transaction_hash": by_step["check.early_debit"]["transaction_hash"],
                               "buyer_records": protected_buyer_records(row.truth).checked_result(),
                               "oracle_status": "PASS" if row.truth == "good" else "FAIL"},
                 "early check receipt differs")
    else:
        _require(e["check_receipt"] is None, "unchecked record has check callback")

    budget, cumulative = term["job_budget_minor"], term["claim_cumulative_minor"]
    _require(event_by_step["setup.mint"].get("Transfer") ==
             [{"from": ZERO, "to": roles["client"], "value": 120_000_000}]
             and event_by_step["endowment.mint"].get("Transfer") ==
             [{"from": ZERO, "to": roles["evaluator"],
               "value": term["auditor_endowment_minor"]}]
             and event_by_step["job.fund"].get("Transfer") ==
             [{"from": roles["client"], "to": core, "value": budget}]
             and _one(event_by_step, "job.fund", "JobFunded") ==
             {"jobId": e["job_id"], "client": roles["client"], "amount": budget},
             "funding mint/endowment/job transfer differs")
    if row.fee_term == CLIENT_PREPAID:
        _require(event_by_step["terms.client_prepay"].get("Transfer") ==
                 [{"from": roles["client"], "to": roles["evaluator"],
                   "value": term["client_prepay_minor"]}],
                 "client prepay transfer differs")
    if checked:
        _require(event_by_step["check.early_debit"].get("Transfer") ==
                 [{"from": roles["evaluator"], "to": roles["outsider"],
                   "value": term["check_price_minor"]}],
                 "independent check debit differs")
    _require(_one(event_by_step, "job.set_budget", "BudgetSet") ==
             {"jobId": e["job_id"], "token": token, "amount": budget},
             "native budget event differs")
    created = _one(event_by_step, "job.create", "JobCreated")
    _require(created["jobId"] == e["job_id"]
             and created["client"] == roles["client"]
             and created["provider"] == roles["provider"]
             and created["evaluator"] == roles["evaluator"]
             and created["hook"] == ZERO
             and created["expiredAt"] == e["funded_job"]["expired_at"],
             "native job creation event differs")
    _require(type(e["job_id"]) is int and e["job_id"] > 0, "invalid native job ID")
    _job(e["funded_job"], roles, token, budget, "Funded", 0, "funded_job")
    binding = e["claim_binding"]
    proof_hash = digest({"milestone_id": MILESTONE, "public_claim_cents": 350,
                         "report_digest": report_digest})
    public_binding = {"buyer": roles["client"], "job_id": e["job_id"],
                      "obligation_id": row.obligation_id, "report_digest": report_digest,
                      "milestone_id": MILESTONE, "cumulative_amount_minor": cumulative,
                      "proof_hash": proof_hash}
    opt = canonical(public_binding)
    claim_hash = _cast("keccak", "0x" + (_word(cumulative) +
                            bytes.fromhex(report_digest) +
                            bytes.fromhex(_cast("keccak", "0x" + opt.hex())[2:])).hex())
    if action == "CLAIM":
        _require({key: binding[key] for key in public_binding} == public_binding
                 and binding["opt_params_hex"].lower() == "0x" + opt.hex()
                 and binding["pending_claim_hash"].lower() == claim_hash,
                 "claim obligation/proof/hash binding differs")
    else:
        _require(binding is None, "WAIT row has claim binding")
    if action == "CLAIM":
        _calldata(by_step["claim.submit"], "submitClaim(uint256,uint256,bytes32,bytes)",
                  [e["job_id"], cumulative, "0x" + report_digest], opt)
        submitted = _one(event_by_step, "claim.submit", "ClaimSubmitted")
        _require(submitted == {"jobId": e["job_id"], "provider": roles["provider"],
                               "cumulativeAmount": cumulative, "delta": cumulative,
                               "deliverable": "0x" + report_digest,
                               "optParams": "0x" + opt.hex()},
                 "submitted claim event differs")
        _require(e["claim_receipt"]["status"] == "CLAIM_PENDING"
                 and e["claim_receipt"]["job_id"] == e["job_id"]
                 and e["claim_receipt"]["obligation_id"] == row.obligation_id
                 and e["claim_receipt"]["transaction_hash"].lower() ==
                 by_step["claim.submit"]["transaction_hash"].lower()
                 and e["claim_receipt"]["pending_claim_hash"].lower() == claim_hash
                 and e["claim_receipt"]["cumulative_amount_minor"] == cumulative
                 and e["claim_receipt"]["report_digest"] == report_digest
                 and e["claim_receipt"]["opt_params_hex"].lower() == "0x" + opt.hex(),
                 "claim callback differs from native submission")
    else:
        _require(e["claim_receipt"] is None, "WAIT row has a claim receipt")
    settled = cumulative if early == "APPROVE" else 0
    if early in {"APPROVE", "REJECT", "DEFER"}:
        _job(e["after_early_job"], roles, token, budget, "Funded", settled, "after_early_job")
    else:
        _require(e["after_early_job"] is None, "no early decision has job read")

    first_provider = term["provider_interim_payout_minor"] if early == "APPROVE" else 0
    first_evaluator = term["evaluator_interim_native_fee_minor"] if early == "APPROVE" else 0
    if early == "APPROVE":
        _calldata(by_step["claim.approve"], "approveClaim(uint256,uint256,bytes32,bytes)",
                  [e["job_id"], cumulative, "0x" + report_digest], opt)
        _require(_one(event_by_step, "claim.approve", "Settled") ==
                 {"jobId": e["job_id"], "cumulativeAmount": cumulative,
                  "delta": cumulative}, "approved cumulative claim differs")
        _require(_one(event_by_step, "claim.approve", "ClaimApproved") ==
                 {"jobId": e["job_id"], "approver": roles["evaluator"],
                  "cumulativeAmount": cumulative, "delta": cumulative,
                  "deliverable": "0x" + report_digest},
                 "claim approval identity/digest differs")
    elif early == "REJECT":
        reason = "0x" + digest({"episode_id": row.episode_id,
                                "decision": "REJECT", "phase": "early"})
        _calldata(by_step["claim.reject"],
                  "rejectClaim(uint256,uint256,bytes32,bytes32,bytes)",
                  [e["job_id"], cumulative, "0x" + report_digest, reason], opt)
        _require(_one(event_by_step, "claim.reject", "ClaimRejected") ==
                 {"jobId": e["job_id"], "rejector": roles["evaluator"],
                  "reason": reason}, "rejected claim event differs")
    for step in ("claim.approve", "job.complete"):
        if step not in by_step:
            continue
        gross = cumulative if step == "claim.approve" else budget - settled
        eval_fee = gross * term["evaluator_fee_bp"] // 10_000
        provider = gross - eval_fee
        _require(_one(event_by_step, step, "PaymentReleased") ==
                 {"jobId": e["job_id"], "recipient": roles["provider"], "amount": provider},
                 f"{step}: provider release differs")
        if eval_fee:
            _require(_one(event_by_step, step, "EvaluatorFeePaid") ==
                     {"jobId": e["job_id"], "evaluator": roles["evaluator"],
                      "amount": eval_fee}, f"{step}: native evaluator fee differs")
        else:
            _one(event_by_step, step, "EvaluatorFeePaid", required=False)
        _one(event_by_step, step, "PlatformFeePaid", required=False)
        transfer = event_by_step[step]["Transfer"]
        _require(len(transfer) == 1 + int(eval_fee > 0)
                 and {tuple(sorted(x.items())) for x in transfer} ==
                 {tuple(sorted(x.items())) for x in
                  ([{"from": core, "to": roles["provider"], "value": provider}] +
                   ([{"from": core, "to": roles["evaluator"], "value": eval_fee}]
                    if eval_fee else []))},
                 f"{step}: ERC-20 payout transfer differs")
    for step in ("claim.submit", "claim.reject", "check.early_debit", "job.submit"):
        if step in event_by_step:
            _require(not event_by_step[step].get("PaymentReleased")
                     and not event_by_step[step].get("EvaluatorFeePaid")
                     and not event_by_step[step].get("Refunded"),
                     f"{step}: premature native payment")
    if early in {"APPROVE", "REJECT", "DEFER"}:
        receipt = e["early_receipt"]
        _require(receipt == {"status": {"APPROVE": "CLAIM_APPROVED",
                                        "REJECT": "CLAIM_REJECTED",
                                        "DEFER": "DEFERRED"}[early],
                             "obligation_id": row.obligation_id, "job_id": e["job_id"],
                             "decision": early,
                             "transaction_hash": by_step["claim.approve" if early == "APPROVE"
                                                        else "claim.reject"]["transaction_hash"]
                             if early != "DEFER" else None,
                             "provider_paid_minor": first_provider,
                             "evaluator_native_fee_minor": first_evaluator,
                             "client_refund_minor": 0},
                 "early callback differs from native payment")
    else:
        _require(e["early_receipt"] is None, "no-claim row has early callback")

    if final is None:
        _require(e["final_receipt"] is None and e["final_job"] is None
                 and e["native_final_claim"] is False,
                 "unsettled row falsely claims terminal state")
        return {"status": "PARTIAL_NATIVE_VERIFIED", "episode_id": row.episode_id,
                "model_behavior_tier": e["model_behavior_tier"],
                "first_provider_paid_minor": first_provider,
                "first_evaluator_fee_minor": first_evaluator,
                "escrow_remaining_minor": budget - settled,
                "terminal_verdict": None}
    _calldata(by_step["job.submit"], "submit(uint256,bytes32,bytes)",
              [e["job_id"], "0x" + report_digest], b"")
    submitted = _one(event_by_step, "job.submit", "JobSubmitted")
    _require(submitted["jobId"] == e["job_id"] and
             submitted["provider"] == roles["provider"] and
             submitted["deliverable"] == "0x" + report_digest,
             "final submitted digest differs")
    if early == "DEFER":
        _require(_one(event_by_step, "job.submit", "ClaimRejected") ==
                 {"jobId": e["job_id"], "rejector": roles["provider"],
                  "reason": "0x" + b"superseded-by-submit".ljust(32, b"\0").hex()},
                 "final submit did not supersede pending claim")
    else:
        _one(event_by_step, "job.submit", "ClaimRejected", required=False)
    step = "job.complete" if final == "ACCEPT" else "job.reject"
    reason = "0x" + digest({"episode_id": row.episode_id,
                            "verdict": final, "phase": "final"})
    _calldata(by_step[step], ("complete" if final == "ACCEPT" else "reject") +
              "(uint256,bytes32,bytes)", [e["job_id"], reason], b"")
    _require(_one(event_by_step, step,
                  "JobCompleted" if final == "ACCEPT" else "JobRejected") ==
             ({"jobId": e["job_id"], "evaluator": roles["evaluator"], "reason": reason}
              if final == "ACCEPT" else
              {"jobId": e["job_id"], "rejector": roles["evaluator"], "reason": reason}),
             "terminal native verdict event differs")
    _job(e["final_job"], roles, token, budget,
         "Completed" if final == "ACCEPT" else "Rejected", settled,
         "final_job")
    final_provider = (budget - settled) * (10_000 - term["evaluator_fee_bp"]) // 10_000 if final == "ACCEPT" else 0
    final_evaluator = (budget - settled) * term["evaluator_fee_bp"] // 10_000 if final == "ACCEPT" else 0
    refund = budget - settled if final == "REJECT" else 0
    if final == "REJECT":
        _require(_one(event_by_step, step, "Refunded") ==
                 {"jobId": e["job_id"], "client": roles["client"], "amount": refund},
                 "final refund excludes or misstates prior claim")
        _require(event_by_step[step]["Transfer"] ==
                 [{"from": core, "to": roles["client"], "value": refund}]
                 and not event_by_step[step].get("PaymentReleased")
                 and not event_by_step[step].get("EvaluatorFeePaid"),
                 "final reject has unexpected payout")
    _require(e["native_final_claim"] is True
             and e["final_receipt"] == {
                 "status": "COMPLETED" if final == "ACCEPT" else "REJECTED",
                 "obligation_id": row.obligation_id, "job_id": e["job_id"],
                 "requested_verdict": final,
                 "transaction_hash": by_step[step]["transaction_hash"],
                 "provider_paid_minor": final_provider,
                 "evaluator_native_fee_minor": final_evaluator,
                 "client_refund_minor": refund},
             "final callback differs from native settlement")
    opening, closed = e["opening"]["balances_minor_units"], e["final"]["balances_minor_units"]
    _require(closed["escrow"] == 0
             and closed["provider"] - opening["provider"] == first_provider + final_provider
             and closed["evaluator"] - opening["evaluator"] ==
             term["client_prepay_minor"] + first_evaluator + final_evaluator -
             (term["check_price_minor"] if checked else 0)
             and closed["client"] - opening["client"] ==
             -term["client_prepay_minor"] - (budget - refund),
             "cumulative native economics differ")
    return {"status": "COMPLETE_VERIFIED", "episode_id": row.episode_id,
            "model_behavior_tier": e["model_behavior_tier"],
            "first_provider_paid_minor": first_provider,
            "first_evaluator_fee_minor": first_evaluator,
            "final_provider_paid_minor": final_provider,
            "final_evaluator_fee_minor": final_evaluator,
            "client_refund_minor": refund,
            "cumulative_client_outlay_minor": term["client_prepay_minor"] + budget - refund,
            "terminal_verdict": final}


def verify_file(path: Path, row: PartialClaimRow | None = None) -> dict:
    _require(path.is_file() and not path.is_symlink(), "native evidence absent or symlinked")
    return verify_record(json.loads(path.read_text()), row)
