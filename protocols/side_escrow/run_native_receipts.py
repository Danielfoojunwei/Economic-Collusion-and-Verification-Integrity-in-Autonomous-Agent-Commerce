#!/usr/bin/env python3
"""Exercise the side escrow against pinned ERC-8183 on disposable local Anvil.

This records raw eth_getTransactionReceipt payloads for both native contracts.
Provider and evaluator choices are scripted controls, not LLM behavior.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from run_erc8183_local import (  # noqa: E402
    BUDGET, CAST, FORGE, SOLC, UNIT, NativeRun, _address, _command, _free_port, _hex_int,
)


BONUS = 5 * UNIT


class SideEscrowRun(NativeRun):
    def _check_event(self, receipt: dict, *, escrow: str, name: str, job_id: int,
                     recipient: str, amount: int, status: int | None = None) -> None:
        matches = [log for log in receipt["logs"] if log["address"].lower() == escrow.lower()
                   and self.abi_topics.get(log["topics"][0].lower()) == name]
        if len(matches) != 1:
            raise AssertionError(f"expected exactly one {name} event from bound side escrow")
        log = matches[0]
        if _hex_int(log["topics"][1]) != job_id:
            raise AssertionError(f"{name}: wrong job ID")
        if _address(log["topics"][2]).lower() != recipient.lower():
            raise AssertionError(f"{name}: wrong indexed address")
        if name == "BonusFunded":
            if _address(log["topics"][3]).lower() != self.roles["evaluator"].lower():
                raise AssertionError("BonusFunded: wrong auditor")
            words = [log["data"][2:66], log["data"][66:130]]
            if _address(words[0]).lower() != self.token.lower() or int(words[1], 16) != amount:
                raise AssertionError("BonusFunded: wrong token or amount")
        else:
            words = [log["data"][2:66], log["data"][66:130]]
            if int(words[0], 16) != amount or int(words[1], 16) != status:
                raise AssertionError("BonusSettled: wrong amount or job status")

    def _side_balance(self, escrow: str) -> int:
        return self.balance(escrow)

    def _deploy_side(self, label: str, job_id: int, expiry: int, artifact: dict) -> str:
        deadline = min(expiry - 1, self.now() + 1800)
        encoded = _command(str(CAST), "abi-encode", "f(address,uint256,address,address,address,uint256,uint48)",
                           self.core, str(job_id), self.roles["provider"], self.roles["evaluator"],
                           self.token, str(BONUS), str(deadline))
        receipt = self.tx(label + ".deploy_side", "admin", None,
                          artifact["bytecode"]["object"] + encoded[2:])
        escrow = receipt["contractAddress"]
        code = bytes.fromhex(self.rpc.call("eth_getCode", [escrow, "latest"])[2:])
        if not code:
            raise AssertionError("side escrow deployment returned no runtime code")
        for selector, expected in (
            ("core()", self.core), ("provider()", self.roles["provider"]),
            ("auditor()", self.roles["evaluator"]), ("token()", self.token),
        ):
            if _address(self.read(escrow, selector)).lower() != expected.lower():
                raise AssertionError(f"side escrow {selector} immutable mismatch")
        if self.uint(escrow, "jobId()") != job_id or self.uint(escrow, "bonusAmount()") != BONUS:
            raise AssertionError("side escrow job or amount immutable mismatch")
        if self.uint(escrow, "fundingDeadline()") != deadline:
            raise AssertionError("side escrow funding deadline immutable mismatch")
        self.tx(label + ".approve_bonus", "provider", self.token,
                self.calldata("approve(address,uint256)", escrow, BONUS), events=("Approval",))
        funded = self.tx(label + ".fund_bonus", "provider", escrow,
                         self.calldata("fund()"), events=("BonusFunded", "Transfer"))
        self._check_event(funded, escrow=escrow, name="BonusFunded", job_id=job_id,
                          recipient=self.roles["provider"], amount=BONUS)
        if self._side_balance(escrow) != BONUS:
            raise AssertionError("side escrow did not receive exact bonus amount")
        self.tx(label + ".premature_settle", "outsider", escrow,
                self.calldata("settle()"), status=0)
        return escrow

    def _settle_side(self, label: str, escrow: str, job_id: int,
                     recipient_role: str, status: int) -> dict:
        before = {role: self.balance(address) for role, address in self.roles.items()}
        side_before = self._side_balance(escrow)
        settled = self.tx(label + ".settle_bonus", "outsider", escrow,
                          self.calldata("settle()"), events=("BonusSettled", "Transfer"))
        self._check_event(settled, escrow=escrow, name="BonusSettled", job_id=job_id,
                          recipient=self.roles[recipient_role], amount=BONUS, status=status)
        if self._side_balance(escrow) != 0:
            raise AssertionError("side escrow balance was not exhausted after settlement")
        after = {role: self.balance(address) for role, address in self.roles.items()}
        if after[recipient_role] - before[recipient_role] != BONUS:
            raise AssertionError("wrong beneficiary or amount in native token balance")
        self.tx(label + ".replay_settle", "outsider", escrow,
                self.calldata("settle()"), status=0)
        return {"job_id": job_id, "side_escrow": escrow, "status_code": status,
                "bonus_recipient": recipient_role, "bonus_minor_units": BONUS,
                "bonus_receipt": settled["transactionHash"],
                "recipient_balance_before": before[recipient_role],
                "recipient_balance_after": after[recipient_role],
                "escrow_balance_before": side_before,
                "escrow_balance_after": self._side_balance(escrow),
                "side_runtime_code_sha256": sha256(bytes.fromhex(
                    self.rpc.call("eth_getCode", [escrow, "latest"])[2:])).hexdigest()}

    def flow(self) -> None:
        with (self.output / "side-forge-build.log").open("w", encoding="utf-8") as log:
            subprocess.run([str(FORGE), "build", "--offline", "--use", str(SOLC), "--threads", "4"],
                           cwd=HERE, stdout=log, stderr=subprocess.STDOUT, check=True)
        path = HERE / "out" / "ProviderAuditorBonusEscrow.sol" / "ProviderAuditorBonusEscrow.json"
        artifact = json.loads(path.read_text(encoding="utf-8"))
        self._event_names(artifact)
        self.contracts["ProviderAuditorBonusEscrow"] = {
            "artifact_path": str(path), "artifact_sha256": sha256(path.read_bytes()).hexdigest(),
            "source_sha256": sha256((HERE / "src" / "ProviderAuditorBonusEscrow.sol").read_bytes()).hexdigest(),
        }

        self.tx("setup.mint_provider_bonus", "admin", self.token,
                self.calldata("mint(address,uint256)", self.roles["provider"], 2 * BONUS),
                events=("Transfer",))
        self.initial_supply += 2 * BONUS

        good_id, good_expiry = self.create_funded("good", "scripted good work")
        good_escrow = self._deploy_side("good", good_id, good_expiry, artifact)
        self.submit("good", good_id, "ab" * 32)
        self.send("good.complete", "evaluator", "complete(uint256,bytes32,bytes)",
                  good_id, "0x" + "01" * 32, "0x",
                  events=("JobCompleted", "PaymentReleased"))
        if self.job(good_id)["status"] != "Completed":
            raise AssertionError("official core did not reach Completed")
        self.scenarios["completed"] = self._settle_side("good", good_escrow, good_id, "evaluator", 3)

        bad_id, bad_expiry = self.create_funded("bad", "scripted bad work")
        bad_escrow = self._deploy_side("bad", bad_id, bad_expiry, artifact)
        self.submit("bad", bad_id, "cd" * 32)
        self.send("bad.reject", "evaluator", "reject(uint256,bytes32,bytes)",
                  bad_id, "0x" + "02" * 32, "0x", events=("JobRejected", "Refunded"))
        if self.job(bad_id)["status"] != "Rejected":
            raise AssertionError("official core did not reach Rejected")
        self.scenarios["rejected"] = self._settle_side("bad", bad_escrow, bad_id, "provider", 4)
        if self._side_balance(good_escrow) or self._side_balance(bad_escrow):
            raise AssertionError("a side escrow retained bonus tokens")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new output directory for native receipts")
    args = parser.parse_args()
    run = SideEscrowRun(args.output, _free_port())
    evidence = run.execute()
    evidence["work_order"] = "exploratory provider funded offer mechanism"
    evidence["gate"] = "local feasibility only"
    evidence["source"]["side_escrow_script_sha256"] = sha256(Path(__file__).read_bytes()).hexdigest()
    evidence["limitations"].extend([
        "Both evaluator decisions are scripted controls; this does not show LLM influence or collusion.",
        "The side escrow pays on official Completed status, not independent artifact correctness.",
        "This local application contract is not an ERC-8183 standard feature or a security audit.",
    ])
    (args.output / "evidence.json").write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n",
                                               encoding="utf-8")
    print(json.dumps({"evidence": str(args.output / "evidence.json"),
                      "transactions": len(evidence["transactions"]),
                      "scenarios": list(evidence["scenarios"]),
                      "failed_receipts": sum(tx["status"] == 0 for tx in evidence["transactions"])},
                     sort_keys=True))


if __name__ == "__main__":
    main()
