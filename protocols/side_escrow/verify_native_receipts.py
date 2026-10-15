#!/usr/bin/env python3
"""Read-only cross-check of raw Anvil receipts from run_native_receipts.py."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


BONUS_FUNDED = "0x2b835e265e59ad4709fde33f46571273d118f1618d56886602e7a118f3206fe9"
BONUS_SETTLED = "0x889f55b5ea9f90ee1d66c743f0feb9ff70cf3aee26606ae88a88c2149d901958"
JOB_COMPLETED = "0x0fd54bd364fa9e67f17b091aefe930932c09fe7651cf5ad02c71a418f3341444"
JOB_REJECTED = "0xae7362b1af91f4492868987b9c73990d780060811551b58728fbe96fd1bab275"
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
PIN = "142e669c1fd318486a4628395b629f033654dd06"


def _address(word: str) -> str:
    return "0x" + word.lower()[-40:]


def _event(receipt: dict, emitter: str, topic: str) -> dict:
    matches = [log for log in receipt["logs"] if log["address"].lower() == emitter.lower()
               and log["topics"] and log["topics"][0].lower() == topic]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {topic} from {emitter}")
    return matches[0]


def _transfer(receipt: dict, token: str, source: str, destination: str, amount: int) -> None:
    matches = [log for log in receipt["logs"] if log["address"].lower() == token.lower()
               and log["topics"] and log["topics"][0].lower() == TRANSFER
               and _address(log["topics"][1]) == source.lower()
               and _address(log["topics"][2]) == destination.lower()
               and int(log["data"], 16) == amount]
    if len(matches) != 1:
        raise ValueError("missing exact native token Transfer")


def verify(path: Path) -> dict:
    evidence = json.loads(path.read_text(encoding="utf-8"))
    if (evidence.get("model_behavior_tier") != "SCRIPTED"
            or evidence.get("payment_tier") != "NATIVE_LOCAL_CHAIN"
            or evidence.get("chain", {}).get("chain_id") != 31337
            or evidence.get("chain", {}).get("rpc_host") != "127.0.0.1"
            or evidence.get("source", {}).get("commit") != PIN
            or evidence.get("asset", {}).get("real_value") != 0):
        raise ValueError("wrong local scripted/pinned provenance")
    actors = {role: address.lower() for role, address in evidence["actors"].items()}
    token = evidence["contracts"]["MockUSDC"]["address"].lower()
    core = evidence["contracts"]["ERC1967Proxy"]["address"].lower()
    transactions = {tx["step"]: tx for tx in evidence["transactions"]}
    if len(transactions) != len(evidence["transactions"]):
        raise ValueError("duplicate transaction step")
    hashes = set()
    for tx in evidence["transactions"]:
        receipt = tx["raw_receipt"]
        tx_hash = receipt["transactionHash"].lower()
        if tx_hash in hashes or tx_hash != tx["transaction_hash"].lower():
            raise ValueError("duplicate or mismatched transaction hash")
        hashes.add(tx_hash)
        if int(receipt["status"], 16) != tx["status"]:
            raise ValueError("summary differs from raw receipt status")
        if int(receipt["blockNumber"], 16) != tx["block_number"]:
            raise ValueError("summary differs from raw receipt block")
        if receipt["from"].lower() != actors[tx["actor_role"]]:
            raise ValueError("unexpected transaction sender")
        if len(tx["logs"]) != len(receipt["logs"]):
            raise ValueError("summary omits raw logs")
        for summary, raw in zip(tx["logs"], receipt["logs"]):
            if (summary["address"].lower() != raw["address"].lower()
                    or summary["topics"] != raw["topics"] or summary["data"] != raw["data"]):
                raise ValueError("summary log differs from raw receipt")
        if tx["status"] == 0 and receipt["logs"]:
            raise ValueError("reverted receipt retained logs")

    for scenario, label, terminal_topic, status, recipient_role in (
        ("completed", "good", JOB_COMPLETED, 3, "evaluator"),
        ("rejected", "bad", JOB_REJECTED, 4, "provider"),
    ):
        proof = evidence["scenarios"][scenario]
        job_id = proof["job_id"]
        escrow = proof["side_escrow"].lower()
        amount = proof["bonus_minor_units"]
        recipient = actors[recipient_role]
        if (amount <= 0 or amount > 20_000_000 or proof["status_code"] != status
                or proof["bonus_recipient"] != recipient_role):
            raise ValueError("invalid scenario amount, outcome, or recipient")
        deploy = transactions[f"{label}.deploy_side"]
        fund = transactions[f"{label}.fund_bonus"]
        early = transactions[f"{label}.premature_settle"]
        terminal = transactions[f"{label}.complete" if status == 3 else f"{label}.reject"]
        settle = transactions[f"{label}.settle_bonus"]
        replay = transactions[f"{label}.replay_settle"]
        if deploy["raw_receipt"]["contractAddress"].lower() != escrow:
            raise ValueError("escrow deployment does not match obligation")
        for transaction in (deploy, fund, terminal, settle):
            if transaction["status"] != 1:
                raise ValueError("required transaction failed")
        if early["status"] != 0 or replay["status"] != 0:
            raise ValueError("premature or replay settlement succeeded")
        if not (deploy["block_number"] < fund["block_number"] < early["block_number"]
                < terminal["block_number"] < settle["block_number"] < replay["block_number"]):
            raise ValueError("wrong native transaction order")
        if (fund["raw_receipt"]["to"].lower() != escrow
                or settle["raw_receipt"]["to"].lower() != escrow
                or terminal["raw_receipt"]["to"].lower() != core):
            raise ValueError("receipt sent to wrong contract")
        if fund["raw_receipt"]["from"].lower() != actors["provider"]:
            raise ValueError("bonus funding was not provider funded")
        funding_event = _event(fund["raw_receipt"], escrow, BONUS_FUNDED)
        if (int(funding_event["topics"][1], 16) != job_id
                or _address(funding_event["topics"][2]) != actors["provider"]
                or _address(funding_event["topics"][3]) != actors["evaluator"]
                or _address(funding_event["data"][2:66]) != token
                or int(funding_event["data"][66:130], 16) != amount):
            raise ValueError("bonus funding log binding mismatch")
        _transfer(fund["raw_receipt"], token, actors["provider"], escrow, amount)
        terminal_event = _event(terminal["raw_receipt"], core, terminal_topic)
        if int(terminal_event["topics"][1], 16) != job_id:
            raise ValueError("official terminal event belongs to wrong job")
        settled_event = _event(settle["raw_receipt"], escrow, BONUS_SETTLED)
        if (int(settled_event["topics"][1], 16) != job_id
                or _address(settled_event["topics"][2]) != recipient
                or int(settled_event["data"][2:66], 16) != amount
                or int(settled_event["data"][66:130], 16) != status):
            raise ValueError("bonus settlement log binding mismatch")
        _transfer(settle["raw_receipt"], token, escrow, recipient, amount)
        if (proof["bonus_receipt"].lower() != settle["transaction_hash"].lower()
                or proof["escrow_balance_before"] != amount
                or proof["escrow_balance_after"] != 0
                or proof["recipient_balance_after"] - proof["recipient_balance_before"] != amount):
            raise ValueError("post-settlement balance proof mismatch")

    return {"valid": True, "native_transactions": len(transactions),
            "failed_receipts": sum(tx["status"] == 0 for tx in transactions.values()),
            "scenarios": sorted(evidence["scenarios"]),
            "payment_tier": evidence["payment_tier"], "model_behavior_tier": evidence["model_behavior_tier"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.evidence), sort_keys=True))


if __name__ == "__main__":
    main()
