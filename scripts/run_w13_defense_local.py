#!/usr/bin/env python3
"""Replay W13 scripted application decisions through pinned localhost ERC-8183.

One Anvil snapshot restores the deployment state for each policy. Receipts in
different branches are branch-local and do not all remain on one final chain.
No model, testnet, payment provider, or asset with real value is used.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from time import monotonic, monotonic_ns, sleep
from typing import Any

from run_erc8183_local import (
    ANVIL, BUDGET, CAST, CHAIN_ID, FORGE, GENESIS_TIMESTAMP, PIN, SOLC,
    SUBMODULE_PINS, UNIT, UPSTREAM, ZERO, _command, _free_port, _hex_int,
)
from run_erc8183_replay import ReplayRun


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agent_economic_trust.defense_comparison import POLICIES, evaluate_policy  # noqa: E402
from agent_economic_trust.w10_factorial import frozen_fixtures  # noqa: E402


def _sha_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


class DefenseNativeRun(ReplayRun):
    def create_funded_for(self, prefix: str, description: str, evaluator_role: str) -> int:
        if evaluator_role not in ("evaluator", "outsider"):
            raise ValueError("unknown local evaluator")
        job_id = self.uint(self.core, "jobCounter()") + 1
        expiry = self.now() + 3601
        self.send(prefix + ".create", "client", "createJob(address,address,uint48,string,address,uint256)",
                  self.roles["provider"], self.roles[evaluator_role], expiry, description, ZERO, 0,
                  events=("JobCreated",))
        self.send(prefix + ".budget", "provider", "setBudget(uint256,address,uint256,bytes)",
                  job_id, self.token, BUDGET, "0x", events=("BudgetSet",))
        self.send(prefix + ".fund", "client", "fund(uint256,address,uint256,bytes)",
                  job_id, self.token, BUDGET, "0x", events=("JobFunded", "Transfer"))
        if self.job(job_id)["status"] != "Funded":
            raise AssertionError("native funding failed")
        return job_id

    def run_branch(self, policy: str, setup_token_state: dict[str, Any]) -> dict[str, Any]:
        fixture_map = {item.fixture_id: item for item in frozen_fixtures()}
        decisions = evaluate_policy(policy, fixtures=fixture_map.values())
        if len(decisions["rows"]) != 4:
            raise AssertionError("defense comparison lost a controlled world")
        started = monotonic_ns()
        branch_start = len(self.transactions)
        rows: list[dict[str, Any]] = []
        for decision in decisions["rows"]:
            fixture = fixture_map[decision["fixture_id"]]
            prefix = f"{policy}.{fixture.fixture_id}"
            evaluator_role = ("outsider" if decision["reviewer_role"] == "independent_evaluator"
                              else "evaluator")
            job_id = self.create_funded_for(prefix, json.dumps(fixture.case.public_task(),
                                                  sort_keys=True), evaluator_role)
            self.submit(prefix, job_id, fixture.artifact.digest())
            submitted = self.prestate(job_id)
            if submitted["job"]["evaluator"].lower() != self.roles[evaluator_role].lower():
                raise AssertionError("assigned evaluator differs from native job")
            if submitted["job"]["status"] != "Submitted":
                raise AssertionError("native artifact was not submitted")
            action = decision["dispatch_intent"]
            action_start = monotonic_ns()
            if action == "COMPLETE":
                self.send(prefix + ".complete", evaluator_role,
                          "complete(uint256,bytes32,bytes)", job_id,
                          "0x" + sha256((prefix + ":ACCEPT").encode()).hexdigest(), "0x",
                          events=("JobCompleted", "PaymentReleased", "EvaluatorFeePaid", "PlatformFeePaid"))
            elif action == "REJECT":
                self.send(prefix + ".reject", evaluator_role,
                          "reject(uint256,bytes32,bytes)", job_id,
                          "0x" + sha256((prefix + ":REJECT").encode()).hexdigest(), "0x",
                          events=("JobRejected", "Refunded"))
            elif action != "HOLD":
                raise AssertionError("unexpected dispatch intent")
            dispatch_wall_ns = max(0, monotonic_ns() - action_start)
            final = self.prestate(job_id)
            if action == "COMPLETE":
                self.assert_delta(submitted["token_state"], final["token_state"],
                                  escrow=-BUDGET, provider=17 * UNIT,
                                  **{evaluator_role: 2 * UNIT}, treasury=UNIT)
                if final["job"]["status"] != "Completed":
                    raise AssertionError("completed dispatch did not settle")
            elif action == "REJECT":
                self.assert_delta(submitted["token_state"], final["token_state"],
                                  escrow=-BUDGET, client=BUDGET)
                if final["job"]["status"] != "Rejected":
                    raise AssertionError("rejection did not refund")
            elif final != submitted:
                raise AssertionError("held dispatch changed native state")
            paid = final["job"]["status"] == "Completed"
            rows.append({
                **decision, "job_id": job_id, "native_evaluator_role": evaluator_role,
                "submitted_state": submitted, "final_state": final,
                "dispatch_wall_ns": dispatch_wall_ns,
                "native_wrongful_payment": fixture.truth == 0 and paid,
                "native_honest_nonpayment": fixture.truth == 1 and not paid,
            })
        branch_txs = self.branch_transactions(branch_start, policy)
        final_token_state = self.snapshot()
        token_delta = {
            role: amount - setup_token_state["balances_minor_units"][role]
            for role, amount in final_token_state["balances_minor_units"].items()
        }
        if sum(token_delta.values()) != 0:
            raise AssertionError("native branch token deltas are not conserved")
        branch = {
            **{key: value for key, value in decisions.items() if key != "rows"},
            "payment_tier": "NATIVE_LOCAL_PROTOCOL",
            "model_calls": 0, "model_tokens": 0, "remote_model_spend_usd": 0,
            "branch_wall_ns": max(0, monotonic_ns() - started),
            "native_dispatch_wall_ns": sum(row["dispatch_wall_ns"] for row in rows),
            "native_transaction_gas_used": sum(item["gas_used"] for item in branch_txs),
            "native_final_token_state": final_token_state,
            "native_balance_delta_minor_units": token_delta,
            "native_wrongful_payment_count": sum(row["native_wrongful_payment"] for row in rows),
            "native_honest_nonpayment_count": sum(row["native_honest_nonpayment"] for row in rows),
            "rows": rows,
            "transactions": branch_txs,
        }
        if (branch["native_wrongful_payment_count"] != decisions["projected_wrongful_payment_count"]
                or branch["native_honest_nonpayment_count"] != decisions["projected_honest_nonpayment_count"]):
            raise AssertionError("native settlement differs from application dispatch projection")
        return branch

    def execute(self) -> dict[str, Any]:
        if self.output.exists():
            raise FileExistsError(f"refusing to overwrite native defense evidence: {self.output}")
        self.output.mkdir(parents=True)
        for binary in (ANVIL, CAST, FORGE, SOLC):
            if not binary.is_file():
                raise FileNotFoundError(binary)
        if (_command("git", "rev-parse", "HEAD", cwd=UPSTREAM) != PIN
                or _command("git", "status", "--porcelain", cwd=UPSTREAM)):
            raise RuntimeError("ERC-8183 upstream is not clean at the pinned commit")
        for name, expected in SUBMODULE_PINS.items():
            if _command("git", "rev-parse", "HEAD", cwd=UPSTREAM / name) != expected:
                raise RuntimeError(f"ERC-8183 submodule pin changed: {name}")
        with (self.output / "forge-build.log").open("w", encoding="utf-8") as log:
            subprocess.run([str(FORGE), "build", "--offline", "--use", str(SOLC),
                            "--threads", "4"], cwd=UPSTREAM, stdout=log,
                           stderr=subprocess.STDOUT, check=True)
        with (self.output / "anvil.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([
                str(ANVIL), "--host", "127.0.0.1", "--port", str(self.port),
                "--chain-id", str(CHAIN_ID), "--hardfork", "cancun",
                "--timestamp", str(GENESIS_TIMESTAMP), "--accounts", "6", "--balance", "1000",
                "--mnemonic", "test test test test test test test test test test test junk", "--quiet",
            ], stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = monotonic() + 10
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("Anvil exited before its loopback RPC became ready")
                    try:
                        chain_id = _hex_int(self.rpc.call("eth_chainId"))
                        break
                    except (OSError, ConnectionError):
                        if monotonic() > deadline:
                            raise TimeoutError("Anvil loopback RPC did not become ready")
                        sleep(0.05)
                if chain_id != CHAIN_ID:
                    raise AssertionError("unexpected local chain ID")
                accounts = self.rpc.call("eth_accounts")
                if len(accounts) != 6 or len({item.lower() for item in accounts}) != 6:
                    raise AssertionError("Anvil accounts missing or duplicated")
                self.roles = dict(zip(("admin", "client", "provider", "evaluator", "treasury", "outsider"), accounts))
                self.deploy()
                setup_transactions = self.branch_transactions(0, "setup")
                setup = {"job_counter": self.uint(self.core, "jobCounter()"),
                         "token_state": self.snapshot()}
                snapshot_id = self.rpc.call("evm_snapshot")
                branches: dict[str, Any] = {}
                for index, policy in enumerate(POLICIES):
                    if index:
                        if self.rpc.call("evm_revert", [snapshot_id]) is not True:
                            raise AssertionError("failed to restore defense policy pre-state")
                        restored = {"job_counter": self.uint(self.core, "jobCounter()"),
                                    "token_state": self.snapshot()}
                        if restored != setup:
                            raise AssertionError("policy branches have different deployment pre-state")
                        snapshot_id = self.rpc.call("evm_snapshot")
                    branches[policy] = self.run_branch(policy, setup["token_state"])
                evidence = {
                    "schema_version": 1, "work_order": "W13_PREP", "gate": "G5_PENDING",
                    "model_behavior_tier": "SCRIPTED_SIMULATION",
                    "payment_tier": "NATIVE_LOCAL_PROTOCOL", "execution_tier": "NATIVE_LOCAL_PROTOCOL",
                    "source": {"repository": "https://github.com/erc-8183/base-contracts",
                               "commit": PIN, "submodules": SUBMODULE_PINS,
                               "foundry_version": "1.8.5", "solc_version": "0.8.28+commit.7893614a"},
                    "code_sha256": {
                        path: _sha_file(ROOT / path) for path in (
                            "src/agent_economic_trust/defense_comparison.py",
                            "src/agent_economic_trust/w10_factorial.py",
                            "src/agent_economic_trust/protected_receipts.py",
                            "scripts/run_w13_defense_local.py")
                    },
                    "chain": {"rpc_host": "127.0.0.1", "port": self.port,
                              "chain_id": CHAIN_ID, "hardfork": "cancun"},
                    "asset": {"name": "MockUSDC", "decimals": 6,
                              "real_value": 0, "supply_minor_units": self.initial_supply},
                    "actors": self.roles, "contracts": self.contracts,
                    "setup_prestate": setup, "setup_transactions": setup_transactions,
                    "branches": branches,
                    "limitations": [
                        "All ACCEPT decisions are authored fixed controls; no live model changed decisions under a defense.",
                        "The principal budget is an application-level unit ledger, not an on-chain funded check allowance.",
                        "Independent assignment changes the local contract evaluator address; no reviewer behavior or ownership claim is measured.",
                        "Receipt check calls use the local protected oracle; observed wall times are process timings, not external service or model latency.",
                        "A selected public task is replayed in both private counterfactual worlds; four rows are not four independent tasks.",
                        "Anvil snapshot branches have saved native receipts but do not all survive on one final chain.",
                        "Only valueless MockUSDC on localhost was used.",
                    ],
                }
                (self.output / "evidence.json").write_text(json.dumps(evidence, sort_keys=True,
                                          indent=2) + "\n", encoding="utf-8")
                return evidence
            except Exception as exc:
                (self.output / "failure.json").write_text(json.dumps({
                    "error_type": type(exc).__name__, "error": str(exc),
                    "transactions": self.transactions,
                }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
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
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--port", default=0, type=int)
    args = parser.parse_args()
    evidence = DefenseNativeRun(args.output, args.port or _free_port()).execute()
    print(json.dumps({"evidence": str(args.output / "evidence.json"),
                      "branches": list(evidence["branches"]),
                      "wrongful_paid": {key: value["native_wrongful_payment_count"]
                                        for key, value in evidence["branches"].items()}}, sort_keys=True))


if __name__ == "__main__":
    main()
