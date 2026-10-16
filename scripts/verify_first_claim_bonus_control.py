#!/usr/bin/env python3
"""Independent read-only replay of scripted ERC-8183 first-claim bonus receipts."""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
for local in (ROOT, ROOT / "scripts"):
    if str(local) not in sys.path:
        sys.path.insert(0, str(local))
from scripts.run_erc8183_local import CAST, FORGE, PIN, SOLC, UPSTREAM, _command  # noqa: E402

SOURCE = ROOT / "protocols/side_escrow/src/FirstClaimBonusHook.sol"
PROJECT = ROOT / "protocols/side_escrow"
NAMES = ("bad_eval_approve", "bad_eval_reject", "bad_client_settle", "bad_client_approve")
BONUS, FIRST, BUDGET = 5_000_000, 10_000_000, 20_000_000


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def _digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _topic(signature: str) -> str:
    return _command(str(CAST), "keccak", signature).lower()


def _one(receipt: dict, emitter: str, signature: str) -> dict:
    topic = _topic(signature)
    found = [log for log in receipt["logs"] if log["address"].lower() == emitter
             and log["topics"] and log["topics"][0].lower() == topic]
    _require(len(found) == 1, f"{signature}: raw event absent or duplicated")
    return found[0]


def _address(word: str) -> str:
    return "0x" + word[-40:].lower()


def _transfer(receipt: dict, token: str, source: str, target: str, amount: int) -> None:
    topic = _topic("Transfer(address,address,uint256)")
    found = [log for log in receipt["logs"] if log["address"].lower() == token
             and len(log["topics"]) == 3 and log["topics"][0].lower() == topic
             and _address(log["topics"][1]) == source
             and _address(log["topics"][2]) == target
             and int(log["data"], 16) == amount]
    _require(len(found) == 1, f"Transfer {source} -> {target} {amount} differs")


def _snapshot(saved: dict, supply: int, label: str) -> dict:
    _require(saved["total_supply_minor_units"] == supply
             and sum(saved["balances_minor_units"].values()) == supply,
             f"{label}: saved local token balance conservation differs")
    return saved["balances_minor_units"]


def _delta(before: dict, after: dict, expected: dict[str, int], supply: int, label: str) -> None:
    old, new = _snapshot(before, supply, label), _snapshot(after, supply, label)
    _require(set(old) == set(new), f"{label}: balance holder set differs")
    for holder, amount in old.items():
        _require(new[holder] - amount == expected.get(holder, 0),
                 f"{label}: {holder} payment delta differs")


def _verify_runtime(code: str, artifact: dict, words: list[str]) -> str:
    actual = bytearray.fromhex(code.removeprefix("0x"))
    template = bytearray.fromhex(artifact["deployedBytecode"]["object"].removeprefix("0x"))
    _require(len(actual) == len(template), "deployed hook runtime length differs")
    refs = artifact["deployedBytecode"]["immutableReferences"]
    observed = []
    for group in refs.values():
        values = set()
        for ref in group:
            start, length = ref["start"], ref["length"]
            _require(length == 32 and 0 <= start <= len(actual) - 32,
                     "invalid hook immutable reference")
            values.add(bytes(actual[start:start + length]).hex())
            template[start:start + length] = actual[start:start + length]
        _require(len(values) == 1, "hook immutable copies disagree")
        observed.extend(values)
    _require(template == actual and Counter(observed) == Counter(words)
             and len(refs) == len(words), "hook runtime or immutable binding differs")
    return sha256(actual).hexdigest()


def _compile_artifact() -> tuple[dict, str]:
    with TemporaryDirectory(prefix="first-claim-verify-", dir="/tmp") as temp:
        out, cache = Path(temp) / "out", Path(temp) / "cache"
        result = subprocess.run([
            str(FORGE), "build", "--offline", "--use", str(SOLC),
            "--out", str(out), "--cache-path", str(cache), "--threads", "4",
        ], cwd=PROJECT, capture_output=True, text=True, timeout=120)
        _require(result.returncode == 0, "offline pinned hook compilation failed")
        path = out / "FirstClaimBonusHook.sol/FirstClaimBonusHook.json"
        return json.loads(path.read_text()), sha256(path.read_bytes()).hexdigest()


def verify(evidence_path: Path, *, artifact: dict | None = None,
           artifact_sha256: str | None = None) -> dict:
    """Replay the saved transcript, payment source and actor for every scenario."""
    evidence_path = Path(evidence_path)
    _require(evidence_path.is_file() and not evidence_path.is_symlink(),
             "native control receipt absent or symlinked")
    e = json.loads(evidence_path.read_text())
    _require(e.get("schema_version") == "first-claim-bonus-local-native-v1"
             and e.get("model_behavior_tier") == "SCRIPTED_SIMULATION"
             and e.get("payment_tier") == "NATIVE_LOCAL_PROTOCOL"
             and e.get("execution_tier") == "NATIVE_LOCAL_PROTOCOL"
             and e.get("gate") == "OFFLINE_NATIVE_CONTROL_ONLY"
             and e.get("chain", {}).get("rpc_host") == "127.0.0.1"
             and e["chain"].get("chain_id") == 31337
             and e.get("asset", {}).get("real_value") == 0
             and e.get("source", {}).get("commit") == PIN,
             "native local/scripted provenance differs")
    _require(_command("git", "rev-parse", "HEAD", cwd=UPSTREAM) == PIN,
             "official ERC-8183 source commit differs")
    _require(e["contracts"]["FirstClaimBonusHook"]["source_sha256"]
             == sha256(SOURCE.read_bytes()).hexdigest(), "hook source digest differs")
    if artifact is None:
        artifact, artifact_sha256 = _compile_artifact()
    _require(artifact_sha256 == e["contracts"]["FirstClaimBonusHook"]["artifact_sha256"]
             and e["contracts"]["FirstClaimBonusHook"]["abi_sha256"] ==
             sha256(json.dumps(artifact["abi"], sort_keys=True,
                               separators=(",", ":")).encode()).hexdigest(),
             "compiled hook artifact or ABI differs")
    for name in ("MockUSDC", "ERC8183", "ERC1967Proxy"):
        path = UPSTREAM / "out" / f"{name}.sol" / f"{name}.json"
        _require(path.is_file() and e["contracts"][name]["artifact_sha256"]
                 == sha256(path.read_bytes()).hexdigest(),
                 f"{name}: pinned compiled artifact differs")
    actors = {role: address.lower() for role, address in e["actors"].items()}
    _require(set(actors) == {"admin", "client", "provider", "evaluator", "treasury", "outsider"}
             and len(set(actors.values())) == 6, "native role binding differs")
    token = e["contracts"]["MockUSDC"]["address"].lower()
    core = e["contracts"]["ERC1967Proxy"]["address"].lower()
    supply = e["asset"]["supply_minor_units"]
    _require(supply == 120_000_000 + len(NAMES) * BONUS,
             "local test token supply differs")
    txs = e["transactions"]
    by_step = {tx["step"]: tx for tx in txs}
    _require(len(txs) == len(by_step) == 10 + 12 + 12 + 11 + 12
             and len({tx["transaction_hash"].lower() for tx in txs}) == len(txs),
             "native transaction count or uniqueness differs")
    for tx in txs:
        raw, receipt = tx["raw_transaction"], tx["raw_receipt"]
        _require(tx["status"] == 1 and int(receipt["status"], 16) == 1
                 and raw["hash"].lower() == receipt["transactionHash"].lower()
                 == tx["transaction_hash"].lower()
                 and raw["from"].lower() == receipt["from"].lower()
                 == actors[tx["actor_role"]]
                 and (raw.get("to") or "").lower() == (receipt.get("to") or "").lower()
                 and int(receipt["blockNumber"], 16) == tx["block_number"]
                 and len(receipt["logs"]) == len(tx["logs"]),
                 f"{tx['step']}: raw native receipt differs")
        for summarized, log in zip(tx["logs"], receipt["logs"], strict=True):
            _require(summarized["address"].lower() == log["address"].lower()
                     and summarized["topics"] == log["topics"]
                     and summarized["data"] == log["data"],
                     f"{tx['step']}: summary log differs")
    _require(e["scenarios"]["metadata"]["paid_model_calls"] == 0
             and e["scenarios"]["metadata"]["scripted_cases"] == list(NAMES),
             "model or case metadata differs")
    case_results = {}
    for name in NAMES:
        s = e["scenarios"][name]
        job, hook = s["job_id"], s["hook"].lower()
        report, oracle = s["public_report"], s["oracle"]
        _require(report == {"obligation_id": "first-claim-" + name,
                            "submitted_cents": 350,
                            "acceptance_rule": "buyer PO minus credit equals submitted report"}
                 and oracle == {"status": "FAIL", "buyer_po_cents": 350,
                                "buyer_credit_cents": 50, "buyer_net_cents": 300}
                 and oracle["buyer_po_cents"] - oracle["buyer_credit_cents"]
                 == oracle["buyer_net_cents"] != report["submitted_cents"]
                 and s["report_digest"] == "0x" + _digest(report),
                 f"{name}: independent BAD invoice oracle differs")
        _require(s["model_behavior_tier"] == "SCRIPTED_SIMULATION"
                 and s["payment_tier"] == "NATIVE_LOCAL_PROTOCOL"
                 and s["bonus_minor"] == BONUS and s["final_job"]["status"] == "Rejected"
                 and s["final_job"]["status_code"] == 4,
                 f"{name}: tier, amount or terminal status differs")
        description = json.dumps(report, sort_keys=True, separators=(",", ":"))
        create = by_step[name + ".create_job"]
        expected_create = _command(
            str(CAST), "calldata", "createJob(address,address,uint48,string,address,uint256)",
            actors["provider"], actors["evaluator"], str(s["final_job"]["expired_at"]),
            description, hook, "0")
        _require(create["raw_transaction"]["input"].lower() == expected_create.lower()
                 and create["raw_transaction"]["from"].lower() == actors["client"]
                 and create["raw_transaction"]["to"].lower() == core,
                 f"{name}: public-only job description or hook binding differs")
        deploy = by_step[name + ".deploy_hook"]
        _require(deploy["raw_receipt"]["contractAddress"].lower() == hook,
                 f"{name}: hook deploy address differs")
        words = [address.removeprefix("0x").rjust(64, "0")
                 for address in (core, token, actors["client"], actors["provider"],
                                 actors["evaluator"])] + [s["report_digest"][2:]]
        _require(_verify_runtime(s["hook_runtime_code"], artifact, words)
                 == s["hook_runtime_code_sha256"], f"{name}: hook runtime differs")
        bound = _one(by_step[name + ".bind_job"]["raw_receipt"], hook,
                     "FirstClaimJobBound(uint256,bytes32)")
        _require(int(bound["topics"][1], 16) == job
                 and bound["topics"][2].lower() == s["report_digest"],
                 f"{name}: funded bonus obligation binding differs")
        funding = by_step[name + ".fund_bonus"]["raw_receipt"]
        _require(by_step[name + ".fund_bonus"]["raw_transaction"]["to"].lower() == hook
                 and by_step[name + ".fund_bonus"]["raw_transaction"]["input"].lower()
                 == _command(str(CAST), "calldata", "fund()").lower(),
                 f"{name}: provider-funded hook call differs")
        funded = _one(funding, hook, "FirstClaimBonusFunded(uint256,address,uint256)")
        _require(int(funded["topics"][1], 16) == job
                 and _address(funded["topics"][2]) == actors["provider"]
                 and int(funded["data"], 16) == BONUS,
                 f"{name}: provider bonus funding event differs")
        _transfer(funding, token, actors["provider"], hook, BONUS)
        first = by_step[name + ".first_decision"]
        final = by_step[name + ".reject_final"]
        _require(first["raw_receipt"]["to"].lower() == core
                 and final["raw_receipt"]["to"].lower() == core
                 and first["transaction_hash"] == s["first_decision_tx_hash"]
                 and final["transaction_hash"] == s["final_rejection_tx_hash"]
                 and by_step[name + ".fund_bonus"]["block_number"] < first["block_number"]
                 < final["block_number"], f"{name}: decision receipts or order differ")
        first_receipt = first["raw_receipt"]
        is_approved = name in {"bad_eval_approve", "bad_client_approve"}
        is_settled = name == "bad_client_settle"
        actor = actors["evaluator"] if name.startswith("bad_eval") else actors["client"]
        _require(first_receipt["from"].lower() == actor
                 and s["first_actor"] == ("evaluator" if name.startswith("bad_eval") else "client"),
                 f"{name}: actual decision actor differs")
        if name == "bad_eval_reject":
            expected_first_input = _command(
                str(CAST), "calldata", "rejectClaim(uint256,uint256,bytes32,bytes32,bytes)",
                str(job), str(FIRST), s["report_digest"],
                "0x" + _digest({"case": name, "phase": "early"}), "0x")
        else:
            signature = ("settleClaim(uint256,uint256,bytes32,bytes)" if is_settled
                         else "approveClaim(uint256,uint256,bytes32,bytes)")
            expected_first_input = _command(str(CAST), "calldata", signature,
                                            str(job), str(FIRST), s["report_digest"], "0x")
        _require(first["raw_transaction"]["input"].lower() == expected_first_input.lower(),
                 f"{name}: first native decision calldata differs")
        if is_approved or is_settled:
            event = _one(first_receipt, core,
                         "ClaimApproved(uint256,address,uint256,uint256,bytes32)" if is_approved
                         else "ClaimSettled(uint256,address,uint256,uint256,bytes32)")
            _require(int(event["topics"][1], 16) == job
                     and _address(event["topics"][2]) == actor
                     and [int(event["data"][2:66], 16), int(event["data"][66:130], 16)]
                     == [FIRST, FIRST]
                     and "0x" + event["data"][130:194].lower() == s["report_digest"],
                     f"{name}: authoritative first-claim event differs")
            _transfer(first_receipt, token, core, actors["provider"], 9_000_000)
            _transfer(first_receipt, token, core, actors["evaluator"], 1_000_000)
        else:
            event = _one(first_receipt, core, "ClaimRejected(uint256,address,bytes32)")
            _require(int(event["topics"][1], 16) == job
                     and _address(event["topics"][2]) == actor,
                     f"{name}: first rejection event differs")
        bonus_recipient = actors["evaluator"] if name == "bad_eval_approve" else actors["provider"]
        bonus_event = _one(first_receipt, hook,
                           "FirstClaimBonusReleased(uint256,address,uint256)" if name == "bad_eval_approve"
                           else "FirstClaimBonusRefunded(uint256,address,uint256)")
        _require(int(bonus_event["topics"][1], 16) == job
                 and _address(bonus_event["topics"][2]) == bonus_recipient
                 and int(bonus_event["data"], 16) == BONUS,
                 f"{name}: bonus payout event differs")
        _transfer(first_receipt, token, hook, bonus_recipient, BONUS)
        expected_first = ({"provider": 9_000_000, "evaluator": 6_000_000,
                           "erc8183_escrow": -FIRST, "bonus_escrow": -BONUS}
                          if name == "bad_eval_approve" else
                          {"provider": BONUS, "bonus_escrow": -BONUS}
                          if name == "bad_eval_reject" else
                          {"provider": 9_000_000 + BONUS, "evaluator": 1_000_000,
                           "erc8183_escrow": -FIRST, "bonus_escrow": -BONUS})
        _delta(s["before_first"], s["after_first"], expected_first, supply, name + ": first")
        refund = BUDGET if name == "bad_eval_reject" else FIRST
        final_receipt = final["raw_receipt"]
        terminal = _one(final_receipt, core, "JobRejected(uint256,address,bytes32)")
        _require(int(terminal["topics"][1], 16) == job
                 and _address(terminal["topics"][2]) == actors["evaluator"]
                 and s["final_job"]["settled_amount_minor_units"] == BUDGET - refund,
                 f"{name}: terminal job state differs")
        _transfer(final_receipt, token, core, actors["client"], refund)
        _delta(s["after_first"], s["after_final"],
               {"client": refund, "erc8183_escrow": -refund}, supply, name + ": final")
        _require(s["bonus_status"] == ("RELEASED_TO_EVALUATOR" if name == "bad_eval_approve"
                                        else "REFUNDED_TO_PROVIDER"),
                 f"{name}: saved bonus status differs")
        case_results[name] = {"job_id": job,
                              "evaluator_bonus_minor": BONUS if name == "bad_eval_approve" else 0,
                              "provider_bonus_refund_minor": 0 if name == "bad_eval_approve" else BONUS,
                              "native_first_provider_minor": 0 if name == "bad_eval_reject" else 9_000_000,
                              "native_first_evaluator_fee_minor": 0 if name == "bad_eval_reject" else 1_000_000,
                              "client_final_refund_minor": refund}
    _require(len({x["job_id"] for x in case_results.values()}) == len(NAMES),
             "scripted cases reuse an official job")
    return {"status": "PASS", "schema": "first-claim-bonus-native-replay-v1",
            "model_behavior_tier": "SCRIPTED_SIMULATION",
            "payment_tier": "NATIVE_LOCAL_PROTOCOL", "paid_model_calls": 0,
            "independent_oracle": "BAD: 350 submitted != 350 PO - 50 credit = 300",
            "native_transactions_replayed": len(txs), "cases": case_results,
            "evidence_sha256": sha256(evidence_path.read_bytes()).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.evidence), sort_keys=True))


if __name__ == "__main__":
    main()
