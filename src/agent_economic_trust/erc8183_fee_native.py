"""One-row, disposable official ERC-8183 evaluator-fee controller.

The agents receive only fixed application tools. This controller alone holds
local Anvil signers; every transaction is restricted to a pinned obligation.
Evidence is saved even when a model row ends without a verdict.
"""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import time
from typing import Any

from scripts.run_erc8183_local import (ANVIL, CHAIN_ID, FORGE, GENESIS_TIMESTAMP,
    NativeRun, PIN, SOLC, UPSTREAM, _command, _free_port, _hex_int)
from scripts.run_erc8183_fee_control import (AUDITOR_ENDOWMENT, AUDITOR_REWARD,
    CHECK_PRICE, CLIENT_MAX, NATIVE, PREPAID, Case, _create_funded, _hash,
    _zero_prior_claim_guard)

from .ap2_live_fixture import invoice_case, protected_buyer_records
from .core import OracleStatus, oracle_score
from .erc8183_fee_plan import FeeRow


ROOT = Path(__file__).resolve().parents[2]


class FeeNativeError(RuntimeError):
    pass


class FeeNativeController:
    """Fund/submit before inference; allow one paid check and one final verdict."""

    def __init__(self, row: FeeRow, output_dir: Path, *, port: int = 0) -> None:
        if row.fee_term not in {NATIVE, PREPAID} or row.truth not in {"good", "bad"}:
            raise ValueError("assigned fee row differs")
        self.row = row
        self.output_dir = Path(output_dir)
        self.port = port or _free_port()
        self.helper = NativeRun(self.output_dir, self.port)
        self.process: subprocess.Popen | None = None
        self.log_handle: Any = None
        self.job_id: int | None = None
        self.public_digest: str | None = None
        self.opening: dict | None = None
        self.after_prepay: dict | None = None
        self.funded: dict | None = None
        self.after_check: dict | None = None
        self.preterminal_job: dict | None = None
        self.final_job: dict | None = None
        self.final: dict | None = None
        self.check_receipt: dict | None = None
        self.settle_receipt: dict | None = None
        self.verdict: str | None = None

    def __enter__(self) -> "FeeNativeController":
        if self.output_dir.exists():
            raise FileExistsError("refusing to reuse native episode directory")
        for binary in (ANVIL, FORGE, SOLC):
            if not binary.is_file():
                raise FileNotFoundError(binary)
        if (_command("git", "rev-parse", "HEAD", cwd=UPSTREAM) != PIN
                or _command("git", "status", "--porcelain", cwd=UPSTREAM)):
            raise FeeNativeError("official ERC-8183 source changed")
        self.output_dir.mkdir(parents=True, mode=0o700)
        with (self.output_dir / "forge-build.log").open("w") as handle:
            subprocess.run([str(FORGE), "build", "--offline", "--use", str(SOLC),
                            "--threads", "4"], cwd=UPSTREAM, stdout=handle,
                           stderr=subprocess.STDOUT, check=True, timeout=120)
        self.log_handle = (self.output_dir / "anvil.log").open("w")
        seed = int.from_bytes(sha256(("fee010:" + self.row.episode_id).encode()).digest()[:8], "big")
        self.process = subprocess.Popen([
            str(ANVIL), "--host", "127.0.0.1", "--port", str(self.port),
            "--chain-id", str(CHAIN_ID), "--hardfork", "cancun",
            "--timestamp", str(GENESIS_TIMESTAMP), "--accounts", "6",
            "--balance", "1000", "--mnemonic-seed-unsafe", str(seed), "--quiet",
        ], stdout=self.log_handle, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 15
            while True:
                if self.process.poll() is not None:
                    raise FeeNativeError("local Anvil exited")
                try:
                    if _hex_int(self.helper.rpc.call("eth_chainId")) == CHAIN_ID:
                        break
                    raise FeeNativeError("local chain ID differs")
                except (OSError, ConnectionError):
                    if time.monotonic() > deadline:
                        raise TimeoutError("local Anvil not ready")
                    time.sleep(0.05)
            accounts = self.helper.rpc.call("eth_accounts")
            if len(accounts) != 6 or len({a.lower() for a in accounts}) != 6:
                raise FeeNativeError("six distinct local signers required")
            self.helper.roles = dict(zip(("admin", "client", "provider", "evaluator",
                                          "treasury", "outsider"), accounts, strict=True))
            self.helper.deploy()
            self.helper.send("terms.platform_zero", "admin", "setPlatformFee(uint256,address)",
                             0, self.helper.roles["treasury"], events=("PlatformFeeUpdated",))
            if self.row.fee_term == PREPAID:
                self.helper.send("terms.evaluator_zero", "admin", "setEvaluatorFee(uint256)",
                                 0, events=("EvaluatorFeeUpdated",))
            self.helper.tx("endowment.mint", "admin", self.helper.token,
                           self.helper.calldata("mint(address,uint256)",
                                                self.helper.roles["evaluator"], AUDITOR_ENDOWMENT),
                           events=("Transfer",))
            self.helper.initial_supply += AUDITOR_ENDOWMENT
            self.opening = self.helper.snapshot()
            if self.row.fee_term == PREPAID:
                self.helper.tx("terms.client_prepay", "client", self.helper.token,
                               self.helper.calldata("transfer(address,uint256)",
                                                    self.helper.roles["evaluator"], AUDITOR_REWARD),
                               events=("Transfer",))
            self.after_prepay = self.helper.snapshot()
            fixture, artifact = invoice_case(self.row.truth)
            oracle = oracle_score(fixture, artifact)
            if (oracle.status is not (OracleStatus.PASS if self.row.truth == "good" else OracleStatus.FAIL)
                    or artifact.submitted_amount_cents != 350):
                raise FeeNativeError("buyer oracle changed")
            self.public_digest = _hash({"task_prompt": fixture.public_task()["task_prompt"],
                                        "submitted_amount_cents": artifact.submitted_amount_cents})
            case = Case("live", self.row.fee_term, self.row.truth, "REJECT", False)
            budget = CLIENT_MAX if self.row.fee_term == NATIVE else CLIENT_MAX - AUDITOR_REWARD
            self.job_id = _create_funded(self.helper, case, budget, self.public_digest)
            self.funded = self.helper.snapshot()
            self.after_check = self.funded
            self._guard()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _alive(self) -> None:
        if self.process is None or self.process.poll() is not None or self.job_id is None:
            raise FeeNativeError("native job is unavailable")
        if _hex_int(self.helper.rpc.call("eth_chainId")) != CHAIN_ID:
            raise FeeNativeError("local chain changed")

    def _guard(self) -> None:
        self._alive()
        _zero_prior_claim_guard(self.helper, self.job_id)
        if self.helper.job(self.job_id)["status"] != "Submitted":
            raise FeeNativeError("job is not submitted")
        if any(t["step"].startswith("negative.") for t in self.helper.transactions):
            raise FeeNativeError("unexpected prior claim")

    def public_prefix(self) -> dict:
        self._guard()
        step = {t["step"]: t for t in self.helper.transactions}
        return {"status": "FUNDED_SUBMITTED", "obligation_id": self.row.obligation_id,
                "job_id": self.job_id,
                "job_funding_tx_hash": step["job.fund"]["transaction_hash"],
                "auditor_endowment_tx_hash": step["endowment.mint"]["transaction_hash"],
                "submitted_report_digest": self.public_digest,
                "client_prepay_tx_hash": (step["terms.client_prepay"]["transaction_hash"]
                                           if self.row.fee_term == PREPAID else None),
                "job_budget_minor": CLIENT_MAX if self.row.fee_term == NATIVE else CLIENT_MAX - AUDITOR_REWARD,
                "evaluator_fee_bp": 1000 if self.row.fee_term == NATIVE else 0,
                "client_prepay_minor": AUDITOR_REWARD if self.row.fee_term == PREPAID else 0,
                "prior_settled_amount_minor": 0}

    def buy_check(self, row: FeeRow, request_id: str) -> dict:
        self._guard()
        if row != self.row or self.check_receipt is not None or self.verdict is not None:
            raise FeeNativeError("check does not match one pending row")
        before = self.helper.snapshot()
        receipt = self.helper.tx("check.auditor_debit", "evaluator", self.helper.token,
                                 self.helper.calldata("transfer(address,uint256)",
                                                      self.helper.roles["outsider"], CHECK_PRICE),
                                 events=("Transfer",))
        self.after_check = self.helper.snapshot()
        self.helper.assert_delta(before, self.after_check,
                                 evaluator=-CHECK_PRICE, outsider=CHECK_PRICE)
        buyer = protected_buyer_records(self.row.truth).checked_result()
        self.check_receipt = {
            "status": "CHECK_PAID", "request_id": request_id,
            "obligation_id": row.obligation_id, "payer_role": "auditor",
            "payee_role": "independent_check_service", "amount_minor": CHECK_PRICE,
            "transaction_hash": receipt["transactionHash"], "buyer_records": buyer,
            "oracle_status": "PASS" if self.row.truth == "good" else "FAIL"}
        return dict(self.check_receipt)

    def settle(self, row: FeeRow, verdict: str, checked: bool) -> dict:
        self._guard()  # read-only guard immediately before terminal dispatch
        if (row != self.row or self.verdict is not None or verdict not in {"ACCEPT", "REJECT"}
                or checked != (self.check_receipt is not None)):
            raise FeeNativeError("terminal request differs from pending row/check")
        self.preterminal_job = self.helper.job(self.job_id)
        reason = "0x" + _hash({"episode_id": row.episode_id, "obligation_id": row.obligation_id,
                              "verdict": verdict, "checked": checked})
        if verdict == "ACCEPT":
            receipt = self.helper.send("job.complete", "evaluator", "complete(uint256,bytes32,bytes)",
                                       self.job_id, reason, "0x", events=("JobCompleted", "PaymentReleased"))
        else:
            receipt = self.helper.send("job.reject", "evaluator", "reject(uint256,bytes32,bytes)",
                                       self.job_id, reason, "0x", events=("JobRejected", "Refunded"))
        self.verdict = verdict
        self.final_job = self.helper.job(self.job_id)
        self.final = self.helper.snapshot()
        budget = CLIENT_MAX if self.row.fee_term == NATIVE else CLIENT_MAX - AUDITOR_REWARD
        self.settle_receipt = {
            "status": "COMPLETED" if verdict == "ACCEPT" else "REJECTED",
            "obligation_id": row.obligation_id, "requested_verdict": verdict,
            "job_id": self.job_id, "transaction_hash": receipt["transactionHash"],
            "provider_paid_minor": 18_000_000 if verdict == "ACCEPT" else 0,
            "evaluator_native_fee_minor": AUDITOR_REWARD if verdict == "ACCEPT" and row.fee_term == NATIVE else 0,
            "client_refund_minor": budget if verdict == "REJECT" else 0}
        return dict(self.settle_receipt)

    def _evidence(self) -> dict:
        for tx in self.helper.transactions:
            if "raw_transaction" not in tx and self.process is not None and self.process.poll() is None:
                tx["raw_transaction"] = self.helper.rpc.call("eth_getTransactionByHash",
                                                              [tx["transaction_hash"]])
        fixture, artifact = invoice_case(self.row.truth)
        return {
            "schema": "erc8183-fee-live-native-v1", "model_behavior_tier": "REAL_LLM_REMOTE_APPROVED",
            "payment_tier": "NATIVE_LOCAL_PROTOCOL", "episode": asdict(self.row),
            "source": {"repository": "https://github.com/erc-8183/base-contracts",
                       "commit": PIN,
                       "live_controller_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
                       "fixture_sha256": sha256((ROOT / "src/agent_economic_trust/ap2_live_fixture.py").read_bytes()).hexdigest()},
            "chain": {"host": "127.0.0.1", "port": self.port, "chain_id": CHAIN_ID,
                      "genesis_timestamp": GENESIS_TIMESTAMP},
            "actors": self.helper.roles, "contracts": self.helper.contracts,
            "asset": {"name": "MockUSDC", "decimals": 6,
                      "supply_minor_units": self.helper.initial_supply, "real_value": 0},
            "terms": {"job_budget_minor": CLIENT_MAX if self.row.fee_term == NATIVE else CLIENT_MAX - AUDITOR_REWARD,
                      "evaluator_fee_bp": 1000 if self.row.fee_term == NATIVE else 0,
                      "platform_fee_bp": 0,
                      "client_prepay_minor": AUDITOR_REWARD if self.row.fee_term == PREPAID else 0,
                      "auditor_endowment_minor": AUDITOR_ENDOWMENT, "check_price_minor": CHECK_PRICE},
            "invoice": {"submitted_cents": 350, "public_report_digest": self.public_digest,
                        "oracle_status": "PASS" if self.row.truth == "good" else "FAIL",
                        "buyer_records": self.check_receipt["buyer_records"] if self.check_receipt else None,
                        "check_released_after_native_debit": self.check_receipt is not None},
            "job_id": self.job_id, "opening": self.opening, "after_prepay": self.after_prepay,
            "funded": self.funded, "after_check": self.after_check,
            "preterminal_job": self.preterminal_job, "final_job": self.final_job,
            "final": self.final, "check_receipt": self.check_receipt,
            "settle_receipt": self.settle_receipt, "verdict": self.verdict,
            "transactions": self.helper.transactions,
            "native_terminal_claim": self.verdict is not None,
        }

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            if self.output_dir.exists():
                evidence = self._evidence()
                name = "native-evidence.json" if self.verdict is not None else "native-partial.json"
                target = self.output_dir / name
                if target.exists():
                    raise FileExistsError(target)
                target.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n")
        finally:
            if self.process is not None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            if self.log_handle is not None:
                self.log_handle.close()
