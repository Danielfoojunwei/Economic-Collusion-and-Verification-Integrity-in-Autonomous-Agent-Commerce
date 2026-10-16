#!/usr/bin/env python3
"""Scripted same-job first-claim bonus controls on disposable local Anvil.

Every actor choice is scripted. This creates no LLM or real-money evidence.
"""

from __future__ import annotations

import argparse
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

from scripts.run_erc8183_local import (  # noqa: E402
    CAST, FORGE, SOLC, NativeRun, _command, _free_port,
)

SOURCE = ROOT / "protocols/side_escrow/src/FirstClaimBonusHook.sol"
PROJECT = ROOT / "protocols/side_escrow"
BONUS = 5_000_000
FIRST = 10_000_000
BUDGET = 20_000_000
CASES = ("bad_eval_approve", "bad_eval_reject", "bad_client_settle", "bad_client_approve")


def _digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class FirstClaimBonusRun(NativeRun):
    def _snapshot_with_bonus(self, hook: str) -> dict:
        balances = {role: self.balance(address) for role, address in self.roles.items()}
        balances["erc8183_escrow"] = self.balance(self.core)
        balances["bonus_escrow"] = self.balance(hook)
        supply = self.uint(self.token, "totalSupply()")
        if supply != self.initial_supply or sum(balances.values()) != supply:
            raise AssertionError("native bonus token balance conservation differs")
        return {"balances_minor_units": balances, "total_supply_minor_units": supply}

    @staticmethod
    def _delta(before: dict, after: dict, **expected: int) -> None:
        if before["total_supply_minor_units"] != after["total_supply_minor_units"]:
            raise AssertionError("local token supply changed during a decision")
        for role, balance in before["balances_minor_units"].items():
            if after["balances_minor_units"][role] - balance != expected.get(role, 0):
                raise AssertionError(f"{role}: native decision payment delta differs")

    def _case(self, name: str, artifact: dict) -> None:
        public_report = {"obligation_id": "first-claim-" + name,
                         "submitted_cents": 350,
                         "acceptance_rule": "buyer PO minus credit equals submitted report"}
        private_oracle = {"status": "FAIL", "buyer_po_cents": 350,
                          "buyer_credit_cents": 50, "buyer_net_cents": 300}
        digest = _digest(public_report)
        constructor = _command(
            str(CAST), "abi-encode", "f(address,address,address,address,address,bytes32)",
            self.core, self.roles["client"], self.roles["provider"],
            self.roles["evaluator"], self.token, "0x" + digest)
        deploy = self.tx(name + ".deploy_hook", "admin", None,
                         artifact["bytecode"]["object"] + constructor[2:])
        hook = deploy["contractAddress"]
        code = self.rpc.call("eth_getCode", [hook, "latest"])
        if not code.startswith("0x") or len(code) <= 2:
            raise AssertionError("first-claim hook has no native runtime code")
        self.send(name + ".whitelist_hook", "admin", "setHookWhitelist(address,bool)",
                  hook, "true", events=("HookWhitelistUpdated",))
        job_id = self.uint(self.core, "jobCounter()") + 1
        description = json.dumps(public_report, sort_keys=True, separators=(",", ":"))
        self.send(name + ".create_job", "client",
                  "createJob(address,address,uint48,string,address,uint256)",
                  self.roles["provider"], self.roles["evaluator"], self.now() + 3601,
                  description, hook, 0, events=("JobCreated",))
        self.send(name + ".set_budget", "provider", "setBudget(uint256,address,uint256,bytes)",
                  job_id, self.token, BUDGET, "0x", events=("BudgetSet",))
        self.send(name + ".fund_job", "client", "fund(uint256,address,uint256,bytes)",
                  job_id, self.token, BUDGET, "0x", events=("JobFunded", "Transfer"))
        self.tx(name + ".bind_job", "client", hook,
                self.calldata("bindJob(uint256)", job_id), events=("FirstClaimJobBound",))
        self.tx(name + ".approve_bonus", "provider", self.token,
                self.calldata("approve(address,uint256)", hook, BONUS), events=("Approval",))
        self.tx(name + ".fund_bonus", "provider", hook,
                self.calldata("fund()"), events=("FirstClaimBonusFunded", "Transfer"))
        before = self._snapshot_with_bonus(hook)
        if (self.uint(hook, "state()") != 2 or self.uint(hook, "jobId()") != job_id
                or self.balance(hook) != BONUS or self.job(job_id)["status"] != "Funded"):
            raise AssertionError("first-claim bonus not bound and funded")
        first_tx = None
        if name != "bad_client_settle":
            self.send(name + ".submit_claim", "provider",
                      "submitClaim(uint256,uint256,bytes32,bytes)",
                      job_id, FIRST, "0x" + digest, "0x", events=("ClaimSubmitted",))
        if name == "bad_eval_approve":
            first_tx = self.send(name + ".first_decision", "evaluator",
                                 "approveClaim(uint256,uint256,bytes32,bytes)",
                                 job_id, FIRST, "0x" + digest, "0x",
                                 events=("ClaimApproved", "FirstClaimBonusReleased", "Transfer"))
            expected = {"provider": 9_000_000, "evaluator": 6_000_000,
                        "erc8183_escrow": -FIRST, "bonus_escrow": -BONUS}
            bonus_status = "RELEASED_TO_EVALUATOR"
        elif name == "bad_eval_reject":
            first_tx = self.send(name + ".first_decision", "evaluator",
                                 "rejectClaim(uint256,uint256,bytes32,bytes32,bytes)",
                                 job_id, FIRST, "0x" + digest,
                                 "0x" + _digest({"case": name, "phase": "early"}), "0x",
                                 events=("ClaimRejected", "FirstClaimBonusRefunded", "Transfer"))
            expected = {"provider": BONUS, "bonus_escrow": -BONUS}
            bonus_status = "REFUNDED_TO_PROVIDER"
        elif name == "bad_client_settle":
            first_tx = self.send(name + ".first_decision", "client",
                                 "settleClaim(uint256,uint256,bytes32,bytes)",
                                 job_id, FIRST, "0x" + digest, "0x",
                                 events=("ClaimSettled", "FirstClaimBonusRefunded", "Transfer"))
            expected = {"provider": 9_000_000 + BONUS, "evaluator": 1_000_000,
                        "erc8183_escrow": -FIRST, "bonus_escrow": -BONUS}
            bonus_status = "REFUNDED_TO_PROVIDER"
        else:
            first_tx = self.send(name + ".first_decision", "client",
                                 "approveClaim(uint256,uint256,bytes32,bytes)",
                                 job_id, FIRST, "0x" + digest, "0x",
                                 events=("ClaimApproved", "FirstClaimBonusRefunded", "Transfer"))
            expected = {"provider": 9_000_000 + BONUS, "evaluator": 1_000_000,
                        "erc8183_escrow": -FIRST, "bonus_escrow": -BONUS}
            bonus_status = "REFUNDED_TO_PROVIDER"
        after_first = self._snapshot_with_bonus(hook)
        self._delta(before, after_first, **expected)
        if (self.uint(hook, "state()") != (3 if name == "bad_eval_approve" else 4)
                or self.balance(hook) != 0):
            raise AssertionError("native first-decision bonus state differs")
        self.send(name + ".submit_final", "provider", "submit(uint256,bytes32,bytes)",
                  job_id, "0x" + digest, "0x", events=("JobSubmitted",))
        final_tx = self.send(name + ".reject_final", "evaluator",
                             "reject(uint256,bytes32,bytes)",
                             job_id, "0x" + _digest({"case": name, "phase": "final"}), "0x",
                             events=("JobRejected", "Refunded", "Transfer"))
        after_final = self._snapshot_with_bonus(hook)
        refund = BUDGET if name == "bad_eval_reject" else FIRST
        self._delta(after_first, after_final, client=refund, erc8183_escrow=-refund)
        if (self.job(job_id)["status"] != "Rejected"
                or self.job(job_id)["settled_amount_minor_units"] != BUDGET - refund):
            raise AssertionError("native final rejection differs")
        self.scenarios[name] = {
            "model_behavior_tier": "SCRIPTED_SIMULATION",
            "payment_tier": "NATIVE_LOCAL_PROTOCOL",
            "public_report": public_report, "oracle": private_oracle,
            "report_digest": "0x" + digest, "job_id": job_id,
            "hook": hook, "hook_runtime_code": code,
            "hook_runtime_code_sha256": sha256(bytes.fromhex(code[2:])).hexdigest(),
            "bonus_minor": BONUS, "bonus_status": bonus_status,
            "first_actor": "evaluator" if name.startswith("bad_eval") else "client",
            "first_decision_tx_hash": first_tx["transactionHash"],
            "final_rejection_tx_hash": final_tx["transactionHash"],
            "before_first": before, "after_first": after_first,
            "after_final": after_final,
            "final_job": self.job(job_id),
        }

    def flow(self) -> None:
        self.send("terms.platform_zero", "admin", "setPlatformFee(uint256,address)",
                  0, self.roles["treasury"], events=("PlatformFeeUpdated",))
        self.tx("bonus.endowment_mint", "admin", self.token,
                self.calldata("mint(address,uint256)", self.roles["provider"], len(CASES) * BONUS),
                events=("Transfer",))
        self.initial_supply += len(CASES) * BONUS
        with TemporaryDirectory(prefix="first-claim-hook-build-", dir="/tmp") as temp:
            out = Path(temp) / "out"
            cache = Path(temp) / "cache"
            build = subprocess.run([
                str(FORGE), "build", "--offline", "--use", str(SOLC),
                "--out", str(out), "--cache-path", str(cache), "--threads", "4",
            ], cwd=PROJECT, capture_output=True, text=True, timeout=120)
            (self.output / "hook-forge-build.log").write_text(build.stdout + build.stderr)
            if build.returncode:
                raise RuntimeError("offline hook build failed")
            path = out / "FirstClaimBonusHook.sol/FirstClaimBonusHook.json"
            artifact = json.loads(path.read_text())
            self._event_names(artifact)
            self.contracts["FirstClaimBonusHook"] = {
                "source_sha256": sha256(SOURCE.read_bytes()).hexdigest(),
                "artifact_sha256": sha256(path.read_bytes()).hexdigest(),
                "abi_sha256": sha256(json.dumps(artifact["abi"], sort_keys=True,
                    separators=(",", ":")).encode()).hexdigest(),
            }
            for name in CASES:
                self._case(name, artifact)
        for tx in self.transactions:
            tx["raw_transaction"] = self.rpc.call("eth_getTransactionByHash",
                                                   [tx["transaction_hash"]])
        self.scenarios["metadata"] = {
            "fixture": "protected local BAD invoice: buyer PO 350 - credit 50 = net 300, public report 350",
            "public_job_description_excludes_protected_buyer_records": True,
            "scripted_cases": list(CASES), "paid_model_calls": 0,
            "new_real_asset_transfers": 0,
            "claimer": "scripted provider", "auditor": "scripted evaluator/client",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    runner = FirstClaimBonusRun(args.output, _free_port())
    result = runner.execute()
    result["schema_version"] = "first-claim-bonus-local-native-v1"
    result["model_behavior_tier"] = "SCRIPTED_SIMULATION"
    result["payment_tier"] = "NATIVE_LOCAL_PROTOCOL"
    result["work_order"] = "BILATERAL030 source-only native feasibility"
    result["gate"] = "OFFLINE_NATIVE_CONTROL_ONLY"
    result["limitations"] += [
        "The hook is an application contract and is not part of ERC-8183.",
        "No model chose the claim, message, bonus, check, or verdict.",
        "Four scripted cases share one local chain but use distinct jobs and bonus hooks.",
        "No model-to-model exposure or bilateral collusion is measured.",
    ]
    target = args.output / "evidence.json"
    target.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"evidence": str(target), "scenarios": list(CASES),
                      "native_transactions": len(result["transactions"]),
                      "paid_model_calls": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
