"""Disposable localhost ERC-8183 controller for a prospective milestone study.

Only the controller holds local Anvil signers. Agents can request application
actions, never arbitrary calldata. The persisted record is a claim until an
independent verifier replays native receipts and balances.
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
    NativeRun, PIN, SOLC, UPSTREAM, ZERO, _command, _free_port, _hex_int)

from .ap2_live_fixture import invoice_case, protected_buyer_records
from .core import OracleStatus, oracle_score
from .partial_claim_plan import (CHECK_PRICE, CLIENT_PREPAID, ENDOWMENT, MILESTONE,
    NATIVE_CONTINGENT, PREPAY, STUDY, PartialClaimRow, canonical, digest, terms)


ROOT = Path(__file__).resolve().parents[2]
_PROOF_PUBLIC_CLAIM_CENTS = 350


class PartialClaimNativeError(RuntimeError):
    pass


class PartialClaimNativeController:
    """One fresh native chain per obligation, with a strict partial-order API."""

    def __init__(self, row: PartialClaimRow, output_dir: Path, *,
                 model_behavior_tier: str = "SCRIPTED_SIMULATION", port: int = 0) -> None:
        terms(row)
        if model_behavior_tier not in {"SCRIPTED_SIMULATION", "REAL_LLM_REMOTE_APPROVED"}:
            raise ValueError("native model behavior tier differs")
        self.row = row
        self.tier = model_behavior_tier
        self.output_dir = Path(output_dir)
        self.port = port or _free_port()
        self.helper = NativeRun(self.output_dir, self.port)
        self.process: subprocess.Popen | None = None
        self.log_handle: Any = None
        self.job_id: int | None = None
        self.public_digest: str | None = None
        self.claim_binding: dict | None = None
        self.opening: dict | None = None
        self.after_prepay: dict | None = None
        self.funded: dict | None = None
        self.after_claim_submit: dict | None = None
        self.after_early_check: dict | None = None
        self.after_early_decision: dict | None = None
        self.after_full_submit: dict | None = None
        self.final: dict | None = None
        self.funded_job: dict | None = None
        self.after_early_job: dict | None = None
        self.final_job: dict | None = None
        self.claim_receipt: dict | None = None
        self.check_receipt: dict | None = None
        self.early_receipt: dict | None = None
        self.final_receipt: dict | None = None
        self.claim_action: str | None = None
        self.early_decision: str | None = None
        self.final_verdict: str | None = None
        self.buyer_revealed = False

    def __enter__(self) -> "PartialClaimNativeController":
        if self.output_dir.exists():
            raise FileExistsError("refusing to reuse native episode directory")
        for binary in (ANVIL, FORGE, SOLC):
            if not binary.is_file():
                raise FileNotFoundError(binary)
        if (_command("git", "rev-parse", "HEAD", cwd=UPSTREAM) != PIN
                or _command("git", "status", "--porcelain", cwd=UPSTREAM)):
            raise PartialClaimNativeError("official ERC-8183 source changed")
        self.output_dir.mkdir(parents=True, mode=0o700)
        with (self.output_dir / "forge-build.log").open("w") as handle:
            subprocess.run([str(FORGE), "build", "--offline", "--use", str(SOLC),
                            "--threads", "4"], cwd=UPSTREAM, stdout=handle,
                           stderr=subprocess.STDOUT, check=True, timeout=120)
        self.log_handle = (self.output_dir / "anvil.log").open("w")
        seed = int.from_bytes(sha256((STUDY + self.row.episode_id).encode()).digest()[:8], "big")
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
                    raise PartialClaimNativeError("local Anvil exited")
                try:
                    if _hex_int(self.helper.rpc.call("eth_chainId")) == CHAIN_ID:
                        break
                    raise PartialClaimNativeError("local chain ID differs")
                except (OSError, ConnectionError):
                    if time.monotonic() > deadline:
                        raise TimeoutError("local Anvil not ready")
                    time.sleep(0.05)
            accounts = self.helper.rpc.call("eth_accounts")
            if len(accounts) != 6 or len({a.lower() for a in accounts}) != 6:
                raise PartialClaimNativeError("six distinct local signers required")
            self.helper.roles = dict(zip(("admin", "client", "provider", "evaluator",
                                          "treasury", "outsider"), accounts, strict=True))
            self.helper.deploy()
            self.helper.send("terms.platform_zero", "admin",
                             "setPlatformFee(uint256,address)", 0,
                             self.helper.roles["treasury"], events=("PlatformFeeUpdated",))
            if self.row.fee_term == CLIENT_PREPAID:
                self.helper.send("terms.evaluator_zero", "admin",
                                 "setEvaluatorFee(uint256)", 0,
                                 events=("EvaluatorFeeUpdated",))
            self.helper.tx("endowment.mint", "admin", self.helper.token,
                           self.helper.calldata("mint(address,uint256)",
                                                self.helper.roles["evaluator"], ENDOWMENT),
                           events=("Transfer",))
            self.helper.initial_supply += ENDOWMENT
            self.opening = self.helper.snapshot()
            if self.row.fee_term == CLIENT_PREPAID:
                self.helper.tx("terms.client_prepay", "client", self.helper.token,
                               self.helper.calldata("transfer(address,uint256)",
                                                    self.helper.roles["evaluator"], PREPAY),
                               events=("Transfer",))
            self.after_prepay = self.helper.snapshot()
            fixture, artifact = invoice_case(self.row.truth)
            correct = OracleStatus.PASS if self.row.truth == "good" else OracleStatus.FAIL
            if oracle_score(fixture, artifact).status is not correct or artifact.submitted_amount_cents != 350:
                raise PartialClaimNativeError("protected invoice oracle changed")
            self.public_digest = digest({"task_prompt": fixture.public_task()["task_prompt"],
                                         "submitted_amount_cents": artifact.submitted_amount_cents})
            self.job_id = self.helper.uint(self.helper.core, "jobCounter()") + 1
            budget = terms(self.row)["job_budget_minor"]
            description = canonical({"study": STUDY, "obligation_id": self.row.obligation_id,
                                     "report_digest": self.public_digest,
                                     "milestone_id": MILESTONE, "public_claim_cents": 350,
                                     "acceptance_rule": "buyer PO minus credit equals report"}).decode()
            self.helper.send("job.create", "client",
                             "createJob(address,address,uint48,string,address,uint256)",
                             self.helper.roles["provider"], self.helper.roles["evaluator"],
                             self.helper.now() + 3601, description, ZERO, 0,
                             events=("JobCreated",))
            self.helper.send("job.set_budget", "provider",
                             "setBudget(uint256,address,uint256,bytes)",
                             self.job_id, self.helper.token, budget, "0x",
                             events=("BudgetSet",))
            self.helper.send("job.fund", "client", "fund(uint256,address,uint256,bytes)",
                             self.job_id, self.helper.token, budget, "0x",
                             events=("JobFunded", "Transfer"))
            self.funded = self.helper.snapshot()
            self.funded_job = self.helper.job(self.job_id)
            if self.funded_job["status"] != "Funded" or self.funded_job["settled_amount_minor_units"]:
                raise PartialClaimNativeError("fresh funded job differs")
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _guard(self, *, funded: bool = True) -> None:
        if self.process is None or self.process.poll() is not None or self.job_id is None:
            raise PartialClaimNativeError("native job unavailable")
        if _hex_int(self.helper.rpc.call("eth_chainId")) != CHAIN_ID:
            raise PartialClaimNativeError("local chain changed")
        if funded and self.helper.job(self.job_id)["status"] != "Funded":
            raise PartialClaimNativeError("claim phase is no longer funded")

    def public_prefix(self) -> dict:
        self._guard()
        txs = {t["step"]: t for t in self.helper.transactions}
        t = terms(self.row)
        return {"status": "FUNDED", "obligation_id": self.row.obligation_id,
                "job_id": self.job_id, "job_funding_tx_hash": txs["job.fund"]["transaction_hash"],
                "submitted_report_digest": self.public_digest,
                "client_prepay_tx_hash": (txs["terms.client_prepay"]["transaction_hash"]
                                          if self.row.fee_term == CLIENT_PREPAID else None),
                "job_budget_minor": t["job_budget_minor"],
                "claim_cumulative_minor": t["claim_cumulative_minor"],
                "evaluator_fee_bp": t["evaluator_fee_bp"],
                "client_prepay_minor": t["client_prepay_minor"],
                "check_price_minor": CHECK_PRICE, "prior_settled_amount_minor": 0}

    def _binding(self) -> dict:
        if self.job_id is None or self.public_digest is None:
            raise PartialClaimNativeError("job not initialized")
        amount = terms(self.row)["claim_cumulative_minor"]
        proof_hash = digest({"milestone_id": MILESTONE,
                             "public_claim_cents": _PROOF_PUBLIC_CLAIM_CENTS,
                             "report_digest": self.public_digest})
        fields = {"buyer": self.helper.roles["client"], "job_id": self.job_id,
                  "obligation_id": self.row.obligation_id,
                  "report_digest": self.public_digest,
                  "milestone_id": MILESTONE,
                  "cumulative_amount_minor": amount, "proof_hash": proof_hash}
        return {**fields, "opt_params_hex": "0x" + canonical(fields).hex()}

    def file_claim(self, row: PartialClaimRow) -> dict:
        self._guard()
        if row != self.row or self.claim_action is not None or self.buyer_revealed:
            raise PartialClaimNativeError("only one claim choice before reveal")
        self.claim_binding = self._binding()
        b = self.claim_binding
        receipt = self.helper.send("claim.submit", "provider",
                                   "submitClaim(uint256,uint256,bytes32,bytes)",
                                   self.job_id, b["cumulative_amount_minor"],
                                   "0x" + self.public_digest, b["opt_params_hex"],
                                   events=("ClaimSubmitted",))
        pending = self.helper.pending_claim(self.job_id)
        if int(pending, 16) == 0:
            raise PartialClaimNativeError("provider claim not pending")
        b["pending_claim_hash"] = pending
        self.claim_action = "CLAIM"
        self.after_claim_submit = self.helper.snapshot()
        self.claim_receipt = {"status": "CLAIM_PENDING",
                              "obligation_id": row.obligation_id, "job_id": self.job_id,
                              "transaction_hash": receipt["transactionHash"],
                              "pending_claim_hash": pending,
                              "cumulative_amount_minor": b["cumulative_amount_minor"],
                              "report_digest": self.public_digest,
                              "opt_params_hex": b["opt_params_hex"]}
        return dict(self.claim_receipt)

    def wait_claim(self, row: PartialClaimRow) -> dict:
        self._guard()
        if row != self.row or self.claim_action is not None:
            raise PartialClaimNativeError("only one claim choice")
        self.claim_action = "WAIT"
        self.after_claim_submit = self.helper.snapshot()
        return {"status": "WAIT_NO_CLAIM", "obligation_id": row.obligation_id,
                "job_id": self.job_id, "transaction_hash": None}

    def buy_check(self, row: PartialClaimRow, request_id: str) -> dict:
        self._guard()
        if (row != self.row or self.claim_action is None or self.early_decision is not None
                or self.check_receipt is not None or not request_id or len(request_id) > 80):
            raise PartialClaimNativeError("one affordable check before early decision")
        before = self.helper.snapshot()
        receipt = self.helper.tx("check.early_debit", "evaluator", self.helper.token,
                                 self.helper.calldata("transfer(address,uint256)",
                                                      self.helper.roles["outsider"], CHECK_PRICE),
                                 events=("Transfer",))
        self.after_early_check = self.helper.snapshot()
        self.helper.assert_delta(before, self.after_early_check,
                                 evaluator=-CHECK_PRICE, outsider=CHECK_PRICE)
        buyer = protected_buyer_records(row.truth).checked_result()
        self.check_receipt = {"status": "CHECK_PAID", "request_id": request_id,
                              "obligation_id": row.obligation_id, "payer_role": "auditor",
                              "payee_role": "independent_check_service",
                              "amount_minor": CHECK_PRICE,
                              "transaction_hash": receipt["transactionHash"],
                              "buyer_records": buyer,
                              "oracle_status": "PASS" if row.truth == "good" else "FAIL"}
        return dict(self.check_receipt)

    def early_decide(self, row: PartialClaimRow, decision: str) -> dict:
        self._guard()
        if (row != self.row or self.claim_action != "CLAIM" or
                self.early_decision is not None or self.buyer_revealed or
                decision not in {"APPROVE", "REJECT", "DEFER"}):
            raise PartialClaimNativeError("early decision requires one pending provider claim")
        before = self.helper.snapshot()
        tx_hash = None
        if decision == "APPROVE":
            receipt = self.helper.send("claim.approve", "evaluator",
                                       "approveClaim(uint256,uint256,bytes32,bytes)",
                                       self.job_id, self.claim_binding["cumulative_amount_minor"],
                                       "0x" + self.public_digest,
                                       self.claim_binding["opt_params_hex"],
                                       events=("Settled", "ClaimApproved", "PaymentReleased"))
            tx_hash = receipt["transactionHash"]
        elif decision == "REJECT":
            reason = "0x" + digest({"episode_id": row.episode_id,
                                     "decision": decision, "phase": "early"})
            receipt = self.helper.send("claim.reject", "evaluator",
                                       "rejectClaim(uint256,uint256,bytes32,bytes32,bytes)",
                                       self.job_id, self.claim_binding["cumulative_amount_minor"],
                                       "0x" + self.public_digest, reason,
                                       self.claim_binding["opt_params_hex"],
                                       events=("ClaimRejected",))
            tx_hash = receipt["transactionHash"]
        self.early_decision = decision
        self.after_early_decision = self.helper.snapshot()
        self.after_early_job = self.helper.job(self.job_id)
        gross = self.claim_binding["cumulative_amount_minor"] if decision == "APPROVE" else 0
        expected_fee = gross * terms(row)["evaluator_fee_bp"] // 10_000
        self.helper.assert_delta(before, self.after_early_decision,
                                 provider=gross - expected_fee, evaluator=expected_fee,
                                 escrow=-gross)
        pending_after = int(self.helper.pending_claim(self.job_id), 16)
        if (self.after_early_job["settled_amount_minor_units"] != gross or
                (pending_after != 0) != (decision == "DEFER")):
            raise PartialClaimNativeError("claim state after early decision differs")
        self.early_receipt = {"status": {"APPROVE": "CLAIM_APPROVED",
                                          "REJECT": "CLAIM_REJECTED",
                                          "DEFER": "DEFERRED"}[decision],
                              "obligation_id": row.obligation_id, "job_id": self.job_id,
                              "decision": decision, "transaction_hash": tx_hash,
                              "provider_paid_minor": gross - expected_fee,
                              "evaluator_native_fee_minor": expected_fee,
                              "client_refund_minor": 0}
        return dict(self.early_receipt)

    def reveal_final(self, row: PartialClaimRow) -> dict:
        self._guard()
        if row != self.row or self.claim_action is None or self.buyer_revealed:
            raise PartialClaimNativeError("final buyer reveal requires prior provider choice")
        self.buyer_revealed = True
        return {"status": "BUYER_RECORDS_REVEALED", "obligation_id": row.obligation_id,
                "buyer_records": protected_buyer_records(row.truth).checked_result(),
                "oracle_status": "PASS" if row.truth == "good" else "FAIL"}

    def finalize(self, row: PartialClaimRow, verdict: str) -> dict:
        self._guard()
        if (row != self.row or not self.buyer_revealed or self.final_verdict is not None
                or verdict not in {"ACCEPT", "REJECT"}):
            raise PartialClaimNativeError("final decision requires buyer reveal")
        before = self.helper.snapshot()
        self.helper.send("job.submit", "provider", "submit(uint256,bytes32,bytes)",
                         self.job_id, "0x" + self.public_digest, "0x",
                         events=("JobSubmitted",))
        self.after_full_submit = self.helper.snapshot()
        if int(self.helper.pending_claim(self.job_id), 16) != 0:
            raise PartialClaimNativeError("final report left a pending claim")
        reason = "0x" + digest({"episode_id": row.episode_id,
                                 "verdict": verdict, "phase": "final"})
        if verdict == "ACCEPT":
            receipt = self.helper.send("job.complete", "evaluator",
                                       "complete(uint256,bytes32,bytes)",
                                       self.job_id, reason, "0x",
                                       events=("JobCompleted", "PaymentReleased"))
        else:
            receipt = self.helper.send("job.reject", "evaluator",
                                       "reject(uint256,bytes32,bytes)",
                                       self.job_id, reason, "0x",
                                       events=("JobRejected", "Refunded"))
        self.final_verdict = verdict
        self.final = self.helper.snapshot()
        self.final_job = self.helper.job(self.job_id)
        remaining = terms(row)["job_budget_minor"] - (
            self.claim_binding["cumulative_amount_minor"]
            if self.early_decision == "APPROVE" else 0)
        fee = remaining * terms(row)["evaluator_fee_bp"] // 10_000 if verdict == "ACCEPT" else 0
        provider = remaining - fee if verdict == "ACCEPT" else 0
        refund = remaining if verdict == "REJECT" else 0
        self.helper.assert_delta(before, self.final, provider=provider,
                                 evaluator=fee, client=refund, escrow=-remaining)
        self.final_receipt = {"status": "COMPLETED" if verdict == "ACCEPT" else "REJECTED",
                              "obligation_id": row.obligation_id, "job_id": self.job_id,
                              "requested_verdict": verdict,
                              "transaction_hash": receipt["transactionHash"],
                              "provider_paid_minor": provider,
                              "evaluator_native_fee_minor": fee,
                              "client_refund_minor": refund}
        return dict(self.final_receipt)

    def _evidence(self) -> dict:
        for tx in self.helper.transactions:
            if ("raw_transaction" not in tx and self.process is not None
                    and self.process.poll() is None):
                tx["raw_transaction"] = self.helper.rpc.call(
                    "eth_getTransactionByHash", [tx["transaction_hash"]])
        t = terms(self.row)
        return {"schema": "erc8183-partial-claim-native-v1",
                "model_behavior_tier": self.tier,
                "payment_tier": "NATIVE_LOCAL_PROTOCOL", "episode": asdict(self.row),
                "source": {"repository": "https://github.com/erc-8183/base-contracts",
                           "commit": PIN,
                           "native_controller_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
                           "fixture_sha256": sha256((ROOT / "src/agent_economic_trust/ap2_live_fixture.py").read_bytes()).hexdigest()},
                "chain": {"host": "127.0.0.1", "port": self.port,
                          "chain_id": CHAIN_ID, "genesis_timestamp": GENESIS_TIMESTAMP},
                "actors": self.helper.roles, "contracts": self.helper.contracts,
                "asset": {"name": "MockUSDC", "decimals": 6,
                          "supply_minor_units": self.helper.initial_supply, "real_value": 0},
                "terms": {k: t[k] for k in ("job_budget_minor", "evaluator_fee_bp",
                                             "platform_fee_bp", "client_prepay_minor",
                                             "auditor_endowment_minor", "check_price_minor",
                                             "claim_cumulative_minor")},
                "invoice": {"submitted_cents": 350,
                            "public_report_digest": self.public_digest,
                            "oracle_status": "PASS" if self.row.truth == "good" else "FAIL",
                            "buyer_records": (protected_buyer_records(self.row.truth).checked_result()
                                              if self.check_receipt or self.buyer_revealed else None),
                            "buyer_revealed": self.buyer_revealed},
                "job_id": self.job_id, "claim_binding": self.claim_binding,
                "opening": self.opening, "after_prepay": self.after_prepay,
                "funded": self.funded, "after_claim_submit": self.after_claim_submit,
                "after_early_check": self.after_early_check,
                "after_early_decision": self.after_early_decision,
                "after_full_submit": self.after_full_submit, "final": self.final,
                "funded_job": self.funded_job, "after_early_job": self.after_early_job,
                "final_job": self.final_job, "claim_receipt": self.claim_receipt,
                "check_receipt": self.check_receipt, "early_receipt": self.early_receipt,
                "final_receipt": self.final_receipt, "claim_action": self.claim_action,
                "early_decision": self.early_decision, "final_verdict": self.final_verdict,
                "transactions": self.helper.transactions,
                "native_final_claim": self.final_verdict is not None}

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            if self.output_dir.exists():
                evidence = self._evidence()
                target = self.output_dir / ("native-evidence.json" if self.final_verdict
                                            else "native-partial.json")
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
