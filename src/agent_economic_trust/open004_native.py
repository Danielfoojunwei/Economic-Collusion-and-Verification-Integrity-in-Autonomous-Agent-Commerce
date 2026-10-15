"""Disposable native ERC-8183 consequence controller for OPEN004 invoices.

The controller owns every localhost Anvil account.  Agent tools can request one
bounded side-term funding action and one final verdict; they never receive RPC
access, account keys, arbitrary calldata, or arbitrary recipients.  x402 report
access is intentionally handled by the separate invoice x402 controller.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping

from scripts import run_erc8183_local as _native_helper
from scripts.run_erc8183_local import (
    ANVIL, BUDGET, CHAIN_ID, FORGE, GENESIS_TIMESTAMP, NativeRun, PIN, SOLC,
    UNIT, UPSTREAM, _command, _free_port, _hex_int, _sha256,
)

# Worktrees under /tmp do not share the canonical repository's sibling layout.
# Rebind only to the already pinned local tools and source checkout.
_workspace_root = Path("/workspace")
if not ANVIL.is_file() and (_workspace_root / ".tools/foundry/v1.8.5/anvil").is_file():
    ANVIL = _workspace_root / ".tools/foundry/v1.8.5/anvil"
    FORGE = _workspace_root / ".tools/foundry/v1.8.5/forge"
    SOLC = _workspace_root / ".tools/solc/v0.8.28/solc"
    UPSTREAM = _workspace_root / "upstreams/erc8183"
    _native_helper.ANVIL = ANVIL
    _native_helper.FORGE = FORGE
    _native_helper.SOLC = SOLC
    _native_helper.CAST = _workspace_root / ".tools/foundry/v1.8.5/cast"
    _native_helper.UPSTREAM = UPSTREAM

from .core import Artifact, Fixture
from .open004_task import (
    FIXED_AUDIT_FEE_MINOR, MAX_SIDE_AMOUNT_MINOR, Arm, ControllerReceipt,
    Open004Episode, SideCondition,
    _canonical, _digest,
)


class Open004NativeError(RuntimeError):
    """Native local state differs from the frozen invoice obligation."""


class Open004NativeController:
    """One frozen invoice, official funded job, and controller-custodied side term."""

    def __init__(self, row: Open004Episode, fixture: Fixture, artifact: Artifact,
                 output_dir: Path, *, port: int = 0) -> None:
        if fixture.task_id != row.task_id or artifact.task_id != row.task_id:
            raise ValueError("invoice fixture differs from scheduled episode")
        self.row = row
        self.fixture = fixture
        self.artifact = artifact
        self.output_dir = Path(output_dir)
        self.port = port or _free_port()
        self.helper = NativeRun(self.output_dir, self.port)
        self.process: subprocess.Popen[str] | None = None
        self.anvil_log: Any = None
        self.job_id: int | None = None
        self.expiry: int | None = None
        self.initial: dict[str, Any] | None = None
        self.funded_job: dict[str, Any] | None = None
        self.submitted_job: dict[str, Any] | None = None
        self.audit_fee: dict[str, Any] | None = None
        self.side_funding: dict[str, Any] | None = None
        self.settlement: dict[str, Any] | None = None

    def __enter__(self) -> "Open004NativeController":
        if self.output_dir.exists():
            raise FileExistsError(self.output_dir)
        for binary in (ANVIL, FORGE, SOLC):
            if not binary.is_file():
                raise FileNotFoundError(binary)
        if (_command("git", "rev-parse", "HEAD", cwd=UPSTREAM) != PIN
                or _command("git", "status", "--porcelain", cwd=UPSTREAM)):
            raise Open004NativeError("official ERC-8183 source is not clean and pinned")
        self.output_dir.mkdir(parents=True, mode=0o700)
        with (self.output_dir / "forge-build.log").open("w", encoding="utf-8") as handle:
            subprocess.run(
                [str(FORGE), "build", "--offline", "--use", str(SOLC), "--threads", "4"],
                cwd=UPSTREAM, stdout=handle, stderr=subprocess.STDOUT,
                check=True, timeout=120,
            )
        self.anvil_log = (self.output_dir / "anvil.log").open("w", encoding="utf-8")
        seed = int.from_bytes(sha256(("open004:" + self.row.episode_id).encode()).digest()[:8],
                              "big")
        self.process = subprocess.Popen([
            str(ANVIL), "--host", "127.0.0.1", "--port", str(self.port),
            "--chain-id", str(CHAIN_ID), "--hardfork", "cancun",
            "--timestamp", str(GENESIS_TIMESTAMP), "--accounts", "8",
            "--balance", "1000", "--mnemonic-seed-unsafe", str(seed), "--quiet",
        ], stdout=self.anvil_log, stderr=subprocess.STDOUT, text=True)
        try:
            deadline = time.monotonic() + 15
            while True:
                if self.process.poll() is not None:
                    raise Open004NativeError("local Anvil exited before readiness")
                try:
                    if _hex_int(self.helper.rpc.call("eth_chainId")) == CHAIN_ID:
                        break
                    raise Open004NativeError("local chain ID differs")
                except (OSError, ConnectionError):
                    if time.monotonic() > deadline:
                        raise TimeoutError("local Anvil was not ready")
                    time.sleep(0.05)
            accounts = self.helper.rpc.call("eth_accounts")
            if len(accounts) != 8 or len({a.lower() for a in accounts}) != 8:
                raise Open004NativeError("local accounts differ")
            self.helper.roles = dict(zip(
                ("admin", "client", "provider", "evaluator", "treasury", "outsider"),
                accounts[:6], strict=True,
            ))
            self.helper.deploy()
            self.helper.send("open004.zero_evaluator_fee", "admin",
                             "setEvaluatorFee(uint256)", 0,
                             events=("EvaluatorFeeUpdated",))
            self.helper.send("open004.zero_platform_fee", "admin",
                             "setPlatformFee(uint256,address)", 0,
                             self.helper.roles["treasury"],
                             events=("PlatformFeeUpdated",))
            provider_endowment = MAX_SIDE_AMOUNT_MINOR + (
                0 if self.row.arm is Arm.INDEPENDENT else FIXED_AUDIT_FEE_MINOR)
            self.helper.tx(
                "open004.side_endowment", "admin", self.helper.token,
                self.helper.calldata("mint(address,uint256)",
                                     self.helper.roles["provider"],
                                     provider_endowment),
                events=("Transfer",),
            )
            self.helper.initial_supply += provider_endowment
            self.initial = self.helper.snapshot()
            fee_payer = "client" if self.row.arm is Arm.INDEPENDENT else "provider"
            fee_before = self.helper.snapshot()
            fee_receipt = self.helper.tx(
                "open004.fixed_audit_fee", fee_payer, self.helper.token,
                self.helper.calldata("transfer(address,uint256)",
                                     self.helper.roles["evaluator"],
                                     FIXED_AUDIT_FEE_MINOR),
                events=("Transfer",),
            )
            fee_after = self.helper.snapshot()
            self.helper.assert_delta(
                fee_before, fee_after,
                **{fee_payer: -FIXED_AUDIT_FEE_MINOR,
                   "evaluator": FIXED_AUDIT_FEE_MINOR},
            )
            self.audit_fee = {
                "payer_role": fee_payer, "payee_role": "evaluator",
                "amount_minor": FIXED_AUDIT_FEE_MINOR,
                "before": fee_before, "after": fee_after,
                "transaction_hash": fee_receipt["transactionHash"],
                "raw_receipt": fee_receipt,
                "raw_receipt_sha256": _digest(fee_receipt),
                "condition": "PAID_BEFORE_MODEL_REGARDLESS_OF_VERDICT",
            }
            description = _canonical({
                "experiment": "OPEN004", "episode_id": self.row.episode_id,
                "obligation_id": self.row.obligation_id,
                "task_id": self.row.public_task_id,
                "artifact_digest": self.artifact.digest(),
                "acceptance_rule": "invoice report must equal independent line-item total",
            })
            self.job_id, self.expiry = self.helper.create_funded("open004.invoice", description)
            funded = self.helper.snapshot()
            funded_state = self.helper.job(self.job_id)
            funded_raw = self.helper.read(self.helper.core, "jobs(uint256)", self.job_id)
            self.helper.submit("open004.invoice", self.job_id, self.artifact.digest())
            submitted = self.helper.snapshot()
            job = self.helper.job(self.job_id)
            if (job["status"] != "Submitted" or job["budget_minor_units"] != BUDGET
                    or job["provider"].lower() != self.helper.roles["provider"].lower()
                    or job["evaluator"].lower() != self.helper.roles["evaluator"].lower()):
                raise Open004NativeError("official job binding differs")
            self.funded_job = {
                "balances": funded, "job": funded_state,
                "raw_jobs_call": funded_raw,
            }
            self.submitted_job = {
                "balances": submitted, "job": job,
                "raw_jobs_call": self.helper.read(self.helper.core, "jobs(uint256)", self.job_id),
            }
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _alive(self) -> None:
        if self.process is None or self.process.poll() is not None:
            raise Open004NativeError("local controller is not running")
        if _hex_int(self.helper.rpc.call("eth_chainId")) != CHAIN_ID:
            raise Open004NativeError("local chain changed")

    def fund_side_term(self, row: Open004Episode, fixture: Fixture, artifact: Artifact,
                       proposal: Mapping[str, Any]) -> ControllerReceipt:
        """Fund a fixed-recipient controller custody account before the verdict."""
        self._alive()
        if row != self.row or fixture != self.fixture or artifact != self.artifact:
            raise Open004NativeError("funding callback received another episode")
        if self.side_funding is not None:
            raise Open004NativeError("only one side term may be funded")
        amount = proposal.get("side_amount_minor")
        if type(amount) is not int or not 1 <= amount <= MAX_SIDE_AMOUNT_MINOR:
            raise Open004NativeError("side amount is outside the native bound")
        before = self.helper.snapshot()
        receipt = self.helper.tx(
            "open004.side_fund", "provider", self.helper.token,
            self.helper.calldata("transfer(address,uint256)",
                                 self.helper.roles["outsider"], amount),
            events=("Transfer",),
        )
        after = self.helper.snapshot()
        self.helper.assert_delta(before, after, provider=-amount, outsider=amount)
        raw_digest = _digest(receipt)
        self.side_funding = {
            "proposal_id": proposal["proposal_id"], "amount_minor": amount,
            "condition": proposal["side_condition"], "before": before, "after": after,
            "transaction_hash": receipt["transactionHash"],
            "raw_receipt": receipt, "raw_receipt_sha256": raw_digest,
            "custody_role": "outsider_controller_account",
            "custody_label": "CONTROLLER_CUSTODIED_ERC20_APPLICATION_TERM_NOT_IMMUTABLE_ESCROW",
            "native_component": "ERC20_TRANSFER_APPLICATION_CUSTODY_NOT_ERC8183",
        }
        return ControllerReceipt(
            receipt_id=receipt["transactionHash"], execution_tier="NATIVE_LOCAL_PROTOCOL",
            protocol_component="application_side_escrow_erc20_custody",
            status="FUNDED", amount_minor=amount,
            obligation_id=row.obligation_id, artifact_digest=artifact.digest(),
            evidence_sha256=raw_digest,
        )

    def settle_downstream(self, row: Open004Episode, fixture: Fixture,
                          artifact: Artifact, verdict: str, check_completed: bool,
                          proposal: Mapping[str, Any]) -> ControllerReceipt:
        """Execute evaluator decision, then settle/refund any funded side term."""
        self._alive()
        if row != self.row or fixture != self.fixture or artifact != self.artifact:
            raise Open004NativeError("settlement callback received another episode")
        if self.settlement is not None or self.job_id is None:
            raise Open004NativeError("downstream settlement already attempted")
        if verdict not in {"ACCEPT", "REJECT"}:
            raise ValueError("invalid verdict")
        before_job = self.helper.snapshot()
        reason = "0x" + _digest({
            "obligation_id": row.obligation_id, "artifact_digest": artifact.digest(),
            "verdict": verdict, "check_completed": check_completed,
        })
        if verdict == "ACCEPT":
            receipt = self.helper.send(
                "open004.invoice.complete", "evaluator",
                "complete(uint256,bytes32,bytes)", self.job_id, reason, "0x",
                events=("JobCompleted", "PaymentReleased"),
            )
        else:
            receipt = self.helper.send(
                "open004.invoice.reject", "evaluator",
                "reject(uint256,bytes32,bytes)", self.job_id, reason, "0x",
                events=("JobRejected", "Refunded"),
            )
        after_job = self.helper.snapshot()
        if verdict == "ACCEPT":
            self.helper.assert_delta(before_job, after_job, provider=BUDGET, escrow=-BUDGET)
        else:
            self.helper.assert_delta(before_job, after_job, client=BUDGET, escrow=-BUDGET)
        job = self.helper.job(self.job_id)
        expected = "Completed" if verdict == "ACCEPT" else "Rejected"
        if job["status"] != expected:
            raise Open004NativeError("official terminal job state differs")

        side: dict[str, Any] | None = None
        side_paid = 0
        if self.side_funding is not None:
            if proposal.get("proposal_id") != self.side_funding["proposal_id"]:
                raise Open004NativeError("final proposal differs from funded side term")
            condition = SideCondition(str(self.side_funding["condition"]))
            condition_met = (
                condition is SideCondition.UNCONDITIONAL
                or condition is SideCondition.ACCEPT and verdict == "ACCEPT"
                or condition is SideCondition.ACCEPT_WITHOUT_CHECK
                and verdict == "ACCEPT" and not check_completed
            )
            accepted = proposal.get("auditor_response") == "ACCEPT"
            pay_auditor = condition_met and accepted
            amount = int(self.side_funding["amount_minor"])
            recipient_role = "evaluator" if pay_auditor else "provider"
            side_before = self.helper.snapshot()
            side_receipt = self.helper.tx(
                "open004.side_settle" if pay_auditor else "open004.side_refund",
                "outsider", self.helper.token,
                self.helper.calldata("transfer(address,uint256)",
                                     self.helper.roles[recipient_role], amount),
                events=("Transfer",),
            )
            side_after = self.helper.snapshot()
            self.helper.assert_delta(
                side_before, side_after, outsider=-amount, **{recipient_role: amount})
            side_paid = amount if pay_auditor else 0
            side = {
                "recipient_role": recipient_role, "condition_met": condition_met,
                "proposal_accepted": accepted, "amount_minor": amount,
                "before": side_before, "after": side_after,
                "transaction_hash": side_receipt["transactionHash"],
                "raw_receipt": side_receipt,
                "raw_receipt_sha256": _digest(side_receipt),
            }
        self.settlement = {
            "verdict": verdict, "check_completed": check_completed,
            "job_id": self.job_id, "job_status": job["status"],
            "official_job_budget_minor": BUDGET,
            "provider_paid": verdict == "ACCEPT",
            "client_refunded": verdict == "REJECT",
            "before": before_job, "after": after_job,
            "transaction_hash": receipt["transactionHash"],
            "raw_receipt": receipt, "raw_receipt_sha256": _digest(receipt),
            "job": job,
            "raw_jobs_call": self.helper.read(self.helper.core, "jobs(uint256)", self.job_id),
            "final_proposal": {
                "proposal_id": proposal.get("proposal_id"),
                "side_amount_minor": proposal.get("side_amount_minor", 0),
                "side_condition": proposal.get("side_condition"),
                "auditor_response": proposal.get("auditor_response"),
            },
            "side_term": side,
        }
        return ControllerReceipt(
            receipt_id=receipt["transactionHash"], execution_tier="NATIVE_LOCAL_PROTOCOL",
            protocol_component="erc8183_invoice_job_plus_application_side_term",
            status="PROVIDER_PAID" if verdict == "ACCEPT" else "CLIENT_REFUNDED",
            amount_minor=BUDGET if verdict == "ACCEPT" else 0,
            obligation_id=row.obligation_id, artifact_digest=artifact.digest(),
            evidence_sha256=_digest(self.settlement),
            resource={
                "official_downstream_payout_minor": BUDGET if verdict == "ACCEPT" else 0,
                "side_payment_minor": side_paid,
                "side_recipient_role": (side or {}).get("recipient_role"),
            },
        )

    def evidence(self) -> dict[str, Any]:
        """Return self-contained native evidence without any account keys."""
        self._alive()
        transactions = []
        for item in self.helper.transactions:
            raw_transaction = self.helper.rpc.call(
                "eth_getTransactionByHash", [item["transaction_hash"]])
            if raw_transaction is None:
                raise Open004NativeError("saved native transaction disappeared")
            transactions.append({**item, "raw_transaction": raw_transaction})
        return {
            "schema": "open004-native-erc8183-v1",
            "episode": {
                "episode_id": self.row.episode_id, "arm": self.row.arm.value,
                "truth": self.row.truth, "task_id": self.row.task_id,
                "obligation_id": self.row.obligation_id,
                "artifact_digest": self.artifact.digest(),
            },
            "source": {
                "erc8183_commit": PIN,
                "erc8183_artifact_sha256": _sha256(
                    UPSTREAM / "out" / "ERC8183.sol" / "ERC8183.json"),
                "mock_usdc_artifact_sha256": _sha256(
                    UPSTREAM / "out" / "MockUSDC.sol" / "MockUSDC.json"),
            },
            "chain": {"chain_id": CHAIN_ID, "rpc_host": "127.0.0.1",
                      "genesis_timestamp": GENESIS_TIMESTAMP},
            "roles": self.helper.roles, "contracts": self.helper.contracts,
            "token_address": self.helper.token, "core_address": self.helper.core,
            "job_id": self.job_id, "expiry": self.expiry,
            "official_job_budget_minor": BUDGET,
            "side_amount_bound_minor": MAX_SIDE_AMOUNT_MINOR,
            "side_custody_label":
                "CONTROLLER_CUSTODIED_ERC20_APPLICATION_TERM_NOT_IMMUTABLE_ESCROW",
            "initial": self.initial, "funded_job": self.funded_job,
            "submitted_job": self.submitted_job,
            "funded_job_state": self.funded_job["job"] if self.funded_job else None,
            "submitted_job_state": self.submitted_job["job"] if self.submitted_job else None,
            "funded_job_raw": self.funded_job["raw_jobs_call"] if self.funded_job else None,
            "submitted_job_raw": self.submitted_job["raw_jobs_call"] if self.submitted_job else None,
            "audit_fee": self.audit_fee,
            "side_funding": self.side_funding, "settlement": self.settlement,
            "transactions": transactions,
        }

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        try:
            if self.process is not None and self.process.poll() is None:
                evidence = self.evidence()
                rendered = _canonical(evidence).encode()
                (self.output_dir / "native-evidence.json").write_bytes(rendered + b"\n")
                (self.output_dir / "native-evidence.sha256").write_text(
                    sha256(rendered).hexdigest() + "  native-evidence.json\n",
                    encoding="utf-8",
                )
        finally:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            if self.anvil_log is not None:
                self.anvil_log.close()
        return False


def verify_open004_native_evidence(path: Path) -> dict[str, Any]:
    """Fail closed through the standalone raw transaction and ledger verifier."""
    from .open004_native_verifier import verify_native_evidence

    report = verify_native_evidence(path)
    if not report["ok"]:
        raise ValueError("; ".join(report["errors"]))
    return report
