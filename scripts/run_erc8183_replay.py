#!/usr/bin/env python3
"""Replay frozen scripted verdicts through native ERC-8183 with/without an app guard.

The guard is an idealized application-side oracle upper bound. It is neither an
ERC-8183 rule nor a measured LLM decision. All token transfers use a valueless
MockUSDC on a fresh localhost Anvil process.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from run_erc8183_local import (
    ANVIL, BUDGET, CAST, CHAIN_ID, FORGE, GENESIS_TIMESTAMP, PIN, SOLC,
    SUBMODULE_PINS, UNIT, UPSTREAM, NativeRun, _command, _free_port, _hex_int,
)


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agent_economic_trust.core import AuditState, FIXTURES, OracleStatus, oracle_score


def _canonical_hash(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def application_evidence_guard(*, decision: dict[str, Any], submitted_digest: str,
                               fixture: Any, artifact: Any) -> dict[str, Any]:
    """Ideal oracle-backed dispatch rule, evaluated only after the decision froze."""
    oracle = oracle_score(fixture, artifact)
    digest_bound = decision["artifact_digest"] == submitted_digest == artifact.digest()
    task_bound = artifact.task_id == fixture.task_id
    allow = decision["verdict"] == "ACCEPT" and digest_bound and task_bound and oracle.status == OracleStatus.PASS
    return {
        "origin": "APPLICATION_IDEAL_ORACLE_UPPER_BOUND",
        "allow_complete": allow,
        "digest_bound": digest_bound,
        "task_bound": task_bound,
        "oracle_status": oracle.status.value,
        "oracle_reason_code": oracle.reason_code,
        "verification_calls": 1,
        "monetary_verification_cost_measured": False,
    }


class ReplayRun(NativeRun):
    def prestate(self, job_id: int) -> dict[str, Any]:
        block = self.rpc.call("eth_getBlockByNumber", ["latest", False])
        return {
            "block_number": _hex_int(block["number"]),
            "block_hash": block["hash"],
            "block_timestamp": _hex_int(block["timestamp"]),
            "job_counter": self.uint(self.core, "jobCounter()"),
            "job": self.job(job_id),
            "pending_claim_hash": self.pending_claim(job_id),
            "token_state": self.snapshot(),
            "actor_nonces": {
                role: _hex_int(self.rpc.call("eth_getTransactionCount", [address, "latest"]))
                for role, address in self.roles.items()
            },
        }

    def branch_transactions(self, start: int, name: str) -> list[dict[str, Any]]:
        transactions = []
        for saved in self.transactions[start:]:
            raw_tx = self.rpc.call("eth_getTransactionByHash", [saved["transaction_hash"]])
            if raw_tx is None or raw_tx["hash"].lower() != saved["transaction_hash"].lower():
                raise AssertionError("branch transaction cannot be read before snapshot restore")
            transactions.append({**saved, "branch": name, "raw_transaction": raw_tx})
        return transactions

    def run_pair(self, case: str) -> dict[str, Any]:
        fixture, artifact = FIXTURES[case]
        oracle = oracle_score(fixture, artifact)
        expected = OracleStatus.PASS if case == "good" else OracleStatus.FAIL
        if oracle.status != expected:
            raise AssertionError(f"{case} fixture oracle status changed")

        preparation_start = len(self.transactions)
        job_id, _ = self.create_funded(case, fixture.public_task()["task_prompt"])
        self.submit(case, job_id, artifact.digest())
        submission = self.transactions[-1]
        submitted_events = [log for log in submission["logs"] if log["name"] == "JobSubmitted"]
        if len(submitted_events) != 1 or submitted_events[0]["data"].lower() != "0x" + artifact.digest():
            raise AssertionError("submitted on-chain artifact digest is not uniquely bound")
        preparation_transactions = self.branch_transactions(preparation_start, "preparation")
        submitted_digest = artifact.digest()

        state = AuditState(fixture, artifact, budget_units=0, check_cost_units=1)
        decision = state.submit(actor="auditor", verdict="ACCEPT", request_id=f"w07-{case}").public_result()
        if decision["check_completed"] or decision["check_spent_units"]:
            raise AssertionError("frozen control verdict unexpectedly used an oracle check")
        decision_hash = _canonical_hash(decision)
        attestation = "0x" + decision_hash
        prestate = self.prestate(job_id)
        snapshot_id = self.rpc.call("evm_snapshot")

        # The native contract checks evaluator identity and job state, not the
        # deliverable's correctness. This branch calls its real complete method.
        start = len(self.transactions)
        self.send(f"{case}.unguarded.complete", "evaluator", "complete(uint256,bytes32,bytes)",
                  job_id, attestation, "0x",
                  events=("JobCompleted", "PaymentReleased", "EvaluatorFeePaid", "PlatformFeePaid"))
        unguarded_paid = self.prestate(job_id)
        self.assert_delta(prestate["token_state"], unguarded_paid["token_state"],
                          escrow=-BUDGET, provider=17 * UNIT, evaluator=2 * UNIT, treasury=UNIT)
        self.send(f"{case}.unguarded.replay_complete", "evaluator", "complete(uint256,bytes32,bytes)",
                  job_id, attestation, "0x", status=0)
        unguarded_post_replay = self.prestate(job_id)
        if unguarded_post_replay["token_state"] != unguarded_paid["token_state"] or self.job(job_id)["status"] != "Completed":
            raise AssertionError("replayed completion paid again or changed terminal state")
        unguarded_transactions = self.branch_transactions(start, "unguarded")

        reverted = self.rpc.call("evm_revert", [snapshot_id])
        if reverted is not True:
            raise AssertionError("Anvil did not restore the paired pre-state")
        restored = self.prestate(job_id)
        if restored != prestate:
            raise AssertionError("paired arms did not begin from identical chain pre-state")

        guard = application_evidence_guard(decision=decision, submitted_digest=submitted_digest,
                                           fixture=fixture, artifact=artifact)
        start = len(self.transactions)
        if guard["allow_complete"]:
            self.send(f"{case}.guarded.complete", "evaluator", "complete(uint256,bytes32,bytes)",
                      job_id, attestation, "0x",
                      events=("JobCompleted", "PaymentReleased", "EvaluatorFeePaid", "PlatformFeePaid"))
            guarded_first = self.prestate(job_id)
            self.send(f"{case}.guarded.replay_complete", "evaluator", "complete(uint256,bytes32,bytes)",
                      job_id, attestation, "0x", status=0)
        else:
            # An authorized application dispatcher overrides the frozen ACCEPT
            # and instructs the evaluator to reject/refund. The contract does
            # not perform this semantic check itself.
            guard_reason = "0x" + _canonical_hash({"decision_sha256": decision_hash, "guard": guard})
            self.send(f"{case}.guarded.reject", "evaluator", "reject(uint256,bytes32,bytes)",
                      job_id, guard_reason, "0x", events=("JobRejected", "Refunded"))
            guarded_first = self.prestate(job_id)
            self.send(f"{case}.guarded.replay_reject", "evaluator", "reject(uint256,bytes32,bytes)",
                      job_id, guard_reason, "0x", status=0)
        guarded_final = self.prestate(job_id)
        expected_status = "Completed" if guard["allow_complete"] else "Rejected"
        if guarded_final["job"]["status"] != expected_status:
            raise AssertionError("guarded dispatch did not reach expected native state")
        if guard["allow_complete"]:
            self.assert_delta(prestate["token_state"], guarded_final["token_state"],
                              escrow=-BUDGET, provider=17 * UNIT, evaluator=2 * UNIT, treasury=UNIT)
        else:
            self.assert_delta(prestate["token_state"], guarded_final["token_state"],
                              escrow=-BUDGET, client=BUDGET)
        guarded_transactions = self.branch_transactions(start, "guarded")
        if guarded_transactions[0]["raw_transaction"]["from"].lower() != self.roles["evaluator"].lower():
            raise AssertionError("guard dispatcher used the wrong native evaluator identity")
        if guarded_transactions[0]["raw_transaction"]["nonce"] != unguarded_transactions[0]["raw_transaction"]["nonce"]:
            raise AssertionError("evaluator nonce differs across supposedly identical pre-states")
        if guard["allow_complete"] and guarded_transactions[0]["raw_transaction"]["input"] != unguarded_transactions[0]["raw_transaction"]["input"]:
            raise AssertionError("same accepted decision produced different native calldata")
        if guarded_final["token_state"] != self.prestate(job_id)["token_state"]:
            raise AssertionError("terminal transaction replay changed balances")
        if guarded_final["token_state"] != guarded_first["token_state"] or guarded_final["job"] != guarded_first["job"]:
            raise AssertionError("terminal transaction replay changed balances or job state")

        return {
            "case": case,
            "task_id": fixture.task_id,
            "job_id": job_id,
            "oracle_status": oracle.status.value,
            "artifact_digest": submitted_digest,
            "submitted_event": submitted_events[0],
            "preparation_transactions": preparation_transactions,
            "frozen_auditor_decision": decision,
            "frozen_decision_sha256": decision_hash,
            "decision_origin": "fixed scripted unchecked control",
            "prestate_snapshot_id": snapshot_id,
            "prestate": prestate,
            "restored_prestate": restored,
            "identical_prestate": restored == prestate,
            "arms": {
                "unguarded": {
                    "application_guard": "absent", "transactions": unguarded_transactions,
                    "final_state": unguarded_paid,
                    "post_replay_state": unguarded_post_replay,
                    "wrongful_payment": oracle.status != OracleStatus.PASS,
                },
                "guarded": {
                    "application_guard": guard, "transactions": guarded_transactions,
                    "final_state": guarded_final,
                    "pre_replay_state": guarded_first,
                    "wrongful_payment": guard["allow_complete"] and oracle.status != OracleStatus.PASS,
                },
            },
        }

    def execute_replay(self) -> dict[str, Any]:
        if self.output.exists():
            raise FileExistsError(f"refusing to overwrite replay receipts: {self.output}")
        self.output.mkdir(parents=True)
        for executable in (CAST, FORGE, ANVIL, SOLC):
            if not executable.is_file():
                raise FileNotFoundError(executable)
        if _command("git", "rev-parse", "HEAD", cwd=UPSTREAM) != PIN or _command("git", "status", "--porcelain", cwd=UPSTREAM):
            raise RuntimeError("ERC-8183 upstream checkout is not clean at pinned commit")
        for name, expected in SUBMODULE_PINS.items():
            if _command("git", "rev-parse", "HEAD", cwd=UPSTREAM / name) != expected:
                raise RuntimeError(f"ERC-8183 submodule is not pinned: {name}")
        with (self.output / "forge-build.log").open("w", encoding="utf-8") as log:
            subprocess.run([str(FORGE), "build", "--offline", "--use", str(SOLC), "--threads", "4"],
                           cwd=UPSTREAM, stdout=log, stderr=subprocess.STDOUT, check=True)
        with (self.output / "anvil.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([
                str(ANVIL), "--host", "127.0.0.1", "--port", str(self.port),
                "--chain-id", str(CHAIN_ID), "--hardfork", "cancun",
                "--timestamp", str(GENESIS_TIMESTAMP), "--accounts", "6", "--balance", "1000",
                "--mnemonic", "test test test test test test test test test test test junk", "--quiet",
            ], stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 10
                while True:
                    if process.poll() is not None:
                        raise RuntimeError("Anvil exited before its loopback RPC became ready")
                    try:
                        chain_id = _hex_int(self.rpc.call("eth_chainId"))
                        break
                    except (OSError, ConnectionError):
                        if time.monotonic() > deadline:
                            raise TimeoutError("Anvil loopback RPC did not become ready")
                        time.sleep(0.05)
                if chain_id != CHAIN_ID:
                    raise AssertionError(f"unexpected local chain ID {chain_id}")
                accounts = self.rpc.call("eth_accounts")
                if len(accounts) != 6 or len({account.lower() for account in accounts}) != 6:
                    raise AssertionError("Anvil test accounts are missing or duplicated")
                self.roles = dict(zip(("admin", "client", "provider", "evaluator", "treasury", "outsider"), accounts))
                self.deploy()
                setup_transactions = self.branch_transactions(0, "setup")
                pairs = {case: self.run_pair(case) for case in ("good", "bad")}
                evidence = {
                    "schema_version": 1, "work_order": "W07", "gate": "G2",
                    "model_behavior_tier": "SCRIPTED_SIMULATION",
                    "payment_tier": "NATIVE_LOCAL_PROTOCOL",
                    "execution_tier": "NATIVE_LOCAL_PROTOCOL",
                    "source": {"repository": "https://github.com/erc-8183/base-contracts",
                               "commit": PIN, "submodules": SUBMODULE_PINS, "license": "MIT",
                               "foundry_version": "1.8.5", "solc_version": "0.8.28+commit.7893614a"},
                    "chain": {"rpc_host": "127.0.0.1", "port": self.port,
                              "chain_id": CHAIN_ID, "hardfork": "cancun",
                              "genesis_timestamp": GENESIS_TIMESTAMP},
                    "actors": self.roles, "contracts": self.contracts,
                    "asset": {"name": "MockUSDC", "decimals": 6,
                              "supply_minor_units": self.initial_supply, "real_value": 0},
                    "setup_transactions": setup_transactions,
                    "pairs": pairs,
                    "limitations": [
                        "Frozen ACCEPT decisions are authored scripted controls, not LLM samples or collusion evidence.",
                        "The guard uses an independent, ideal task oracle and is an application-side upper bound, not native ERC-8183 enforcement or a deployable costed defense.",
                        "Each pair uses evm_snapshot/evm_revert; receipts from the first branch are saved before restore and are not all on one canonical final chain.",
                        "Only a valueless local test token and isolated Anvil were used; no testnet or production payment.",
                    ],
                }
                (self.output / "evidence.json").write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8")
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
    parser.add_argument("--output", required=True, type=Path, help="new directory for branch receipts")
    parser.add_argument("--port", default=0, type=int, help="loopback Anvil port; 0 chooses a free port")
    args = parser.parse_args()
    evidence = ReplayRun(args.output, args.port or _free_port()).execute_replay()
    print(json.dumps({"evidence": str(args.output / "evidence.json"),
                      "pairs": list(evidence["pairs"]),
                      "guarded_bad_status": evidence["pairs"]["bad"]["arms"]["guarded"]["final_state"]["job"]["status"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
