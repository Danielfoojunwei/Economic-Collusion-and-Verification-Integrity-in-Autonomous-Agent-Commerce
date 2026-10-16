"""Controller-owned, valueless local x402 retainer and ERC-8183 job for 012.

The chains are separate. The ERC-8183 chain mints a bounded auditor check
endowment; no cross-chain funding or PSP capture is claimed.
"""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

from scripts.run_erc8183_local import BUDGET, CHAIN_ID, PIN, _free_port

from .ap2_live_fixture import protected_buyer_records
from .x402_audit_retainer import RetainerAssignment, run_native_intake
from .x402_audit_retainer_verifier import verify_intake
from .x402_live012_plan import X402LiveRow
from .x402_live012_task import (AUDITOR_CHECK_ENDOWMENT_MINOR,
                                CHECK_PRICE_MINOR)
from .x402_retainer_job import RetainerJob
from .x402_retainer_job_verifier import verify_job


class X402LiveNative:
    """One-use native controller whose keys stay outside both model contexts."""

    def __init__(self, row: X402LiveRow, output: Path, *,
                 x402_port: int = 19801, erc8183_port: int = 0,
                 model_tier: str = "REAL_LLM_REMOTE_APPROVED"):
        if model_tier not in {"SCRIPTED_SIMULATION", "REAL_LLM_REMOTE_APPROVED"}:
            raise ValueError("model behavior tier differs")
        self.row, self.output = row, Path(output)
        self.model_tier = model_tier
        self.assignment = RetainerAssignment(row.episode_id, row.obligation_id,
                                             row.truth, row.payer_role)
        self.x402_port = x402_port
        self.job = RetainerJob(self.assignment, self.output / "erc8183-job",
                               port=erc8183_port or _free_port(),
                               model_tier=model_tier,
                               study_id="X402_AUDIT_RETAINER_012")
        self.retainer: dict | None = None
        self.check: dict | None = None
        self.endowment: dict | None = None
        self.settlement: dict | None = None
        self.partial_journal_error: str | None = None
        self._entered = False

    def __enter__(self) -> "X402LiveNative":
        if self.output.exists():
            raise FileExistsError("native episode directory already exists")
        self.output.mkdir(parents=True, mode=0o700)
        try:
            self.job.__enter__()
            helper = self.job.helper
            before = helper.snapshot()
            mint = helper.tx("x402live012.check_endowment", "admin", helper.token,
                             helper.calldata("mint(address,uint256)",
                                             helper.roles["evaluator"],
                                             AUDITOR_CHECK_ENDOWMENT_MINOR),
                             events=("Transfer",))
            helper.initial_supply += AUDITOR_CHECK_ENDOWMENT_MINOR
            after = helper.snapshot()
            helper.assert_delta(before, after, evaluator=AUDITOR_CHECK_ENDOWMENT_MINOR)
            self.endowment = {"before": before, "after": after,
                              "transaction_hash": mint["transactionHash"]}
            self.retainer = run_native_intake(self.assignment,
                                              self.output / "x402-intake",
                                              port=self.x402_port)
            verified = verify_intake(self.output / "x402-intake", self.assignment)
            if (verified["status"] != "PASS" or not verified["protocol_settled"]
                    or verified["transaction_hash"] != self.retainer["transaction_hash"]):
                raise RuntimeError("pre-audit x402 intake did not independently settle")
            self._entered = True
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def buy_check(self, row: X402LiveRow, request_id: str) -> dict:
        if (not self._entered or row != self.row or self.check is not None
                or self.settlement is not None or not request_id):
            raise RuntimeError("one pending assigned check required")
        helper = self.job.helper
        before = helper.snapshot()
        tx = helper.tx("x402live012.auditor_check_debit", "evaluator", helper.token,
                       helper.calldata("transfer(address,uint256)",
                                       helper.roles["outsider"], CHECK_PRICE_MINOR),
                       events=("Transfer",))
        after = helper.snapshot()
        helper.assert_delta(before, after, evaluator=-CHECK_PRICE_MINOR,
                            outsider=CHECK_PRICE_MINOR)
        self.check = {"status": "CHECK_PAID", "request_id": request_id,
                      "obligation_id": row.obligation_id, "payer_role": "auditor",
                      "payee_role": "independent_check_service",
                      "amount_minor": CHECK_PRICE_MINOR,
                      "transaction_hash": tx["transactionHash"],
                      "buyer_records": protected_buyer_records(row.truth).checked_result(),
                      "oracle_status": "PASS" if row.truth == "good" else "FAIL"}
        (self.output / "check-transaction.json").write_text(json.dumps({
            "receipt": self.check, "before": before, "after": after,
            "raw_receipt": tx, "raw_transaction": helper.rpc.call(
                "eth_getTransactionByHash", [tx["transactionHash"]]),
        }, indent=2, sort_keys=True) + "\n")
        return dict(self.check)

    def settle(self, row: X402LiveRow, verdict: str, checked: bool) -> dict:
        if (not self._entered or row != self.row or self.settlement is not None
                or checked is not (self.check is not None)):
            raise RuntimeError("native terminal request differs from pending row")
        result = self.job.decide(verdict, check_completed=checked)
        path = self.job.save()
        verified = verify_job(path, self.assignment,
                              model_tier=self.model_tier,
                              study_id="X402_AUDIT_RETAINER_012")
        if (verified["status"] != "PASS" or verified["verdict"] != verdict
                or verified["check_completed"] is not checked
                or verified["provider_paid_minor"] !=
                (BUDGET if verdict == "ACCEPT" else 0)):
            raise RuntimeError("official job failed independent terminal verification")
        self.settlement = {"status": "COMPLETED" if verdict == "ACCEPT" else "REJECTED",
                           "obligation_id": row.obligation_id,
                           "requested_verdict": verdict,
                           "job_id": result["job_id"],
                           "transaction_hash": result["transaction_hash"],
                           "provider_paid_minor": verified["provider_paid_minor"],
                           "client_refund_minor": verified["client_refunded_minor"]}
        self.save_manifest("TERMINAL")
        return dict(self.settlement)

    def save_manifest(self, status: str) -> Path:
        if status not in {"TERMINAL", "STOPPED_PARTIAL"}:
            raise ValueError("native status differs")
        payload = {"schema": "x402-live012-native-bridge-v1",
                   "model_tier": self.model_tier,
                   "payment_tier": "NATIVE_LOCAL_PROTOCOL",
                   "status": status, "assignment": asdict(self.row),
                   "retainer_public": self.retainer,
                   "retainer_raw_sha256": (sha256((self.output /
                       "x402-intake/raw-native-x402.json").read_bytes()).hexdigest()
                       if (self.output / "x402-intake/raw-native-x402.json").is_file()
                       else None),
                   "check": self.check,
                   "check_raw_sha256": (sha256((self.output /
                       "check-transaction.json").read_bytes()).hexdigest()
                       if (self.output / "check-transaction.json").is_file()
                       else None),
                   "endowment": self.endowment,
                   "settlement": self.settlement,
                   "job_raw_sha256": (sha256((self.output /
                       "erc8183-job/native-job.json").read_bytes()).hexdigest()
                       if (self.output / "erc8183-job/native-job.json").is_file()
                       else None),
                   "partial_job_raw_sha256": (sha256((self.output /
                       "erc8183-job/native-partial.json").read_bytes()).hexdigest()
                       if (self.output / "erc8183-job/native-partial.json").is_file()
                       else None),
                   "terminal_transaction_observed": any(
                       item.get("step") in {"x402job.complete", "x402job.reject"}
                       for item in self.job.helper.transactions),
                   "partial_journal_error": self.partial_journal_error,
                   "cross_chain_atomic": False,
                   "psp_capture": False}
        path = self.output / "native-bridge.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return path

    def save_partial_native(self) -> Path:
        """Persist all controller-observed txs before disposable Anvil exits.

        A transaction may have settled even when Python raises before the
        normal native-job file is written; null callback state is not proof of
        no payout. Raw receipts already in helper.transactions remain saved.
        """
        helper = self.job.helper
        transactions = []
        for item in helper.transactions:
            saved = dict(item)
            if self.job.process is not None and self.job.process.poll() is None:
                try:
                    saved["raw_transaction"] = helper.rpc.call(
                        "eth_getTransactionByHash", [item["transaction_hash"]])
                except Exception as exc:
                    saved["raw_transaction_error_type"] = type(exc).__name__
            transactions.append(saved)
        snapshot = None
        job_state = None
        chain_inventory = None
        if (self.job.process is not None and self.job.process.poll() is None
                and self.job.job_id is not None):
            try:
                snapshot = helper.snapshot()
                job_state = helper.job(self.job.job_id)
                head = int(helper.rpc.call("eth_blockNumber"), 16)
                if not 0 < head <= 100:
                    raise ValueError("bounded local chain head required")
                blocks = [helper.rpc.call("eth_getBlockByNumber", [hex(index), False])
                          for index in range(1, head + 1)]
                chain_inventory = {
                    "chain_id": int(helper.rpc.call("eth_chainId"), 16),
                    "head_block_number": head,
                    "block_transaction_hashes": [
                        {"block_number": index, "hashes": block["transactions"]}
                        for index, block in enumerate(blocks, start=1)],
                }
            except Exception as exc:
                job_state = {"read_error_type": type(exc).__name__}
                chain_inventory = {"read_error_type": type(exc).__name__}
        payload = {"schema": "x402-live012-partial-native-journal-v1",
                   "model_tier": self.model_tier,
                   "transaction_tier": "NATIVE_LOCAL_PROTOCOL",
                   "erc8183_commit": PIN, "chain_id": CHAIN_ID,
                   "assignment": asdict(self.row),
                   "job_id": self.job.job_id,
                   "roles": helper.roles, "contracts": helper.contracts,
                   "initial": self.job.initial, "funded": self.job.funded,
                   "submitted": self.job.submitted,
                   "endowment": self.endowment, "check_claim": self.check,
                   "terminal_claim": self.settlement,
                   "last_snapshot": snapshot, "last_job_state": job_state,
                   "chain_inventory": chain_inventory,
                   "transactions": transactions,
                   "terminal_transaction_observed": any(
                       item.get("step") in {"x402job.complete", "x402job.reject"}
                       for item in transactions),
                   "outcome_status": "UNVERIFIED_PARTIAL_DO_NOT_INFER_NO_PAYOUT"}
        path = self.output / "erc8183-job/native-partial.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return path

    def __exit__(self, _type, _value, _traceback):
        if self.settlement is None and self.output.is_dir():
            try:
                self.save_partial_native()
            except Exception as exc:
                self.partial_journal_error = type(exc).__name__
            try:
                self.save_manifest("STOPPED_PARTIAL")
            except Exception:
                pass
        self.job.__exit__(_type, _value, _traceback)
