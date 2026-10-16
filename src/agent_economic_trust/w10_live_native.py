"""Disposable native ERC-8183 job and live ERC-20 audit fee for one W10 pair.

The Anvil process stays alive through the model decision and payout. This is
local valueless execution; direct fee transfers and ERC-8183 job settlement
are distinct native actions with different guarantees.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import time
from typing import Any

from scripts.run_erc8183_local import (
    ANVIL, CAST, CHAIN_ID, FORGE, GENESIS_TIMESTAMP, NativeRun, PIN, SOLC,
    UPSTREAM, UNIT, BUDGET, _command, _free_port, _hex_int, _sha256,
)

from .w10_factorial import FEE_MINOR_UNITS, Trial, VerifiedFunding, _canonical
from .w10_funding import _expect_transfer


class NativeTrialError(RuntimeError):
    pass


class LiveNativeTrial:
    """One chain, one assigned pair, one prepaid fee, one escrowed job."""

    def __init__(self, trial: Trial, output: Path, *, pair_index: int,
                 assignment_manifest_sha256: str, port: int = 0):
        if not 0 <= pair_index < 32:
            raise ValueError("pair index is outside the frozen assignment")
        self.trial = trial
        self.output = Path(output)
        self.pair_index = pair_index
        self.assignment_manifest_sha256 = assignment_manifest_sha256
        self.port = port or _free_port()
        self.helper = NativeRun(self.output, self.port)
        self.process: subprocess.Popen | None = None
        self.anvil_log = None
        self.job_id: int | None = None
        self.fee_transaction: dict[str, Any] | None = None
        self.fee_receipt: dict[str, Any] | None = None
        self.fee_before: dict[str, int] | None = None
        self.fee_after: dict[str, int] | None = None
        self.task_settlement: dict[str, Any] | None = None
        self.native_evidence_sha256: str | None = None

    def __enter__(self) -> LiveNativeTrial:
        if self.output.exists():
            raise FileExistsError("native trial directory already exists")
        for binary in (ANVIL, CAST, FORGE, SOLC):
            if not binary.is_file():
                raise FileNotFoundError(binary)
        if _command("git", "rev-parse", "HEAD", cwd=UPSTREAM) != PIN \
                or _command("git", "status", "--porcelain", cwd=UPSTREAM):
            raise NativeTrialError("ERC-8183 checkout is not clean and pinned")
        self.output.mkdir(parents=True, mode=0o700, exist_ok=False)
        with (self.output / "forge-build.log").open("w", encoding="utf-8") as handle:
            subprocess.run([str(FORGE), "build", "--offline", "--use", str(SOLC),
                            "--threads", "4"], cwd=UPSTREAM, stdout=handle,
                           stderr=subprocess.STDOUT, check=True, timeout=60)
        self.anvil_log = (self.output / "anvil.log").open("w", encoding="utf-8")
        # All 32 frozen pairs map to distinct account triplets even though each
        # paid trial runs on a fresh isolated chain. No address is exposed to
        # the model; a fresh Inspect evaluation has no cross-arm memory.
        self.process = subprocess.Popen([
            str(ANVIL), "--host", "127.0.0.1", "--port", str(self.port),
            "--chain-id", str(CHAIN_ID), "--hardfork", "cancun",
            "--timestamp", str(GENESIS_TIMESTAMP), "--accounts", "99",
            "--balance", "1000",
            "--mnemonic", "test test test test test test test test test test test junk",
            "--quiet",
        ], stdout=self.anvil_log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 15
            while True:
                if self.process.poll() is not None:
                    raise NativeTrialError("local Anvil exited before RPC readiness")
                try:
                    chain_id = _hex_int(self.helper.rpc.call("eth_chainId"))
                    break
                except (OSError, ConnectionError):
                    if time.monotonic() > deadline:
                        raise TimeoutError("local Anvil RPC did not become ready")
                    time.sleep(0.05)
            if chain_id != CHAIN_ID:
                raise NativeTrialError("local chain ID changed")
            accounts = self.helper.rpc.call("eth_accounts")
            if len(accounts) != 99 or len(set(a.lower() for a in accounts)) != 99:
                raise NativeTrialError("local pair role addresses are not distinct")
            start = 1 + 3 * self.pair_index
            self.helper.roles = {
                "admin": accounts[0], "client": accounts[start],
                "provider": accounts[start + 1], "evaluator": accounts[start + 2],
                "treasury": accounts[97], "outsider": accounts[98],
            }
            self.helper.deploy()
            # W06's reusable baseline deploys a 10% contingent evaluator fee.
            # The W10 R contrast requires the auditor's only compensation to
            # be the fixed prepaid two-unit fee, regardless of verdict.
            self.helper.send("setup.zero_conditional_evaluator_fee", "admin",
                             "setEvaluatorFee(uint256)", 0,
                             events=("EvaluatorFeeUpdated",))
            self.helper.send("setup.zero_platform_fee", "admin",
                             "setPlatformFee(uint256,address)", 0,
                             self.helper.roles["treasury"],
                             events=("PlatformFeeUpdated",))
            description = (f"W10 obligation {self.trial.obligation_id}; "
                           f"artifact sha256 {self.trial.artifact_digest}; "
                           f"public task sha256 {self.trial.public_task_digest}")
            self.job_id, _ = self.helper.create_funded("assigned_job", description)
            job = self.helper.job(self.job_id)
            if (job["client"].lower() != self.helper.roles["client"].lower()
                    or job["provider"].lower() != self.helper.roles["provider"].lower()
                    or job["evaluator"].lower() != self.helper.roles["evaluator"].lower()
                    or job["payment_token"].lower() != self.helper.token.lower()
                    or job["budget_minor_units"] != BUDGET
                    or job["status"] != "Funded"):
                raise NativeTrialError("funded job roles or budget differ from assignment")
            if self.trial.r:
                self.helper.tx("setup.provider_fee_mint", "admin", self.helper.token,
                               self.helper.calldata("mint(address,uint256)",
                                                    self.helper.roles["provider"],
                                                    FEE_MINOR_UNITS), events=("Transfer",))
                self.helper.initial_supply += FEE_MINOR_UNITS
            self.fee_before = self._balances()
            payer_role = "provider" if self.trial.r else "client"
            receipt = self.helper.tx("assigned_prepaid_audit_fee", payer_role,
                                     self.helper.token,
                                     self.helper.calldata("transfer(address,uint256)",
                                                          self.helper.roles["evaluator"],
                                                          FEE_MINOR_UNITS),
                                     events=("Transfer",))
            self.fee_receipt = receipt
            self.fee_transaction = self.helper.rpc.call("eth_getTransactionByHash",
                                                         [receipt["transactionHash"]])
            self.fee_after = self._balances()
            self._verify_live_fee()
            return self
        except BaseException:
            self.__exit__(*sys_exc_info())
            raise

    def _balances(self) -> dict[str, int]:
        return {role: self.helper.balance(address)
                for role, address in self.helper.roles.items()} | {
                    "escrow": self.helper.balance(self.helper.core)
                }

    def _verify_live_fee(self) -> VerifiedFunding:
        if self.process is None or self.process.poll() is not None \
                or self.fee_transaction is None or self.fee_receipt is None \
                or self.fee_before is None or self.fee_after is None:
            raise NativeTrialError("native pair fee is not live")
        tx_hash = self.fee_receipt["transactionHash"]
        if self.helper.rpc.call("eth_getTransactionReceipt", [tx_hash]) != self.fee_receipt \
                or self.helper.rpc.call("eth_getTransactionByHash", [tx_hash]) != self.fee_transaction:
            raise NativeTrialError("live chain receipt differs from saved fee receipt")
        tx = self.fee_transaction
        payer_role = "provider" if self.trial.r else "client"
        payer = self.helper.roles[payer_role].lower()
        payee = self.helper.roles["evaluator"].lower()
        if (tx["from"].lower() != payer or tx["to"].lower() != self.helper.token.lower()
                or int(tx["chainId"], 16) != CHAIN_ID
                or tx["input"].lower() !=
                ("0xa9059cbb" + payee[2:].rjust(64, "0")
                 + format(FEE_MINOR_UNITS, "064x"))):
            raise NativeTrialError("live fee payer, recipient, amount, or chain differs")
        _expect_transfer(self.fee_receipt, self.helper.token.lower(), payer, payee,
                         FEE_MINOR_UNITS)
        current = self._balances()
        if current != self.fee_after:
            raise NativeTrialError("live balances changed before auditor decision")
        for role, old in self.fee_before.items():
            delta = -FEE_MINOR_UNITS if role == payer_role else \
                FEE_MINOR_UNITS if role == "evaluator" else 0
            if self.fee_after[role] - old != delta:
                raise NativeTrialError("live pair fee balance delta differs")
        self.helper.snapshot()  # local total supply conservation
        result = VerifiedFunding(
            obligation_id=self.trial.obligation_id, pair_id=self.trial.pair_id,
            payer_role="worker" if self.trial.r else "client", payee_role="auditor",
            amount_minor=FEE_MINOR_UNITS,
            receipt_sha256=sha256(_canonical(self.fee_receipt)).hexdigest(),
            transaction_hash=tx_hash, chain_id=CHAIN_ID,
            native_protocol="LOCAL_ERC20_TRANSFER",
        )
        result.assert_matches(self.trial)
        return result

    def __call__(self, trial: Trial) -> VerifiedFunding:
        if trial != self.trial:
            raise NativeTrialError("live funding verifier received another pair")
        return self._verify_live_fee()

    def settle_task(self, verdict: str, artifact_digest: str) -> dict[str, Any]:
        if self.task_settlement is not None or self.job_id is None:
            raise NativeTrialError("task settlement already attempted or job missing")
        if verdict not in {"ACCEPT", "REJECT"} or artifact_digest != self.trial.artifact_digest:
            raise NativeTrialError("auditor verdict or submitted artifact is not frozen")
        self._verify_live_fee()
        before = self.helper.snapshot()
        self.helper.submit("assigned_job", self.job_id, artifact_digest)
        decision = "complete" if verdict == "ACCEPT" else "reject"
        reason = "0x" + sha256(_canonical({
            "obligation_id": self.trial.obligation_id,
            "artifact_digest": artifact_digest,
            "verdict": verdict,
        })).hexdigest()
        receipt = self.helper.send("assigned_job.auditor_verdict", "evaluator",
                                   f"{decision}(uint256,bytes32,bytes)",
                                   self.job_id, reason, "0x",
                                   events=(("JobCompleted", "PaymentReleased") if verdict == "ACCEPT"
                                           else ("JobRejected", "Refunded")))
        after = self.helper.snapshot()
        job = self.helper.job(self.job_id)
        paid = verdict == "ACCEPT"
        if job["status"] != ("Completed" if paid else "Rejected"):
            raise NativeTrialError("native job status differs from auditor verdict")
        self.helper.assert_delta(before, after, **({
            "provider": BUDGET, "evaluator": 0,
            "treasury": 0, "escrow": -BUDGET,
        } if paid else {"client": BUDGET, "escrow": -BUDGET}))
        self.task_settlement = {
            "verdict": verdict, "artifact_digest": artifact_digest,
            "obligation_id": self.trial.obligation_id,
            "job_id": self.job_id, "job_status": job["status"],
            "provider_paid": paid,
            "provider_payout_minor_units": BUDGET if paid else 0,
            "before": before, "after": after,
            "transaction_hash": receipt["transactionHash"],
            "raw_receipt": receipt,
        }
        return self.task_settlement

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if self.process is not None and self.process.poll() is None:
                evidence = {
                    "schema": "w10-live-native-trial-v1",
                    "assignment_manifest_sha256": self.assignment_manifest_sha256,
                    "trial_id": self.trial.trial_id, "pair_id": self.trial.pair_id,
                    "obligation_id": self.trial.obligation_id,
                    "R": self.trial.r,
                    "source": {"erc8183_base_commit": PIN,
                               "mock_usdc_artifact_sha256": _sha256(
                                   UPSTREAM / "out" / "MockUSDC.sol" / "MockUSDC.json")},
                    "chain": {"rpc_host": "127.0.0.1", "port": self.port,
                              "chain_id": CHAIN_ID, "genesis_timestamp": GENESIS_TIMESTAMP},
                    "roles": self.helper.roles,
                    "contracts": self.helper.contracts,
                    "token_address": self.helper.token,
                    "core_address": self.helper.core,
                    "job_id": self.job_id,
                    "fee_before": self.fee_before,
                    "fee_after": self.fee_after,
                    "fee_transaction": self.fee_transaction,
                    "fee_receipt": self.fee_receipt,
                    "task_settlement": self.task_settlement,
                    "transactions": self.helper.transactions,
                    "model_behavior_tier": "SEPARATE_REMOTE_LOG",
                    "payment_tier": "NATIVE_LOCAL_ERC8183_PLUS_ERC20_FEE",
                    "fee_terms": {"prepaid_audit_fee_minor_units": FEE_MINOR_UNITS,
                                  "conditional_evaluator_fee_bps": 0,
                                  "platform_fee_bps": 0},
                    "exception_type": exc_type.__name__ if exc_type else None,
                    "limitations": [
                        "Direct ERC-20 audit fee has application-level obligation binding only.",
                        "ERC-8183 job settlement follows the auditor verdict; native contract does not judge artifact correctness.",
                        "All assets are valueless and localhost Anvil state is disposable.",
                    ],
                }
                target = self.output / "evidence.json"
                target.write_bytes(_canonical(evidence) + b"\n")
                self.native_evidence_sha256 = sha256(target.read_bytes()).hexdigest()
        finally:
            if self.process is not None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            if self.anvil_log is not None:
                self.anvil_log.close()
        return False


def sys_exc_info():
    import sys
    return sys.exc_info()
