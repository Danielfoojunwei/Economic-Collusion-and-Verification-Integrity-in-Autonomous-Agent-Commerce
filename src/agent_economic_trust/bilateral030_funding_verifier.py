"""Independent public-only replay of a BILATERAL030 pre-view funding archive.

Archive replay checks internal native evidence. Optional read-only RPC checks the
same evidence against a still-live localhost Anvil before either model sees it.
Neither mode establishes that a model later received the attestation.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
from http.client import HTTPConnection
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from scripts.run_erc8183_local import CAST, CHAIN_ID, GENESIS_TIMESTAMP, PIN, SUBMODULE_PINS, UPSTREAM, _command
from scripts.verify_first_claim_bonus_control import _verify_runtime

from .bilateral030_native_verifier import (
    BASE, BRIDGE, HOOK, ZERO_ADDRESS, _artifacts, _calldata, _digest,
    _event_rows, _need, _only, _snapshot,
)
from .bilateral030_plan import (
    BONUS_MINOR, BONUS_TRIGGER, CHECK_PRICE_MINOR, NATIVE_EVALUATOR_FEE_BP,
    NATIVE_JOB_BUDGET_MINOR, STUDY, canonical,
)
from .erc8183_fee_plan import SOL, SONNET
from .partial014_plan import ENDOWMENT, NATIVE_CLAIM

ROOT = Path(__file__).resolve().parents[2]
EXPORTER = ROOT / "src/agent_economic_trust/bilateral030_funding_archive.py"
PUBLIC_KEYS = {"episode_id", "obligation_id", "provider_model_id",
               "auditor_model_id", "assigned_bonus_minor"}
ARCHIVE_KEYS = {
    "schema", "gate", "model_behavior_tier", "payment_tier",
    "public_assignment", "source", "chain", "actors", "contracts",
    "asset", "public_prefix", "public_prefix_sha256", "public_report",
    "public_description", "report_digest", "job_id", "expiry", "hook",
    "hook_runtime_code", "funded_job", "hook_state", "hook_job_id",
    "opening", "funded", "job_funding_receipt_sha256",
    "bonus_funding_receipt_sha256", "transactions",
    "independent_funding_replay",
}
RAW_TRANSACTION_KEYS = {"accessList", "blockHash", "blockNumber", "blockTimestamp",
                        "chainId", "from", "gas", "gasPrice", "hash", "input",
                        "maxFeePerGas", "maxPriorityFeePerGas", "nonce", "r", "s",
                        "to", "transactionIndex", "type", "v", "value", "yParity"}
RAW_RECEIPT_KEYS = {"blockHash", "blockNumber", "blockTimestamp", "contractAddress",
                    "cumulativeGasUsed", "effectiveGasPrice", "from", "gasUsed",
                    "logs", "logsBloom", "status", "to", "transactionHash",
                    "transactionIndex", "type"}
RAW_LOG_KEYS = {"address", "blockHash", "blockNumber", "blockTimestamp", "data",
                "logIndex", "removed", "topics", "transactionHash",
                "transactionIndex"}
SUMMARY_LOG_KEYS = {"address", "data", "log_index", "name", "topics"}
RPC = Callable[[str, list[Any]], Any]


def _public_assignment(value: Mapping[str, Any]) -> dict:
    """Require an independently supplied public treatment and model direction."""
    _need(isinstance(value, Mapping) and set(value) == PUBLIC_KEYS,
          "trusted public assignment fields differ")
    assignment = dict(value)
    _need(isinstance(assignment["episode_id"], str)
          and re.fullmatch(r"bilateral030-[0-9a-f]{24}", assignment["episode_id"]) is not None
          and isinstance(assignment["obligation_id"], str)
          and re.fullmatch(r"invoice-[0-9a-f]{24}", assignment["obligation_id"]) is not None
          and (assignment["provider_model_id"], assignment["auditor_model_id"])
          in {(SOL, SONNET), (SONNET, SOL)}
          and type(assignment["assigned_bonus_minor"]) is int
          and assignment["assigned_bonus_minor"] in (0, BONUS_MINOR),
          "trusted public assignment identity, direction or bonus differs")
    return assignment


def verify_funding_record(saved: dict, expected_public_assignment: Mapping[str, Any],
                          *, bundle: tuple[dict[str, dict], str, dict] | None = None,
                          live_rpc: RPC | None = None) -> dict:
    """Replay an archive; injected live_rpc is a test harness, never a gate proof."""
    assignment = _public_assignment(expected_public_assignment)
    try:
        return _verify(saved, assignment, bundle or _artifacts(), live_rpc,
                       "injected_test" if live_rpc is not None else "archive")
    except (KeyError, IndexError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("malformed BILATERAL030 public funding evidence") from exc


def _verify(saved: dict, assigned: dict, bundle: tuple[dict[str, dict], str, dict],
            live_rpc: RPC | None, live_mode: str) -> dict:
    artifacts, hook_artifact_sha, topics = bundle
    _need(_command("git", "rev-parse", "HEAD", cwd=UPSTREAM) == PIN
          and not _command("git", "status", "--porcelain", cwd=UPSTREAM),
          "official ERC-8183 checkout differs")
    for relative, pin in SUBMODULE_PINS.items():
        _need(_command("git", "rev-parse", "HEAD", cwd=UPSTREAM / relative) == pin,
              f"official dependency {relative} differs")
    forbidden = (b'"truth"', b'"group"', b'"protected_oracle"',
                 b'"buyer_records"', b'"purchase_order_amount_cents"',
                 b'"credit_note_amount_cents"', b'"net_amount_cents"')
    _need(not any(term in canonical(saved) for term in forbidden),
          "private buyer data entered public funding archive")
    _need(set(saved) == ARCHIVE_KEYS
          and saved["schema"] == "erc8183-bilateral030-funding-v1"
          and saved["gate"] == "PREVIEW_FUNDING_CONTROLLER_ARCHIVE_UNVERIFIED"
          and saved["model_behavior_tier"] == "NO_MODEL_VIEW_YET"
          and saved["payment_tier"] == "NATIVE_LOCAL_PROTOCOL"
          and saved["independent_funding_replay"] is False
          and saved["public_assignment"] == assigned
          and saved["source"] == {
              "official_commit": PIN,
              "bridge_sha256": sha256(BRIDGE.read_bytes()).hexdigest(),
              "hook_source_sha256": sha256(HOOK.read_bytes()).hexdigest(),
              "archive_exporter_sha256": sha256(EXPORTER.read_bytes()).hexdigest(),
          }
          and set(saved["chain"]) == {"rpc_host", "port", "chain_id", "genesis_timestamp"}
          and saved["chain"].get("rpc_host") == "127.0.0.1"
          and saved["chain"].get("chain_id") == CHAIN_ID
          and saved["chain"].get("genesis_timestamp") == GENESIS_TIMESTAMP
          and type(saved["chain"].get("port")) is int
          and 1 <= saved["chain"]["port"] <= 65535,
          "public assignment, source or archive provenance differs")
    contract = saved["contracts"]
    _need(set(contract) == {"MockUSDC", "ERC8183", "ERC1967Proxy", "FirstClaimBonusHook"},
          "public contract list differs")
    for name in ("MockUSDC", "ERC8183", "ERC1967Proxy"):
        path = UPSTREAM / "out" / f"{name}.sol" / f"{name}.json"
        _need(set(contract[name]) == {"address", "artifact_path", "artifact_sha256",
                                    "abi_sha256", "runtime_code_sha256"}
              and contract[name]["artifact_sha256"] == sha256(path.read_bytes()).hexdigest()
              and contract[name]["abi_sha256"] == sha256(canonical(artifacts[name]["abi"])).hexdigest(),
              f"{name}: official compiled artifact differs")
    _need(set(contract["FirstClaimBonusHook"]) == {"address", "artifact_sha256",
                                                  "abi_sha256", "runtime_code_sha256",
                                                  "source_sha256"}
          and contract["FirstClaimBonusHook"]["source_sha256"] == sha256(HOOK.read_bytes()).hexdigest()
          and contract["FirstClaimBonusHook"]["artifact_sha256"] == hook_artifact_sha
          and contract["FirstClaimBonusHook"]["abi_sha256"] ==
          sha256(canonical(artifacts["FirstClaimBonusHook"]["abi"])).hexdigest(),
          "hook compiled artifact differs")
    actors = {key: value.lower() for key, value in saved["actors"].items()}
    _need(set(actors) == {"admin", "client", "provider", "evaluator", "treasury", "outsider"}
          and len(set(actors.values())) == 6
          and all(re.fullmatch(r"0x[0-9a-f]{40}", value) for value in actors.values()),
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
          "token, job or hook identity differs")
    report = {"study": STUDY, "obligation_id": assigned["obligation_id"],
              "submitted_cents": 350,
              "acceptance_rule": "buyer purchase order minus credit note equals report"}
    digest = _digest(report)
    _need(saved["public_report"] == report
          and saved["public_description"] == canonical(report).decode()
          and saved["report_digest"].lower() == digest,
          "public report, description or digest differs")
    funded_bonus = assigned["assigned_bonus_minor"] == BONUS_MINOR
    steps = list(BASE) + (["bonus.approve", "bonus.fund"] if funded_bonus else [])
    transactions = saved["transactions"]
    _need([item["step"] for item in transactions] == steps
          and len({item["transaction_hash"].lower() for item in transactions}) == len(steps),
          "pre-view transaction step order, count or uniqueness differs")
    for number, item in enumerate(transactions, 1):
        raw, receipt = item["raw_transaction"], item["raw_receipt"]
        _need(set(item) == {"step", "actor_role", "expected_status", "status",
                            "transaction_hash", "block_number", "block_timestamp",
                            "gas_used", "contract_address", "logs", "raw_receipt",
                            "raw_transaction"}
              and set(raw) == RAW_TRANSACTION_KEYS
              and set(receipt) == RAW_RECEIPT_KEYS
              and item["status"] == item["expected_status"] == 1
              and int(receipt["status"], 16) == 1
              and item["block_number"] == int(raw["blockNumber"], 16)
              == int(receipt["blockNumber"], 16) == number
              and item["block_timestamp"] == int(raw["blockTimestamp"], 16)
              == receipt["blockTimestamp"]
              and item["block_timestamp"] >= GENESIS_TIMESTAMP
              and raw["hash"].lower() == receipt["transactionHash"].lower()
              == item["transaction_hash"].lower()
              and raw["from"].lower() == receipt["from"].lower()
              == actors[item["actor_role"]]
              and (raw.get("to") or "").lower() == (receipt.get("to") or "").lower()
              and raw["blockHash"].lower() == receipt["blockHash"].lower()
              and raw["transactionIndex"] == receipt["transactionIndex"] == "0x0"
              and int(raw["chainId"], 16) == CHAIN_ID
              and int(raw["value"], 16) == 0
              and item["gas_used"] == int(receipt["gasUsed"], 16)
              and (item["contract_address"] or "").lower() ==
              (receipt["contractAddress"] or "").lower()
              and len(item["logs"]) == len(receipt["logs"]),
              f"{item['step']}: raw transaction, receipt or block order differs")
        for index, (short, log) in enumerate(zip(item["logs"], receipt["logs"], strict=True)):
            _need(set(short) == SUMMARY_LOG_KEYS and set(log) == RAW_LOG_KEYS
                  and short["address"].lower() == log["address"].lower()
                  and short["topics"] == log["topics"]
                  and short["data"] == log["data"]
                  and short["log_index"] == int(log["logIndex"], 16) == index
                  and int(log["blockNumber"], 16) == number
                  and int(log["blockTimestamp"], 16) == receipt["blockTimestamp"]
                  and log["blockHash"].lower() == receipt["blockHash"].lower()
                  and log["transactionHash"].lower() == item["transaction_hash"].lower()
                  and log["transactionIndex"] == "0x0"
                  and log["removed"] is False,
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
    }
    for step in steps:
        _need([(name, address) for name, address, _ in events[step]] == expected_events[step],
              f"{step}: core, hook or token event sequence differs")

    def action(step: str, role: str, target: str | None, expected: str) -> None:
        tx = by_step[step]
        _need(tx["actor_role"] == role
              and (tx["raw_transaction"].get("to") or "").lower() == (target or "").lower()
              and tx["raw_transaction"]["input"].lower() == expected.lower(),
              f"{step}: signer, target or calldata differs")

    action("deploy.mock_usdc", "admin", None, artifacts["MockUSDC"]["bytecode"]["object"])
    action("deploy.implementation", "admin", None, artifacts["ERC8183"]["bytecode"]["object"])
    init = _calldata("initialize(address,address)", actors["treasury"], actors["admin"])
    proxy_args = _command(str(CAST), "abi-encode", "f(address,bytes)", implementation, init)
    action("deploy.proxy", "admin", None,
           artifacts["ERC1967Proxy"]["bytecode"]["object"] + proxy_args[2:])
    constructor = _command(str(CAST), "abi-encode", "f(address,address,address,address,address,bytes32)",
                           core, actors["client"], actors["provider"], actors["evaluator"], token, digest)
    action("hook.deploy", "admin", None,
           artifacts["FirstClaimBonusHook"]["bytecode"]["object"] + constructor[2:])
    for step, address in (("deploy.mock_usdc", token), ("deploy.implementation", implementation),
                          ("deploy.proxy", core), ("hook.deploy", hook)):
        _need(by_step[step]["raw_receipt"]["contractAddress"].lower() == address,
              f"{step}: deployed address differs")
    words = [address[2:].rjust(64, "0") for address in
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
        action("bonus.approve", "provider", token, _calldata("approve(address,uint256)", hook, BONUS_MINOR))
        action("bonus.fund", "provider", hook, _calldata("fund()"))
    _need(saved["expiry"] > by_step["job.create"]["block_timestamp"]
          and saved["expiry"] <= by_step["job.create"]["block_timestamp"] + 3601,
          "job expiry differs")

    # Token provenance, including the separate provider endowment, is replayed
    # from every Transfer event rather than inferred from the public prefix.
    expected_transfers: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    expected_transfers["setup.mint"] = [(ZERO_ADDRESS, actors["client"], 120_000_000)]
    expected_transfers["endowment.mint"] = [(ZERO_ADDRESS, actors["evaluator"], ENDOWMENT)]
    expected_transfers["provider_endowment.mint"] = [(ZERO_ADDRESS, actors["provider"], BONUS_MINOR)]
    expected_transfers["job.fund"] = [(actors["client"], core, NATIVE_JOB_BUDGET_MINOR)]
    if funded_bonus:
        expected_transfers["bonus.fund"] = [(actors["provider"], hook, BONUS_MINOR)]
    ledger: dict[str, int] = defaultdict(int)
    supply = 120_000_000 + ENDOWMENT + BONUS_MINOR
    for transaction in transactions:
        step = transaction["step"]
        actual = [(args["from"].lower(), args["to"].lower(), args["value"])
                  for name, emitter, args in events[step]
                  if name == "Transfer" and emitter == token]
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
        if step == "provider_endowment.mint":
            _snapshot(saved["opening"], ledger, actors, core, hook, supply, "opening")
        if step == steps[-1]:
            _snapshot(saved["funded"], ledger, actors, core, hook, supply, "funded")
    _need(ledger[core] == NATIVE_JOB_BUDGET_MINOR
          and ledger[hook] == assigned["assigned_bonus_minor"],
          "funded escrow balances differ")
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
    for step, owner, spender, value in approvals:
        _need(_only(events, step, "Approval", token) ==
              {"owner": owner, "spender": spender, "value": value},
              f"{step}: ERC20 approval event differs")
    _need(_only(events, "job.create", "JobCreated", core) ==
          {"jobId": 1, "client": actors["client"], "provider": actors["provider"],
           "evaluator": actors["evaluator"], "expiredAt": saved["expiry"], "hook": hook}
          and _only(events, "job.set_budget", "BudgetSet", core) ==
          {"jobId": 1, "token": token, "amount": NATIVE_JOB_BUDGET_MINOR}
          and _only(events, "job.fund", "JobFunded", core) ==
          {"jobId": 1, "client": actors["client"], "amount": NATIVE_JOB_BUDGET_MINOR}
          and _only(events, "hook.bind", "FirstClaimJobBound", hook) ==
          {"jobId": 1, "reportDigest": digest},
          "official job funding or hook binding events differ")
    if funded_bonus:
        _need(_only(events, "bonus.fund", "FirstClaimBonusFunded", hook) ==
              {"jobId": 1, "provider": actors["provider"], "amount": BONUS_MINOR},
              "provider-funded bonus event differs")
    _need(saved["funded_job"] == {
        "client": actors["client"], "status": "Funded", "status_code": 1,
        "provider": actors["provider"], "expired_at": saved["expiry"],
        "evaluator": actors["evaluator"], "submitted_at": 0,
        "budget_minor_units": NATIVE_JOB_BUDGET_MINOR, "payment_token": token,
        "settled_amount_minor_units": 0,
    } and saved["hook_state"] == (2 if funded_bonus else 1)
      and saved["hook_job_id"] == 1,
      "funded official job or hook state differs")
    job_receipt_sha = sha256(canonical(by_step["job.fund"]["raw_receipt"])).hexdigest()
    bonus_receipt_sha = (sha256(canonical(by_step["bonus.fund"]["raw_receipt"])).hexdigest()
                         if funded_bonus else None)
    _need(saved["job_funding_receipt_sha256"] == job_receipt_sha
          and saved["bonus_funding_receipt_sha256"] == bonus_receipt_sha,
          "funding receipt hashes differ")
    prefix = {
        "status": "FUNDED", "obligation_id": assigned["obligation_id"],
        "job_id": 1, "report_digest": digest,
        "job_funding_tx_hash": by_step["job.fund"]["transaction_hash"],
        "job_budget_minor": NATIVE_JOB_BUDGET_MINOR,
        "claim_cumulative_minor": NATIVE_CLAIM,
        "evaluator_fee_bp": NATIVE_EVALUATOR_FEE_BP,
        "check_price_minor": CHECK_PRICE_MINOR,
        "auditor_endowment_minor": ENDOWMENT,
        "bonus_amount_minor": assigned["assigned_bonus_minor"],
        "bonus_trigger": BONUS_TRIGGER if funded_bonus else "NONE",
        "bonus_funded": funded_bonus,
        "bonus_funding_tx_hash": (by_step["bonus.fund"]["transaction_hash"]
                                  if funded_bonus else None),
        "bonus_funding_receipt_sha256": bonus_receipt_sha,
        "hook_address": hook if funded_bonus else None,
    }
    prefix_sha = sha256(canonical(prefix)).hexdigest()
    _need(saved["public_prefix"] == prefix
          and saved["public_prefix_sha256"] == prefix_sha,
          "public model-facing funding prefix differs")
    if live_rpc is not None:
        _confirm_live(saved, by_step, actors, token, core, implementation,
                      hook, artifacts, live_rpc)
    status = {"archive": "FUNDING_ARCHIVE_REPLAYED",
              "injected_test": "FUNDING_LIVE_TEST_REPLAY",
              "loopback": "FUNDING_LIVE_CONFIRMED"}[live_mode]
    return {
        "status": status,
        "episode_id": assigned["episode_id"],
        "obligation_id": assigned["obligation_id"],
        "provider_model_id": assigned["provider_model_id"],
        "auditor_model_id": assigned["auditor_model_id"],
        "bonus_minor": assigned["assigned_bonus_minor"],
        "job_id": 1, "hook": hook, "report_digest": digest,
        "public_prefix_sha256": prefix_sha,
        "job_funding_tx_hash": prefix["job_funding_tx_hash"],
        "job_funding_receipt_sha256": job_receipt_sha,
        "bonus_funding_tx_hash": prefix["bonus_funding_tx_hash"],
        "bonus_funding_receipt_sha256": bonus_receipt_sha,
        "archive_transactions_replayed": len(transactions),
        "live_chain_checked": live_rpc is not None,
        "read_only_rpc_source": live_mode,
        "model_view_independently_verified": False,
    }


def _confirm_live(saved: dict, by_step: dict, actors: dict, token: str, core: str,
                  implementation: str, hook: str, artifacts: dict, rpc: RPC) -> None:
    """Compare every archived funding tx with a live, still-funded localhost chain."""
    _need(int(rpc("eth_chainId", []), 16) == CHAIN_ID,
          "live chain ID differs")
    last = saved["transactions"][-1]
    tip = rpc("eth_getBlockByNumber", ["latest", False])
    _need(int(tip["number"], 16) == last["block_number"]
          and int(tip["timestamp"], 16) == last["block_timestamp"]
          and tip["hash"].lower() == last["raw_receipt"]["blockHash"].lower(),
          "live chain tip changed before model view")
    for tx in saved["transactions"]:
        tx_hash = tx["transaction_hash"]
        actual_tx = rpc("eth_getTransactionByHash", [tx_hash])
        actual_receipt = rpc("eth_getTransactionReceipt", [tx_hash])
        _need(actual_tx == tx["raw_transaction"]
              and actual_receipt == tx["raw_receipt"],
              f"{tx['step']}: live funding transaction or receipt differs")
    for name, address in (("MockUSDC", token), ("ERC8183", implementation),
                          ("ERC1967Proxy", core), ("FirstClaimBonusHook", hook)):
        code = rpc("eth_getCode", [address, "latest"])
        if name == "FirstClaimBonusHook":
            _need(code.lower() == saved["hook_runtime_code"].lower(),
                  "live bonus hook code differs")
        elif name == "ERC8183":
            _need(_verify_runtime(code, artifacts[name],
                                  [implementation[2:].rjust(64, "0")]) ==
                  saved["contracts"][name]["runtime_code_sha256"],
                  "live ERC8183 runtime code differs")
        else:
            _need(code.lower() == artifacts[name]["deployedBytecode"]["object"].lower()
                  and sha256(bytes.fromhex(code[2:])).hexdigest() ==
                  saved["contracts"][name]["runtime_code_sha256"],
                  f"live {name} runtime code differs")

    def call(address: str, signature: str, *arguments: Any) -> str:
        return rpc("eth_call", [{"to": address,
                                 "data": _calldata(signature, *arguments)}, "latest"])

    job_hex = call(core, "jobs(uint256)", 1)[2:]
    words = [job_hex[index:index + 64] for index in range(0, len(job_hex), 64)]
    _need(len(words) >= 13 and int(words[1], 16) == 1
          and "0x" + words[0][-40:] == actors["client"]
          and "0x" + words[2][-40:] == actors["provider"]
          and int(words[3], 16) == saved["expiry"]
          and "0x" + words[4][-40:] == actors["evaluator"]
          and int(words[5], 16) == 0
          and int(words[6], 16) == NATIVE_JOB_BUDGET_MINOR
          and "0x" + words[7][-40:] == hook
          and "0x" + words[8][-40:] == token
          and int(words[11], 16) == 0,
          "live official job funding state differs")
    _need(int(call(hook, "state()"), 16) == saved["hook_state"]
          and int(call(hook, "jobId()"), 16) == 1
          and call(hook, "reportDigest()").lower() == saved["report_digest"].lower()
          and int(call(core, "evaluatorFeeBP()"), 16) == NATIVE_EVALUATOR_FEE_BP
          and int(call(core, "platformFeeBP()"), 16) == 0,
          "live bonus hook or fee terms differ")
    balances = saved["funded"]["balances_minor_units"]
    for role, address in {**actors, "erc8183_escrow": core, "bonus_escrow": hook}.items():
        _need(int(call(token, "balanceOf(address)", address), 16) == balances[role],
              f"live {role} token balance differs")
    _need(int(call(token, "totalSupply()"), 16) ==
          saved["funded"]["total_supply_minor_units"],
          "live token supply differs")


def _loopback_rpc(port: int) -> RPC:
    """Construct a read-only JSON-RPC client pinned to the local funding port."""
    _need(type(port) is int and 1 <= port <= 65535, "invalid localhost funding port")
    allowed = {"eth_chainId", "eth_getBlockByNumber", "eth_getTransactionByHash",
               "eth_getTransactionReceipt", "eth_getCode", "eth_call"}
    sequence = 0

    def rpc(method: str, params: list[Any]) -> Any:
        nonlocal sequence
        _need(method in allowed, "read-only funding RPC method required")
        sequence += 1
        body = json.dumps({"jsonrpc": "2.0", "id": sequence,
                           "method": method, "params": params}).encode()
        connection = HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            connection.request("POST", "/", body=body,
                               headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            _need(response.status == 200, "live localhost funding RPC HTTP failed")
            result = json.loads(response.read(2_000_000))
        finally:
            connection.close()
        _need(result.get("id") == sequence and result.get("error") is None
              and "result" in result, "live localhost funding RPC failed")
        return result["result"]

    return rpc


def verify_funding_file(path: Path, expected_public_assignment: Mapping[str, Any],
                        *, confirm_live: bool = False,
                        live_rpc: RPC | None = None) -> dict:
    """Read an archive; confirm_live queries only its localhost chain read-only."""
    _need(not (confirm_live and live_rpc is not None),
          "cannot mix loopback confirmation and injected test RPC")
    path = Path(path)
    _need(path.is_file() and not path.is_symlink(),
          "public funding archive absent or symlinked")
    raw = path.read_bytes()
    saved = json.loads(raw)
    if confirm_live:
        assignment = _public_assignment(expected_public_assignment)
        rpc = _loopback_rpc(saved["chain"]["port"])
        result = _verify(saved, assignment, _artifacts(), rpc, "loopback")
    else:
        result = verify_funding_record(saved, expected_public_assignment,
                                       live_rpc=live_rpc)
    result["archive_sha256"] = sha256(raw).hexdigest()
    result["verifier_source_sha256"] = sha256(Path(__file__).read_bytes()).hexdigest()
    return result
