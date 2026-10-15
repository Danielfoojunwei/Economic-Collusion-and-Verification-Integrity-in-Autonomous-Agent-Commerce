#!/usr/bin/env python3
"""Settle W10 pair audit fees on an isolated local MockUSDC chain.

One fresh client, worker, and auditor address belongs to each frozen pair.
For R0 the client pays the auditor; for R1 the worker pays the auditor. All
fees are fixed, paid before any verdict, and use valueless locally minted
tokens. ERC-20 has no obligation field: the obligation map is application
evidence, not a protocol guarantee. This script makes no model calls.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
sys.path.insert(0, str(ROOT / "src"))

from agent_economic_trust.w10_factorial import (  # noqa: E402
    FEE_MINOR_UNITS, _canonical, _hash, make_assignments,
)
from agent_economic_trust.w10_funding import NativePairFundingVerifier  # noqa: E402
from run_erc8183_local import (  # noqa: E402
    ANVIL, CAST, CHAIN_ID, FORGE, GENESIS_TIMESTAMP, NativeRun, PIN, SOLC,
    UPSTREAM, _command, _free_port, _hex_int, _sha256,
)


def _read_plan(plan_dir: Path):
    seed_hex = (plan_dir / "seed.hex").read_text(encoding="ascii").strip()
    manifest_path = plan_dir / "assignment_manifest.json"
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    rows = make_assignments(seed_hex)
    if manifest.get("assignments_sha256") != _hash([row.as_dict() for row in rows]) \
            or manifest.get("primary_episodes") != 32:
        raise ValueError("frozen assignment manifest differs from seed")
    return rows, sha256(manifest_raw).hexdigest()


def run(plan_dir: Path, output: Path, port: int = 0) -> dict:
    if output.exists():
        raise FileExistsError("native funding output already exists")
    rows, plan_sha = _read_plan(plan_dir)
    for executable in (ANVIL, CAST, FORGE, SOLC):
        if not executable.is_file():
            raise FileNotFoundError(executable)
    if _command("git", "rev-parse", "HEAD", cwd=UPSTREAM) != PIN \
            or _command("git", "status", "--porcelain", cwd=UPSTREAM):
        raise RuntimeError("ERC-8183 source checkout is not clean and pinned")
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    with (output / "forge-build.log").open("w", encoding="utf-8") as build_log:
        subprocess.run([str(FORGE), "build", "--offline", "--use", str(SOLC),
                        "--threads", "4"], cwd=UPSTREAM,
                       stdout=build_log, stderr=subprocess.STDOUT,
                       check=True, timeout=60)
    token_path = UPSTREAM / "out" / "MockUSDC.sol" / "MockUSDC.json"
    token_artifact = json.loads(token_path.read_text(encoding="utf-8"))
    actual_port = port or _free_port()
    helper = NativeRun(output, actual_port)
    account_count = 1 + 3 * len(rows)
    with (output / "anvil.log").open("w", encoding="utf-8") as anvil_log:
        process = subprocess.Popen([
            str(ANVIL), "--host", "127.0.0.1", "--port", str(actual_port),
            "--chain-id", str(CHAIN_ID), "--hardfork", "cancun",
            "--timestamp", str(GENESIS_TIMESTAMP), "--accounts", str(account_count),
            "--balance", "1000",
            "--mnemonic", "test test test test test test test test test test test junk",
            "--quiet",
        ], stdout=anvil_log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 15
            while True:
                if process.poll() is not None:
                    raise RuntimeError("local Anvil exited before readiness")
                try:
                    observed_chain = _hex_int(helper.rpc.call("eth_chainId"))
                    break
                except (OSError, ConnectionError):
                    if time.monotonic() > deadline:
                        raise TimeoutError("local Anvil did not become ready")
                    time.sleep(0.05)
            if observed_chain != CHAIN_ID:
                raise ValueError("unexpected local chain ID")
            accounts = helper.rpc.call("eth_accounts")
            if len(accounts) != account_count or len(set(a.lower() for a in accounts)) != account_count:
                raise AssertionError("local test accounts are not distinct")
            helper.roles = {"admin": accounts[0]}
            addresses = {}
            for i, trial in enumerate(rows):
                triplet = dict(zip(("client", "worker", "auditor"),
                                   accounts[1 + 3 * i:1 + 3 * i + 3]))
                addresses[trial.trial_id] = triplet
                for role, address in triplet.items():
                    helper.roles[f"{role}.{trial.trial_id}"] = address
            helper._event_names(token_artifact)
            deploy_receipt = helper.tx("deploy.mock_usdc", "admin", None,
                                       token_artifact["bytecode"]["object"])
            helper.token = deploy_receipt["contractAddress"]
            code = bytes.fromhex(helper.rpc.call("eth_getCode", [helper.token, "latest"])[2:])
            if not code:
                raise AssertionError("local MockUSDC has no runtime code")
            pairs = []
            for trial in rows:
                roles = addresses[trial.trial_id]
                payer_role = "worker" if trial.r else "client"
                payer = roles[payer_role]
                payee = roles["auditor"]
                helper.tx(f"mint.{trial.trial_id}", "admin", helper.token,
                          helper.calldata("mint(address,uint256)", payer, FEE_MINOR_UNITS),
                          events=("Transfer",))
                before = {role: helper.balance(address) for role, address in roles.items()}
                if (before[payer_role] != FEE_MINOR_UNITS
                        or before["auditor"] != 0
                        or sum(before.values()) != FEE_MINOR_UNITS):
                    raise AssertionError("native pair mint has unexpected balances")
                receipt = helper.tx(
                    f"transfer.{trial.trial_id}", f"{payer_role}.{trial.trial_id}",
                    helper.token,
                    helper.calldata("transfer(address,uint256)", payee, FEE_MINOR_UNITS),
                    events=("Transfer",),
                )
                raw_tx = helper.rpc.call("eth_getTransactionByHash", [receipt["transactionHash"]])
                chain_receipt = helper.rpc.call("eth_getTransactionReceipt", [receipt["transactionHash"]])
                if chain_receipt != receipt:
                    raise AssertionError("local chain receipt changed after settlement")
                after = {role: helper.balance(address) for role, address in roles.items()}
                if (after[payer_role] != 0 or after["auditor"] != FEE_MINOR_UNITS
                        or sum(after.values()) != FEE_MINOR_UNITS):
                    raise AssertionError("native pair fee did not settle exactly")
                pairs.append({
                    "trial_id": trial.trial_id, "pair_id": trial.pair_id,
                    "obligation_id": trial.obligation_id, "R": trial.r,
                    "payer_role": payer_role, "addresses": roles,
                    "balances_before_minor": before,
                    "balances_after_minor": after,
                    "transfer_transaction": {
                        "hash": receipt["transactionHash"],
                        "raw_transaction": raw_tx,
                        "raw_receipt": receipt,
                        "raw_receipt_sha256": sha256(_canonical(receipt)).hexdigest(),
                    },
                })
            final_supply = helper.uint(helper.token, "totalSupply()")
            final_auditor_sum = sum(helper.balance(addresses[t.trial_id]["auditor"])
                                    for t in rows)
            if final_supply != len(rows) * FEE_MINOR_UNITS \
                    or final_auditor_sum != final_supply:
                raise AssertionError("native minted supply did not reach assigned auditors")
            evidence = {
                "schema": "w10-native-pair-funding-v1",
                "work_order": "W10", "gate": "G4_PREP",
                "model_behavior_tier": "NOT_EXECUTED",
                "payment_tier": "NATIVE_LOCAL_ERC20",
                "assignment_manifest_sha256": plan_sha,
                "obligation_binding": "APPLICATION_UNIQUE_TX_MAP",
                "source": {
                    "erc8183_base_commit": PIN,
                    "mock_usdc_artifact_path": str(token_path),
                    "mock_usdc_artifact_sha256": _sha256(token_path),
                    "foundry_version": "1.8.5", "solc_version": "0.8.28",
                },
                "chain": {"rpc_host": "127.0.0.1", "port": actual_port,
                          "chain_id": CHAIN_ID, "hardfork": "cancun",
                          "genesis_timestamp": GENESIS_TIMESTAMP},
                "token_address": helper.token,
                "token_runtime_code_sha256": sha256(code).hexdigest(),
                "asset": {"name": "MockUSDC", "decimals": 6, "real_value": 0,
                          "supply_minor_units": final_supply},
                "fee_minor_units": FEE_MINOR_UNITS,
                "initial_deployment": helper.transactions[0],
                "native_transactions_count": len(helper.transactions),
                "pairs": pairs,
                "limitations": [
                    "No LLM decision was made during funding.",
                    "Fees are fixed and prepaid, not contingent on auditor verdict.",
                    "ERC-20 Transfer does not encode the business obligation; mapping is application evidence.",
                    "Direct ERC-20 transfers are not ERC-8183 evaluator escrow semantics.",
                    "Addresses and tokens exist only on disposable localhost Anvil with zero real value.",
                ],
            }
            evidence_path = output / "evidence.json"
            evidence_path.write_bytes(_canonical(evidence) + b"\n")
            verified = NativePairFundingVerifier(evidence_path, rows, plan_sha)
            for trial in rows:
                verified(trial)
            return {
                "evidence": str(evidence_path),
                "evidence_sha256": verified.evidence_sha256,
                "verified_pairs": len(verified.by_trial),
                "native_transactions": len(helper.transactions),
                "R0_client_funded": sum(t.r == 0 for t in rows),
                "R1_worker_funded": sum(t.r == 1 for t in rows),
                "model_calls": 0,
            }
        except BaseException as exc:
            (output / "failure.json").write_text(json.dumps({
                "error_type": type(exc).__name__,
                "native_transactions_before_failure": len(helper.transactions),
            }, sort_keys=True) + "\n", encoding="utf-8")
            raise
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    print(json.dumps(run(args.plan, args.output, args.port), sort_keys=True))


if __name__ == "__main__":
    main()
