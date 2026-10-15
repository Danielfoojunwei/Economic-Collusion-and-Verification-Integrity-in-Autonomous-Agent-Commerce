"""Separate official local ERC-8183 invoice job for x402 intake controls.

The x402 HTTP transfer pays for intake on its own disposable chain. This job
uses another disposable local chain and pays the provider only after evaluator
ACCEPT. Neither protocol object certifies the invoice itself.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time

from scripts.run_erc8183_local import (
    ANVIL, BUDGET, CHAIN_ID, FORGE, GENESIS_TIMESTAMP, NativeRun,
    PIN, SOLC, UPSTREAM, _command, _hex_int,
)

from .ap2_live_fixture import invoice_case
from .core import oracle_score
from .x402_audit_retainer import RetainerAssignment, digest


class RetainerJob:
    """One pre-funded official job with zero protocol evaluator/platform fees."""

    def __init__(self, row: RetainerAssignment, output: Path, *, port: int):
        row.validate()
        self.row, self.output, self.port = row, Path(output), port
        self.helper = NativeRun(self.output, port)
        self.process = None
        self.log = None
        self.job_id = None
        self.initial = None
        self.funded = None
        self.submitted = None
        self.settlement = None

    def __enter__(self):
        if self.output.exists():
            raise FileExistsError(self.output)
        if any(not binary.is_file() for binary in (ANVIL, FORGE, SOLC)):
            raise FileNotFoundError("pinned native toolchain unavailable")
        if (_command("git", "rev-parse", "HEAD", cwd=UPSTREAM) != PIN
                or _command("git", "status", "--porcelain", cwd=UPSTREAM)):
            raise RuntimeError("official ERC-8183 checkout is not clean and pinned")
        self.output.mkdir(parents=True)
        with (self.output / "forge-build.log").open("w") as stream:
            subprocess.run([str(FORGE), "build", "--offline", "--use", str(SOLC),
                            "--threads", "4"], cwd=UPSTREAM, stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=120)
        self.log = (self.output / "anvil.log").open("w")
        # Same test identities as the x402 chain, distinct disposable state.
        mnemonic = "test test test test test test test test test test test junk"
        self.process = subprocess.Popen([
            str(ANVIL), "--host", "127.0.0.1", "--port", str(self.port),
            "--chain-id", str(CHAIN_ID), "--hardfork", "cancun",
            "--timestamp", str(GENESIS_TIMESTAMP), "--accounts", "8",
            "--balance", "1000", "--mnemonic", mnemonic, "--quiet",
        ], stdout=self.log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 15
            while True:
                if self.process.poll() is not None:
                    raise RuntimeError("local ERC-8183 chain exited")
                try:
                    if _hex_int(self.helper.rpc.call("eth_chainId")) == CHAIN_ID:
                        break
                    raise RuntimeError("local ERC-8183 chain ID changed")
                except (ConnectionError, OSError):
                    if time.monotonic() > deadline:
                        raise TimeoutError("local ERC-8183 chain did not start")
                    time.sleep(.05)
            accounts = self.helper.rpc.call("eth_accounts")
            if len(accounts) != 8 or len(set(map(str.lower, accounts))) != 8:
                raise RuntimeError("local native accounts differ")
            self.helper.roles = dict(zip(("admin", "client", "provider", "evaluator",
                                          "treasury", "outsider"), accounts[:6], strict=True))
            self.helper.deploy()
            self.helper.send("x402job.zero_evaluator_fee", "admin", "setEvaluatorFee(uint256)",
                             0, events=("EvaluatorFeeUpdated",))
            self.helper.send("x402job.zero_platform_fee", "admin",
                             "setPlatformFee(uint256,address)", 0,
                             self.helper.roles["treasury"], events=("PlatformFeeUpdated",))
            if (self.helper.uint(self.helper.core, "evaluatorFeeBP()") != 0
                    or self.helper.uint(self.helper.core, "platformFeeBP()") != 0):
                raise RuntimeError("official job has nonzero protocol fees")
            self.initial = self.helper.snapshot()
            fixture, artifact = invoice_case(self.row.truth)
            description = json.dumps({
                "study": "X402_AUDIT_RETAINER_010", "obligation_id": self.row.obligation_id,
                "artifact_digest": artifact.digest(),
                "rule": "release iff independent invoice total matches report",
            }, sort_keys=True, separators=(",", ":"))
            self.job_id, _ = self.helper.create_funded("x402job", description)
            self.funded = self.helper.snapshot()
            self.helper.submit("x402job", self.job_id, artifact.digest())
            self.submitted = self.helper.snapshot()
            job = self.helper.job(self.job_id)
            if (job["status"] != "Submitted" or job["budget_minor_units"] != BUDGET
                    or job["evaluator"].lower() != self.helper.roles["evaluator"].lower()):
                raise RuntimeError("official job did not fund/submit as assigned")
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def decide(self, verdict: str, *, check_completed: bool) -> dict:
        if self.process is None or self.process.poll() is not None or self.settlement is not None:
            raise RuntimeError("official job is absent or terminal")
        if verdict not in {"ACCEPT", "REJECT"} or type(check_completed) is not bool:
            raise ValueError("invalid scripted verdict or check state")
        fixture, artifact = invoice_case(self.row.truth)
        oracle = oracle_score(fixture, artifact)
        before = self.helper.snapshot()
        reason = "0x" + digest({"obligation_id": self.row.obligation_id,
                               "artifact_digest": artifact.digest(),
                               "verdict": verdict, "check_completed": check_completed})
        if verdict == "ACCEPT":
            receipt = self.helper.send("x402job.complete", "evaluator",
                                       "complete(uint256,bytes32,bytes)", self.job_id,
                                       reason, "0x", events=("JobCompleted", "PaymentReleased"))
        else:
            receipt = self.helper.send("x402job.reject", "evaluator",
                                       "reject(uint256,bytes32,bytes)", self.job_id,
                                       reason, "0x", events=("JobRejected", "Refunded"))
        after = self.helper.snapshot()
        if verdict == "ACCEPT":
            self.helper.assert_delta(before, after, provider=BUDGET, escrow=-BUDGET)
        else:
            self.helper.assert_delta(before, after, client=BUDGET, escrow=-BUDGET)
        job = self.helper.job(self.job_id)
        if job["status"] != ("Completed" if verdict == "ACCEPT" else "Rejected"):
            raise RuntimeError("official job terminal state differs from verdict")
        self.settlement = {
            "verdict": verdict, "check_completed": check_completed,
            "oracle_status": oracle.status.value, "oracle_reason_code": oracle.reason_code,
            "job_id": self.job_id, "job": job,
            "before": before, "after": after,
            "transaction_hash": receipt["transactionHash"], "raw_receipt": receipt,
            "provider_paid": verdict == "ACCEPT", "client_refunded": verdict == "REJECT",
            "wrongful_provider_payout": verdict == "ACCEPT" and oracle.status.value == "FAIL",
        }
        return self.settlement

    def save(self) -> Path:
        if self.settlement is None:
            raise RuntimeError("official job has no final decision")
        fixture, artifact = invoice_case(self.row.truth)
        result = {
            "schema": "x402-retainer-separate-erc8183-job-v1",
            "model_tier": "SCRIPTED_SIMULATION", "transaction_tier": "NATIVE_LOCAL_PROTOCOL",
            "assignment": vars(self.row), "erc8183_commit": PIN,
            "obligation_id": self.row.obligation_id, "artifact_digest": artifact.digest(),
            "oracle_status": oracle_score(fixture, artifact).status.value,
            "chain_id": CHAIN_ID, "rpc_port": self.port,
            "roles": self.helper.roles, "contracts": self.helper.contracts,
            "initial": self.initial, "funded": self.funded,
            "submitted": self.submitted, "settlement": self.settlement,
            "transactions": self.helper.transactions,
            "raw_transactions": {
                item["step"]: self.helper.rpc.call(
                    "eth_getTransactionByHash", [item["transaction_hash"]])
                for item in self.helper.transactions
            },
        }
        path = self.output / "native-job.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return path

    def __exit__(self, _type, _value, _traceback):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log is not None:
            self.log.close()
