#!/usr/bin/env python3
"""Independently replay fixed ERC-8183 receiver controls from raw local receipts."""

from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT.parent / "upstreams/erc8183"
CAST = ROOT.parent / ".tools/foundry/v1.8.5/cast"
PIN = "142e669c1fd318486a4628395b629f033654dd06"
SUBMODULE_PINS = {
    "lib/forge-std": "620536fa5277db4e3fd46772d5cbc1ea0696fb43",
    "lib/openzeppelin-contracts": "5fd1781b1454fd1ef8e722282f86f9293cacf256",
    "lib/openzeppelin-contracts-upgradeable": "7bf4727aacdbfaa0f36cbd664654d0c9e1dc52bf",
}
ZERO = "0x" + "00" * 20
BUDGET = 20_000_000
FEE = 2_000_000
NET = 18_000_000
SUPPLY = 120_000_000
CASES = ("direct-approve", "evaluator-receiver-approve", "evaluator-receiver-reject")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _cast(*args: str) -> str:
    return subprocess.run([str(CAST), *args], check=True, capture_output=True,
                          text=True, timeout=10).stdout.strip().lower()


def _calldata(tx: dict, signature: str, args: list[int | str]) -> None:
    data = tx["raw_transaction"]["input"].lower()
    require(data.startswith(_cast("sig", signature)) and len(data) >= 10 + 64 * len(args),
            f"{tx['step']}: selector or calldata length differs")
    for i, expected in enumerate(args):
        got = int(data[10 + 64 * i:10 + 64 * (i + 1)], 16)
        want = int(expected, 16) if isinstance(expected, str) and expected.startswith("0x") else int(expected)
        require(got == want, f"{tx['step']}: calldata argument {i} differs")


def _events(tx: dict, name: str, address: str) -> list[dict]:
    return [log for log in tx["raw_receipt"]["logs"]
            if log.get("_checked_name") == name and log["address"].lower() == address]


def _indexed_event(tx: dict, name: str, core: str, job_id: int, receiver: str, amount: int | None) -> None:
    logs = _events(tx, name, core)
    require(len(logs) == 1, f"{tx['step']}: expected one {name}")
    log = logs[0]
    require(len(log["topics"]) == 3 and int(log["topics"][1], 16) == job_id
            and ("0x" + log["topics"][2][-40:]).lower() == receiver.lower(),
            f"{tx['step']}: {name} job or recipient differs")
    if amount is not None:
        require(int(log["data"], 16) == amount, f"{tx['step']}: {name} amount differs")


def _transfers(tx: dict, token: str) -> list[tuple[str, str, int]]:
    result = []
    for log in _events(tx, "Transfer", token):
        require(len(log["topics"]) == 3, "malformed ERC-20 Transfer")
        result.append((("0x" + log["topics"][1][-40:]).lower(),
                       ("0x" + log["topics"][2][-40:]).lower(), int(log["data"], 16)))
    return result


def verify_record(e: dict[str, Any]) -> dict[str, Any]:
    require(e.get("schema") == "erc8183-receiver-conflict-native-v1"
            and e.get("model_behavior_tier") == "SCRIPTED_SIMULATION"
            and e.get("payment_tier") == "NATIVE_LOCAL_PROTOCOL", "evidence tier/schema differs")
    name = e.get("case")
    require(name in CASES, "unknown fixed case")
    conflict, approved = name.startswith("evaluator-receiver-"), name.endswith("approve")
    source = e["source"]
    require(source["repository"] == "https://github.com/erc-8183/base-contracts"
            and source["commit"] == PIN and source["submodules"] == SUBMODULE_PINS,
            "official upstream provenance differs")
    require(subprocess.run(["git", "rev-parse", "HEAD"], cwd=UPSTREAM, check=True,
                           capture_output=True, text=True, timeout=10).stdout.strip() == PIN,
            "local official upstream pin differs")
    for submodule, pin in SUBMODULE_PINS.items():
        require(subprocess.run(["git", "rev-parse", "HEAD"], cwd=UPSTREAM / submodule,
                               check=True, capture_output=True, text=True, timeout=10).stdout.strip() == pin,
                f"official upstream submodule {submodule} differs")
    require(source["runner_sha256"] == sha256((ROOT / "scripts/run_erc8183_receiver_control.py").read_bytes()).hexdigest(),
            "runner source changed after evidence")
    require(e["chain"]["host"] == "127.0.0.1" and e["chain"]["chain_id"] == 31337
            and e["chain"]["genesis_timestamp"] == 1_760_000_000,
            "chain provenance differs")
    require(e["asset"] == {"name": "MockUSDC", "decimals": 6,
                           "supply_minor_units": SUPPLY, "real_value": 0}, "asset differs")
    roles = {role: address.lower() for role, address in e["actors"].items()}
    require(set(roles) == {"admin", "client", "provider", "evaluator", "treasury", "outsider"}
            and len(set(roles.values())) == 6, "role identities overlap")
    receiver = roles["evaluator"] if conflict else ZERO
    require(e["terms"] == {"budget_minor": BUDGET, "evaluator_fee_bp": 1000,
                           "platform_fee_bp": 0, "payout_receiver": receiver},
            "fee or receiver terms differ")
    require(e["onchain_receiver"].lower() == receiver, "on-chain receiver read differs")
    artifacts: dict[str, dict] = {}
    topics: dict[str, str] = {}
    for artifact_name in ("MockUSDC", "ERC8183", "ERC1967Proxy"):
        saved = e["contracts"][artifact_name]
        artifact_path = UPSTREAM / "out" / f"{artifact_name}.sol" / f"{artifact_name}.json"
        require(artifact_path.is_file() and sha256(artifact_path.read_bytes()).hexdigest() == saved["artifact_sha256"],
                f"{artifact_name}: compiled artifact differs")
        artifact = json.loads(artifact_path.read_text())
        abi_hash = sha256(json.dumps(artifact["abi"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        require(abi_hash == saved["abi_sha256"], f"{artifact_name}: ABI differs")
        artifacts[artifact_name] = artifact
        for entry in artifact["abi"]:
            if entry["type"] == "event" and not entry.get("anonymous", False):
                signature = entry["name"] + "(" + ",".join(item["type"] for item in entry["inputs"]) + ")"
                topics[_cast("keccak", signature)] = entry["name"]
    token = e["contracts"]["MockUSDC"]["address"].lower()
    core = e["contracts"]["ERC1967Proxy"]["address"].lower()
    job_id = e["job_id"]
    require(type(job_id) is int and job_id == 1, "unexpected job identifier")
    steps = ["deploy.mock_usdc", "deploy.implementation", "deploy.proxy",
             "setup.allow_token", "setup.evaluator_fee", "setup.platform_fee",
             "setup.mint", "setup.approve", "terms.platform_zero", "guard.same_nominal_role",
             "job.create", "guard.evaluator_cannot_assign"]
    if conflict:
        steps.append("job.assign_evaluator_receiver")
    steps += ["job.budget", "job.fund", "guard.receiver_locked", "job.submit",
              "job.complete" if approved else "job.reject"]
    txs = e["transactions"]
    require([tx["step"] for tx in txs] == steps, "native transaction sequence differs")
    by_step = {tx["step"]: tx for tx in txs}
    actors_by_step = {"deploy.mock_usdc": "admin", "deploy.implementation": "admin",
                      "deploy.proxy": "admin", "setup.allow_token": "admin",
                      "setup.evaluator_fee": "admin", "setup.platform_fee": "admin",
                      "setup.mint": "admin", "setup.approve": "client",
                      "terms.platform_zero": "admin", "guard.same_nominal_role": "client",
                      "job.create": "client", "guard.evaluator_cannot_assign": "evaluator",
                      "job.assign_evaluator_receiver": "provider", "job.budget": "provider",
                      "job.fund": "client", "guard.receiver_locked": "provider",
                      "job.submit": "provider", "job.complete": "evaluator",
                      "job.reject": "evaluator"}
    ledger: defaultdict[str, int] = defaultdict(int)
    checkpoints: dict[str, dict[str, int]] = {}
    for tx in txs:
        step = tx["step"]
        raw, receipt = tx["raw_transaction"], tx["raw_receipt"]
        expected_to = ("" if step.startswith("deploy.") else
                       token if step in {"setup.mint", "setup.approve"} else core)
        expected_status = 0 if step.startswith("guard.") else 1
        require(tx["actor_role"] == actors_by_step[step]
                and tx["status"] == tx["expected_status"] == expected_status
                and int(receipt["status"], 16) == expected_status
                and tx["transaction_hash"].lower() == raw["hash"].lower() == receipt["transactionHash"].lower()
                and raw["from"].lower() == roles[tx["actor_role"]]
                and (raw["to"] or "").lower() == expected_to
                and tx["block_number"] == int(raw["blockNumber"], 16) == int(receipt["blockNumber"], 16)
                and len(tx["logs"]) == len(receipt["logs"]),
                f"{step}: raw transaction or receipt differs")
        require((expected_status == 1 or not receipt["logs"]), f"{step}: revert retained logs")
        for saved, log in zip(tx["logs"], receipt["logs"], strict=True):
            require(saved["topics"] == log["topics"] and saved["data"] == log["data"]
                    and saved["address"].lower() == log["address"].lower(),
                    f"{step}: saved event differs from raw receipt")
            event_name = topics.get(log["topics"][0].lower()) if log["topics"] else None
            require(saved["name"] == event_name, f"{step}: event signature differs")
            log["_checked_name"] = event_name
        for sender, payee, amount in _transfers(tx, token):
            if sender != ZERO:
                ledger[sender] -= amount
            ledger[payee] += amount
        if step in {"terms.platform_zero", "job.fund", "job.submit", "job.complete", "job.reject"}:
            checkpoints[step] = dict(ledger)
    def replay(step: str) -> dict[str, int]:
        balances = checkpoints[step]
        return {**{role: balances.get(address, 0) for role, address in roles.items()},
                "escrow": balances.get(core, 0)}
    for label, step in (("opening", "terms.platform_zero"), ("funded", "job.fund"),
                        ("submitted", "job.submit"),
                        ("final", "job.complete" if approved else "job.reject")):
        require(e[label]["balances_minor_units"] == replay(step)
                and e[label]["total_supply_minor_units"] == SUPPLY
                and sum(replay(step).values()) == SUPPLY,
                f"{label}: balances disagree with raw token transfers")
    _calldata(by_step["setup.evaluator_fee"], "setEvaluatorFee(uint256)", [1000])
    _calldata(by_step["terms.platform_zero"], "setPlatformFee(uint256,address)", [0, roles["treasury"]])
    _calldata(by_step["guard.same_nominal_role"], "createJob(address,address,uint48,string,address,uint256)",
              [roles["evaluator"], roles["evaluator"]])
    _calldata(by_step["job.create"], "createJob(address,address,uint48,string,address,uint256)",
              [roles["provider"], roles["evaluator"]])
    same_role_input = by_step["guard.same_nominal_role"]["raw_transaction"]["input"].lower()
    valid_input = by_step["job.create"]["raw_transaction"]["input"].lower()
    require(same_role_input[10 + 64 * 2:] == valid_input[10 + 64 * 2:],
            "same-role guard differs from valid job beyond nominal roles")
    require(e["description"].encode().hex() in by_step["job.create"]["raw_transaction"]["input"].lower(),
            "native job description differs")
    _calldata(by_step["guard.evaluator_cannot_assign"], "setPayoutReceiver(uint256,address)",
              [job_id, roles["evaluator"]])
    if conflict:
        _calldata(by_step["job.assign_evaluator_receiver"], "setPayoutReceiver(uint256,address)",
                  [job_id, roles["evaluator"]])
        _indexed_event(by_step["job.assign_evaluator_receiver"], "PayoutReceiverSet", core,
                       job_id, roles["evaluator"], None)
    _calldata(by_step["job.budget"], "setBudget(uint256,address,uint256,bytes)", [job_id, token, BUDGET])
    _calldata(by_step["job.fund"], "fund(uint256,address,uint256,bytes)", [job_id, token, BUDGET])
    require(_transfers(by_step["job.fund"], token) == [(roles["client"], core, BUDGET)],
            "escrow funding transfer differs")
    _calldata(by_step["guard.receiver_locked"], "setPayoutReceiver(uint256,address)",
              [job_id, ZERO if conflict else roles["evaluator"]])
    require(len(_events(by_step["job.submit"], "JobSubmitted", core)) == 1,
            "native provider submission missing")
    pre, terminal = e["preterminal_job"], e["terminal_job"]
    require(pre["status"] == "Submitted" and pre["provider"].lower() == roles["provider"]
            and pre["evaluator"].lower() == roles["evaluator"]
            and pre["client"].lower() == roles["client"]
            and pre["payment_token"].lower() == token
            and pre["budget_minor_units"] == BUDGET and pre["settled_amount_minor_units"] == 0,
            "submitted native job state differs")
    require(terminal["status"] == ("Completed" if approved else "Rejected")
            and terminal["settled_amount_minor_units"] == 0,
            "terminal native job state differs")
    last = by_step["job.complete" if approved else "job.reject"]
    _calldata(last, "complete(uint256,bytes32,bytes)" if approved else "reject(uint256,bytes32,bytes)", [job_id])
    if approved:
        require(_transfers(last, token) == ([(core, roles["evaluator"], FEE),
                                             (core, receiver if conflict else roles["provider"], NET)]),
                "completion fee/net transfer route differs")
        _indexed_event(last, "EvaluatorFeePaid", core, job_id, roles["evaluator"], FEE)
        _indexed_event(last, "PaymentReleased", core, job_id,
                       receiver if conflict else roles["provider"], NET)
        require(not _events(last, "Refunded", core), "completion unexpectedly refunded")
    else:
        require(_transfers(last, token) == [(core, roles["client"], BUDGET)],
                "rejection refund transfer differs")
        _indexed_event(last, "Refunded", core, job_id, roles["client"], BUDGET)
        require(not _events(last, "EvaluatorFeePaid", core)
                and not _events(last, "PaymentReleased", core),
                "rejection unexpectedly paid provider or evaluator")
    delta = {role: e["final"]["balances_minor_units"][role] - e["opening"]["balances_minor_units"][role]
             for role in (*roles, "escrow")}
    expected_delta = {role: 0 for role in (*roles, "escrow")}
    if approved:
        expected_delta["client"] = -BUDGET
        expected_delta["evaluator"] = BUDGET if conflict else FEE
        expected_delta["provider"] = 0 if conflict else NET
    require(delta == expected_delta, "exact actor balances differ")
    return {"case": name, "native_receipts": len(txs), "provider_delta_minor": delta["provider"],
            "evaluator_delta_minor": delta["evaluator"], "client_delta_minor": delta["client"]}


def verify_directory(path: Path) -> dict[str, Any]:
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    require(manifest["schema"] == "erc8183-receiver-control-manifest-v1"
            and manifest["native_local_only"] is True
            and manifest["live_agent_collusion_evidence"] is False
            and [row["case"] for row in manifest["cases"]] == list(CASES),
            "manifest or denominator differs")
    rows = []
    for saved in manifest["cases"]:
        path_case = path / saved["case"]
        raw = (path_case / "evidence.json").read_bytes()
        digest = sha256(raw).hexdigest()
        require(digest == saved["evidence_sha256"] == (path_case / "evidence.sha256").read_text().strip(),
                "evidence digest differs")
        row = verify_record(json.loads(raw))
        require(row["case"] == saved["case"] and row["native_receipts"] == saved["transactions"]
                and all(row[f"{role}_delta_minor"] == saved[f"{role}_delta_minor"]
                        for role in ("client", "provider", "evaluator")),
                "manifest outcome differs from receipt replay")
        rows.append(row)
    return {"status": "PASS", "cases": rows, "live_agent_collusion_evidence": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify_directory(args.input), sort_keys=True))


if __name__ == "__main__":
    main()
