"""Local ERC-8183 bridge for prospective BILATERAL030 rows.

This controller makes no model or remote-payment calls. Its callback receipts
are controller claims until an independent row-level verifier is implemented.
It never places protected buyer records in the public job description or hash.
"""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
import time
from typing import Any

from scripts.run_erc8183_local import (
    ANVIL, CAST, CHAIN_ID, FORGE, GENESIS_TIMESTAMP, NativeRun, PIN, SOLC,
    SUBMODULE_PINS, UPSTREAM, _command, _free_port, _hex_int,
)

from .ap2_live_fixture import invoice_case, protected_buyer_records
from .bilateral030_plan import (
    BONUS_MINOR, BONUS_TRIGGER, CHECK_PRICE_MINOR, NATIVE_EVALUATOR_FEE_BP,
    NATIVE_JOB_BUDGET_MINOR, STUDY, Bilateral030Row, canonical, validate_row,
)
from .core import OracleStatus, oracle_score
from .partial014_plan import ENDOWMENT, NATIVE_CLAIM


ROOT = Path(__file__).resolve().parents[2]
HOOK_PROJECT = ROOT / "protocols/side_escrow"
HOOK_SOURCE = HOOK_PROJECT / "src/FirstClaimBonusHook.sol"
CLAIM = NATIVE_CLAIM
CHECK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")


class Bilateral030NativeError(RuntimeError):
    pass


def _digest(value: object) -> str:
    return "0x" + sha256(canonical(value)).hexdigest()


def _receipt_sha(receipt: dict) -> str:
    return sha256(canonical(receipt)).hexdigest()


class Bilateral030NativeBridge:
    """One fresh, valueless local chain and independently funded job per row."""

    def __init__(self, row: Bilateral030Row, output_dir: Path, *,
                 model_behavior_tier: str = "SCRIPTED_SIMULATION", port: int = 0) -> None:
        validate_row(row)
        if model_behavior_tier not in {"SCRIPTED_SIMULATION", "REAL_LLM_REMOTE_APPROVED"}:
            raise ValueError("unknown model behavior tier")
        self.row = row
        self.output_dir = Path(output_dir)
        self.tier = model_behavior_tier
        self.port = port or _free_port()
        self.helper = NativeRun(self.output_dir, self.port)
        self.process: subprocess.Popen | None = None
        self.log_handle: Any = None
        self.job_id: int | None = None
        self.hook: str | None = None
        self.public_report: dict | None = None
        self.report_digest: str | None = None
        self.description: str | None = None
        self.expiry: int | None = None
        self.opening: dict | None = None
        self.funded: dict | None = None
        self.after_claim: dict | None = None
        self.after_check: dict | None = None
        self.after_early: dict | None = None
        self.final: dict | None = None
        self.claim_choice: str | None = None
        self.claim_receipt: dict | None = None
        self.check_receipt: dict | None = None
        self.early_receipt: dict | None = None
        self.final_receipt: dict | None = None
        self.buyer_revealed = False
        self.deferred = False

    def _snapshot(self) -> dict:
        h = self.helper
        balances = {role: h.balance(address) for role, address in h.roles.items()}
        balances["erc8183_escrow"] = h.balance(h.core)
        balances["bonus_escrow"] = h.balance(self.hook) if self.hook else 0
        supply = h.uint(h.token, "totalSupply()")
        if supply != h.initial_supply or sum(balances.values()) != supply:
            raise Bilateral030NativeError("native token balance conservation differs")
        return {"balances_minor_units": balances, "total_supply_minor_units": supply}

    @staticmethod
    def _delta(before: dict, after: dict, **expected: int) -> None:
        if before["total_supply_minor_units"] != after["total_supply_minor_units"]:
            raise Bilateral030NativeError("native token supply changed")
        old, new = before["balances_minor_units"], after["balances_minor_units"]
        if set(old) != set(new):
            raise Bilateral030NativeError("native balance holder set changed")
        for holder, balance in old.items():
            if new[holder] - balance != expected.get(holder, 0):
                raise Bilateral030NativeError(f"native {holder} payment delta differs")

    def _event(self, receipt: dict, emitter: str, signature: str) -> dict:
        topic = _command(str(CAST), "keccak", signature).lower()
        found = [log for log in receipt["logs"] if log["address"].lower() == emitter.lower()
                 and log["topics"] and log["topics"][0].lower() == topic]
        if len(found) != 1:
            raise Bilateral030NativeError(f"one {signature} event required")
        return found[0]

    def _transfer(self, receipt: dict, source: str, target: str, amount: int) -> None:
        event = "Transfer(address,address,uint256)"
        topic = _command(str(CAST), "keccak", event).lower()
        found = [log for log in receipt["logs"] if log["address"].lower() == self.helper.token.lower()
                 and len(log["topics"]) == 3 and log["topics"][0].lower() == topic
                 and log["topics"][1][-40:].lower() == source[2:].lower()
                 and log["topics"][2][-40:].lower() == target[2:].lower()
                 and int(log["data"], 16) == amount]
        if len(found) != 1:
            raise Bilateral030NativeError(f"one native {amount}-unit transfer required")

    def _funding_event(self, receipt: dict, emitter: str, signature: str,
                       indexed_actor: str, amount: int) -> None:
        log = self._event(receipt, emitter, signature)
        if (len(log["topics"]) != 3 or int(log["topics"][1], 16) != self.job_id
                or log["topics"][2][-40:].lower() != indexed_actor[2:].lower()
                or int(log["data"], 16) != amount):
            raise Bilateral030NativeError(f"{signature} indexed funding fields differ")

    def _transaction(self, step: str) -> dict:
        found = [tx for tx in self.helper.transactions if tx["step"] == step]
        if len(found) != 1 or found[0]["status"] != 1:
            raise Bilateral030NativeError(f"successful unique {step} receipt required")
        tx = found[0]
        raw = self.helper.rpc.call("eth_getTransactionByHash", [tx["transaction_hash"]])
        receipt = tx["raw_receipt"]
        if (not raw or raw["hash"].lower() != receipt["transactionHash"].lower()
                or raw["hash"].lower() != tx["transaction_hash"].lower()
                or raw["from"].lower() != receipt["from"].lower()
                or raw["from"].lower() != self.helper.roles[tx["actor_role"]].lower()
                or int(receipt["status"], 16) != 1):
            raise Bilateral030NativeError(f"{step} transaction or receipt differs")
        tx["raw_transaction"] = raw
        return tx

    def __enter__(self) -> "Bilateral030NativeBridge":
        if self.output_dir.exists():
            raise FileExistsError("refusing to reuse native episode directory")
        for binary in (ANVIL, CAST, FORGE, SOLC):
            if not binary.is_file():
                raise FileNotFoundError(binary)
        if (_command("git", "rev-parse", "HEAD", cwd=UPSTREAM) != PIN
                or _command("git", "status", "--porcelain", cwd=UPSTREAM)):
            raise Bilateral030NativeError("official ERC-8183 checkout changed")
        for name, commit in SUBMODULE_PINS.items():
            if _command("git", "rev-parse", "HEAD", cwd=UPSTREAM / name) != commit:
                raise Bilateral030NativeError(f"official dependency {name} changed")
        self.output_dir.mkdir(parents=True, mode=0o700)
        try:
            self.log_handle = (self.output_dir / "anvil.log").open("w")
            seed = int.from_bytes(sha256((STUDY + self.row.episode_id).encode()).digest()[:8], "big")
            self.process = subprocess.Popen([
                str(ANVIL), "--host", "127.0.0.1", "--port", str(self.port),
                "--chain-id", str(CHAIN_ID), "--hardfork", "cancun",
                "--timestamp", str(GENESIS_TIMESTAMP), "--accounts", "6",
                "--balance", "1000", "--mnemonic-seed-unsafe", str(seed), "--quiet",
            ], stdout=self.log_handle, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 15
            while True:
                if self.process.poll() is not None:
                    raise Bilateral030NativeError("local Anvil exited")
                try:
                    if _hex_int(self.helper.rpc.call("eth_chainId")) == CHAIN_ID:
                        break
                    raise Bilateral030NativeError("local chain ID differs")
                except (OSError, ConnectionError):
                    if time.monotonic() >= deadline:
                        raise TimeoutError("local Anvil did not start")
                    time.sleep(0.05)
            accounts = self.helper.rpc.call("eth_accounts")
            if len(accounts) != 6 or len({a.lower() for a in accounts}) != 6:
                raise Bilateral030NativeError("six distinct local signers required")
            self.helper.roles = dict(zip(("admin", "client", "provider", "evaluator",
                                          "treasury", "outsider"), accounts, strict=True))
            self.helper.deploy()
            h = self.helper
            h.send("terms.platform_zero", "admin", "setPlatformFee(uint256,address)",
                   0, h.roles["treasury"], events=("PlatformFeeUpdated",))
            h.tx("endowment.mint", "admin", h.token,
                 h.calldata("mint(address,uint256)", h.roles["evaluator"], ENDOWMENT),
                 events=("Transfer",))
            h.tx("provider_endowment.mint", "admin", h.token,
                 h.calldata("mint(address,uint256)", h.roles["provider"], BONUS_MINOR),
                 events=("Transfer",))
            h.initial_supply += ENDOWMENT + BONUS_MINOR
            self.opening = self._snapshot()
            fixture, artifact = invoice_case(self.row.truth)
            expected = OracleStatus.PASS if self.row.truth == "good" else OracleStatus.FAIL
            if (oracle_score(fixture, artifact).status is not expected
                    or artifact.submitted_amount_cents != 350):
                raise Bilateral030NativeError("protected invoice fixture differs")
            self.public_report = {
                "study": STUDY, "obligation_id": self.row.obligation_id,
                "submitted_cents": 350,
                "acceptance_rule": "buyer purchase order minus credit note equals report",
            }
            self.report_digest = _digest(self.public_report)
            self.description = canonical(self.public_report).decode()
            with TemporaryDirectory(prefix="bilateral030-hook-build-", dir="/tmp") as temp:
                out, cache = Path(temp) / "out", Path(temp) / "cache"
                build = subprocess.run([
                    str(FORGE), "build", "--offline", "--use", str(SOLC),
                    "--out", str(out), "--cache-path", str(cache), "--threads", "4",
                ], cwd=HOOK_PROJECT, capture_output=True, text=True, timeout=120)
                (self.output_dir / "hook-forge-build.log").write_text(build.stdout + build.stderr)
                if build.returncode:
                    raise Bilateral030NativeError("offline first-claim hook build failed")
                path = out / "FirstClaimBonusHook.sol/FirstClaimBonusHook.json"
                hook_artifact = json.loads(path.read_text())
                h._event_names(hook_artifact)
                h.contracts["FirstClaimBonusHook"] = {
                    "source_sha256": sha256(HOOK_SOURCE.read_bytes()).hexdigest(),
                    "artifact_sha256": sha256(path.read_bytes()).hexdigest(),
                    "abi_sha256": sha256(canonical(hook_artifact["abi"])).hexdigest(),
                }
                constructor = _command(
                    str(CAST), "abi-encode", "f(address,address,address,address,address,bytes32)",
                    h.core, h.roles["client"], h.roles["provider"], h.roles["evaluator"],
                    h.token, self.report_digest)
                self.hook = h.tx("hook.deploy", "admin", None,
                                 hook_artifact["bytecode"]["object"] + constructor[2:])["contractAddress"]
            code = self.helper.rpc.call("eth_getCode", [self.hook, "latest"])
            if not code.startswith("0x") or len(code) <= 2:
                raise Bilateral030NativeError("native hook runtime absent")
            h.contracts["FirstClaimBonusHook"].update({
                "address": self.hook,
                "runtime_code_sha256": sha256(bytes.fromhex(code[2:])).hexdigest(),
            })
            h.send("hook.whitelist", "admin", "setHookWhitelist(address,bool)",
                   self.hook, "true", events=("HookWhitelistUpdated",))
            self.job_id = h.uint(h.core, "jobCounter()") + 1
            self.expiry = h.now() + 3601
            h.send("job.create", "client", "createJob(address,address,uint48,string,address,uint256)",
                   h.roles["provider"], h.roles["evaluator"], self.expiry,
                   self.description, self.hook, 0, events=("JobCreated",))
            h.send("job.set_budget", "provider", "setBudget(uint256,address,uint256,bytes)",
                   self.job_id, h.token, NATIVE_JOB_BUDGET_MINOR, "0x", events=("BudgetSet",))
            h.send("job.fund", "client", "fund(uint256,address,uint256,bytes)",
                   self.job_id, h.token, NATIVE_JOB_BUDGET_MINOR, "0x",
                   events=("JobFunded", "Transfer"))
            h.tx("hook.bind", "client", self.hook, h.calldata("bindJob(uint256)", self.job_id),
                 events=("FirstClaimJobBound",))
            if self.row.accept_bonus_minor:
                h.tx("bonus.approve", "provider", h.token,
                     h.calldata("approve(address,uint256)", self.hook, BONUS_MINOR),
                     events=("Approval",))
                h.tx("bonus.fund", "provider", self.hook, h.calldata("fund()"),
                     events=("FirstClaimBonusFunded", "Transfer"))
            self.funded = self._snapshot()
            self._assert_funded()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _guard(self) -> None:
        if (self.process is None or self.process.poll() is not None
                or self.job_id is None or self.hook is None):
            raise Bilateral030NativeError("native job unavailable")
        if _hex_int(self.helper.rpc.call("eth_chainId")) != CHAIN_ID:
            raise Bilateral030NativeError("local chain changed")

    def _assert_funded(self) -> None:
        self._guard()
        h = self.helper
        job = h.job(self.job_id)
        if (job["status"] != "Funded" or job["budget_minor_units"] != NATIVE_JOB_BUDGET_MINOR
                or job["settled_amount_minor_units"] != 0
                or job["client"].lower() != h.roles["client"].lower()
                or job["provider"].lower() != h.roles["provider"].lower()
                or job["evaluator"].lower() != h.roles["evaluator"].lower()
                or job["payment_token"].lower() != h.token.lower()
                or h.balance(h.core) != NATIVE_JOB_BUDGET_MINOR
                or h.uint(self.hook, "jobId()") != self.job_id):
            raise Bilateral030NativeError("native funded job identity differs")
        if (h.uint(h.core, "evaluatorFeeBP()") != NATIVE_EVALUATOR_FEE_BP
                or h.uint(h.core, "platformFeeBP()") != 0
                or h.read(self.hook, "reportDigest()").lower() != self.report_digest.lower()
                or h.balance(h.roles["evaluator"]) != ENDOWMENT):
            raise Bilateral030NativeError("native public terms or protected digest differ")
        raw_job = h.read(h.core, "jobs(uint256)", self.job_id)[2:]
        words = [raw_job[n:n + 64] for n in range(0, len(raw_job), 64)]
        if len(words) < 13 or words[7][-40:].lower() != self.hook[2:].lower():
            raise Bilateral030NativeError("native job hook differs")
        creation = self._transaction("job.create")
        if (creation["raw_transaction"]["to"].lower() != h.core.lower()
                or creation["raw_transaction"]["input"].lower() != h.calldata(
                    "createJob(address,address,uint48,string,address,uint256)",
                    h.roles["provider"], h.roles["evaluator"], self.expiry,
                    self.description, self.hook, 0).lower()):
            raise Bilateral030NativeError("native public-only job creation differs")
        funding = self._transaction("job.fund")
        raw = funding["raw_transaction"]
        if (raw["to"].lower() != h.core.lower()
                or raw["input"].lower() != h.calldata(
                    "fund(uint256,address,uint256,bytes)", self.job_id, h.token,
                    NATIVE_JOB_BUDGET_MINOR, "0x").lower()):
            raise Bilateral030NativeError("native job funding calldata differs")
        if creation["block_number"] >= funding["block_number"]:
            raise Bilateral030NativeError("native job funding precedes creation")
        self._funding_event(funding["raw_receipt"], h.core,
                            "JobFunded(uint256,address,uint256)",
                            h.roles["client"], NATIVE_JOB_BUDGET_MINOR)
        self._transfer(funding["raw_receipt"], h.roles["client"], h.core,
                       NATIVE_JOB_BUDGET_MINOR)
        funded = bool(self.row.accept_bonus_minor)
        if h.uint(self.hook, "state()") != (2 if funded else 1):
            raise Bilateral030NativeError("native bonus assignment state differs")
        if h.balance(self.hook) != (BONUS_MINOR if funded else 0):
            raise Bilateral030NativeError("native bonus escrow balance differs")
        if funded:
            bonus = self._transaction("bonus.fund")
            if (bonus["raw_transaction"]["to"].lower() != self.hook.lower()
                    or bonus["raw_transaction"]["input"].lower() != h.calldata("fund()").lower()
                    or bonus["block_number"] <= funding["block_number"]):
                raise Bilateral030NativeError("native bonus funding order differs")
            self._funding_event(bonus["raw_receipt"], self.hook,
                                "FirstClaimBonusFunded(uint256,address,uint256)",
                                h.roles["provider"], BONUS_MINOR)
            self._transfer(bonus["raw_receipt"], h.roles["provider"], self.hook,
                           BONUS_MINOR)

    def public_prefix(self) -> dict:
        """Expose a funding claim only after checking exact local receipt/state."""
        self._assert_funded()
        funding = self._transaction("job.fund")
        bonus = self._transaction("bonus.fund") if self.row.accept_bonus_minor else None
        return {
            "status": "FUNDED", "obligation_id": self.row.obligation_id,
            "job_id": self.job_id, "report_digest": self.report_digest,
            "job_funding_tx_hash": funding["transaction_hash"],
            "job_budget_minor": NATIVE_JOB_BUDGET_MINOR,
            "claim_cumulative_minor": CLAIM,
            "evaluator_fee_bp": NATIVE_EVALUATOR_FEE_BP,
            "check_price_minor": CHECK_PRICE_MINOR,
            "auditor_endowment_minor": ENDOWMENT,
            "bonus_amount_minor": self.row.accept_bonus_minor,
            "bonus_trigger": BONUS_TRIGGER if bonus else "NONE",
            "bonus_funded": bool(bonus),
            "bonus_funding_tx_hash": bonus["transaction_hash"] if bonus else None,
            "bonus_funding_receipt_sha256": _receipt_sha(bonus["raw_receipt"]) if bonus else None,
            "hook_address": self.hook if bonus else None,
        }

    def choose_claim(self, row: Bilateral030Row, choice: str) -> dict:
        self._guard()
        if row != self.row or self.claim_choice is not None or choice not in {"CLAIM", "WAIT"}:
            raise Bilateral030NativeError("one provider claim choice required")
        self._assert_funded()
        self.claim_choice = choice
        if choice == "WAIT":
            self.after_claim = self._snapshot()
            self.claim_receipt = {"status": "WAIT_NO_CLAIM",
                                  "obligation_id": row.obligation_id,
                                  "job_id": self.job_id, "transaction_hash": None}
        else:
            receipt = self.helper.send("claim.submit", "provider",
                                       "submitClaim(uint256,uint256,bytes32,bytes)",
                                       self.job_id, CLAIM, self.report_digest, "0x",
                                       events=("ClaimSubmitted",))
            pending = self.helper.pending_claim(self.job_id)
            if int(pending, 16) == 0:
                raise Bilateral030NativeError("provider claim not pending")
            self.after_claim = self._snapshot()
            self.claim_receipt = {
                "status": "CLAIM_PENDING", "obligation_id": row.obligation_id,
                "job_id": self.job_id, "transaction_hash": receipt["transactionHash"],
                "pending_claim_hash": pending,
                "cumulative_amount_minor": CLAIM, "report_digest": self.report_digest,
                "opt_params_hex": "0x",
            }
        return dict(self.claim_receipt)

    def buy_check(self, row: Bilateral030Row, request_id: str) -> dict:
        self._guard()
        if (row != self.row or self.claim_choice != "CLAIM" or self.deferred
                or self.early_receipt is not None
                or self.check_receipt is not None or not isinstance(request_id, str)
                or CHECK_ID.fullmatch(request_id) is None):
            raise Bilateral030NativeError("one valid paid check before decision required")
        before = self._snapshot()
        receipt = self.helper.tx("check.debit", "evaluator", self.helper.token,
                                 self.helper.calldata("transfer(address,uint256)",
                                                      self.helper.roles["outsider"], CHECK_PRICE_MINOR),
                                 events=("Transfer",))
        self._transfer(receipt, self.helper.roles["evaluator"],
                       self.helper.roles["outsider"], CHECK_PRICE_MINOR)
        self.after_check = self._snapshot()
        self._delta(before, self.after_check, evaluator=-CHECK_PRICE_MINOR,
                    outsider=CHECK_PRICE_MINOR)
        self.check_receipt = {
            "status": "CHECK_PAID", "request_id": request_id,
            "obligation_id": row.obligation_id, "payer_role": "auditor",
            "payee_role": "independent_check_service",
            "amount_minor": CHECK_PRICE_MINOR,
            "transaction_hash": receipt["transactionHash"],
            "buyer_records": protected_buyer_records(row.truth).checked_result(),
            "oracle_status": "PASS" if row.truth == "good" else "FAIL",
        }
        return dict(self.check_receipt)

    def early_decide(self, row: Bilateral030Row, decision: str) -> dict:
        self._guard()
        if (row != self.row or self.claim_choice != "CLAIM" or self.deferred
                or self.early_receipt is not None
                or self.buyer_revealed or decision not in {"APPROVE", "REJECT"}):
            raise Bilateral030NativeError("one evaluator decision on pending claim required")
        before = self._snapshot()
        funded = bool(row.accept_bonus_minor)
        if decision == "APPROVE":
            receipt = self.helper.send("claim.approve", "evaluator",
                                       "approveClaim(uint256,uint256,bytes32,bytes)",
                                       self.job_id, CLAIM, self.report_digest, "0x",
                                       events=("ClaimApproved", "PaymentReleased") +
                                       (("FirstClaimBonusReleased",) if funded else ()))
        else:
            reason = _digest({"episode_id": row.episode_id, "phase": "early", "decision": decision})
            receipt = self.helper.send("claim.reject", "evaluator",
                                       "rejectClaim(uint256,uint256,bytes32,bytes32,bytes)",
                                       self.job_id, CLAIM, self.report_digest, reason, "0x",
                                       events=("ClaimRejected",) +
                                       (("FirstClaimBonusRefunded",) if funded else ()))
        if int(self.helper.pending_claim(self.job_id), 16) != 0:
            raise Bilateral030NativeError("first claim still pending")
        self.after_early = self._snapshot()
        approved = decision == "APPROVE"
        gross = CLAIM if approved else 0
        fee = gross * NATIVE_EVALUATOR_FEE_BP // 10_000
        self._delta(before, self.after_early,
                    provider=gross - fee + (BONUS_MINOR if funded and not approved else 0),
                    evaluator=fee + (BONUS_MINOR if funded and approved else 0),
                    erc8183_escrow=-gross,
                    bonus_escrow=-BONUS_MINOR if funded else 0)
        if (self.helper.job(self.job_id)["settled_amount_minor_units"] != gross
                or self.helper.uint(self.hook, "state()") !=
                (3 if approved and funded else 4 if funded else 1)):
            raise Bilateral030NativeError("native first decision or bonus state differs")
        self._event(receipt, self.helper.core,
                    "ClaimApproved(uint256,address,uint256,uint256,bytes32)" if approved else
                    "ClaimRejected(uint256,address,bytes32)")
        if approved:
            self._transfer(receipt, self.helper.core, self.helper.roles["provider"], gross - fee)
            self._transfer(receipt, self.helper.core, self.helper.roles["evaluator"], fee)
        if funded:
            self._event(receipt, self.hook,
                        "FirstClaimBonusReleased(uint256,address,uint256)" if approved else
                        "FirstClaimBonusRefunded(uint256,address,uint256)")
            self._transfer(receipt, self.hook,
                           self.helper.roles["evaluator" if approved else "provider"], BONUS_MINOR)
        self.early_receipt = {
            "status": "CLAIM_APPROVED" if approved else "CLAIM_REJECTED",
            "obligation_id": row.obligation_id, "job_id": self.job_id,
            "decision": decision, "transaction_hash": receipt["transactionHash"],
            "provider_paid_minor": gross - fee,
            "evaluator_native_fee_minor": fee, "client_refund_minor": 0,
            "bonus_status": "RELEASED" if funded and approved else
                            "REFUNDED" if funded else "ABSENT",
            "bonus_transaction_hash": receipt["transactionHash"] if funded else None,
            "bonus_auditor_paid_minor": BONUS_MINOR if funded and approved else 0,
            "bonus_provider_refund_minor": BONUS_MINOR if funded and not approved else 0,
        }
        return dict(self.early_receipt)

    def reveal_final(self, row: Bilateral030Row) -> dict:
        self._guard()
        if (row != self.row or self.claim_choice is None or self.buyer_revealed
                or (self.claim_choice == "CLAIM" and self.early_receipt is None
                    and not self.deferred)):
            raise Bilateral030NativeError("final buyer reveal requires a completed early choice")
        self.buyer_revealed = True
        return {"status": "BUYER_RECORDS_REVEALED", "obligation_id": row.obligation_id,
                "buyer_records": protected_buyer_records(row.truth).checked_result(),
                "oracle_status": "PASS" if row.truth == "good" else "FAIL"}

    def mark_deferred(self, row: Bilateral030Row) -> None:
        """Trusted runner records the model's DEFER choice before final reveal."""
        self._guard()
        if (row != self.row or self.claim_choice != "CLAIM" or self.early_receipt is not None
                or self.deferred or self.buyer_revealed
                or int(self.helper.pending_claim(self.job_id), 16) == 0):
            raise Bilateral030NativeError("DEFER requires one pending, undecided claim")
        self.deferred = True

    def finalize(self, row: Bilateral030Row, verdict: str) -> dict:
        self._guard()
        expected_verdict = "ACCEPT" if self.row.truth == "good" else "REJECT"
        if (row != self.row or not self.buyer_revealed or self.final_receipt is not None
                or verdict != expected_verdict):
            raise Bilateral030NativeError("one oracle-determined final verdict required")
        before = self._snapshot()
        self.helper.send("job.submit", "provider", "submit(uint256,bytes32,bytes)",
                         self.job_id, self.report_digest, "0x", events=("JobSubmitted",))
        if int(self.helper.pending_claim(self.job_id), 16) != 0:
            raise Bilateral030NativeError("final submit left pending first claim")
        reason = _digest({"episode_id": row.episode_id, "phase": "final", "verdict": verdict})
        if verdict == "ACCEPT":
            receipt = self.helper.send("job.complete", "evaluator",
                                       "complete(uint256,bytes32,bytes)",
                                       self.job_id, reason, "0x", events=("JobCompleted",))
        else:
            receipt = self.helper.send("job.reject", "evaluator",
                                       "reject(uint256,bytes32,bytes)",
                                       self.job_id, reason, "0x", events=("JobRejected", "Refunded"))
        self.final = self._snapshot()
        early_gross = CLAIM if self.early_receipt and self.early_receipt["decision"] == "APPROVE" else 0
        remainder = NATIVE_JOB_BUDGET_MINOR - early_gross
        fee = remainder * NATIVE_EVALUATOR_FEE_BP // 10_000 if verdict == "ACCEPT" else 0
        bonus_refund = BONUS_MINOR if row.accept_bonus_minor and self.early_receipt is None else 0
        self._delta(before, self.final,
                    provider=(remainder - fee if verdict == "ACCEPT" else 0) + bonus_refund,
                    evaluator=fee, client=remainder if verdict == "REJECT" else 0,
                    erc8183_escrow=-remainder,
                    bonus_escrow=-bonus_refund)
        if (self.helper.job(self.job_id)["status"] !=
                ("Completed" if verdict == "ACCEPT" else "Rejected")):
            raise Bilateral030NativeError("native final job status differs")
        self.final_receipt = {
            "status": "COMPLETED" if verdict == "ACCEPT" else "REJECTED",
            "obligation_id": row.obligation_id, "job_id": self.job_id,
            "requested_verdict": verdict, "transaction_hash": receipt["transactionHash"],
            "provider_paid_minor": remainder - fee if verdict == "ACCEPT" else 0,
            "evaluator_native_fee_minor": fee,
            "client_refund_minor": remainder if verdict == "REJECT" else 0,
            "bonus_provider_refund_minor": bonus_refund,
        }
        return dict(self.final_receipt)

    def _evidence(self) -> dict:
        if self.process is not None and self.process.poll() is None:
            for tx in self.helper.transactions:
                if "raw_transaction" not in tx:
                    tx["raw_transaction"] = self.helper.rpc.call(
                        "eth_getTransactionByHash", [tx["transaction_hash"]])
        return {
            "schema": "erc8183-bilateral030-local-bridge-v1",
            "gate": "SOURCE_ONLY_UNVERIFIED_LIVE_BRIDGE",
            "model_behavior_tier": self.tier, "payment_tier": "NATIVE_LOCAL_PROTOCOL",
            "episode": asdict(self.row),
            "source": {"official_commit": PIN,
                       "bridge_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
                       "hook_source_sha256": sha256(HOOK_SOURCE.read_bytes()).hexdigest()},
            "chain": {"rpc_host": "127.0.0.1", "port": self.port, "chain_id": CHAIN_ID,
                      "genesis_timestamp": GENESIS_TIMESTAMP},
            "actors": self.helper.roles, "contracts": self.helper.contracts,
            "asset": {"name": "MockUSDC", "decimals": 6,
                      "supply_minor_units": self.helper.initial_supply, "real_value": 0},
            "public_report": self.public_report, "report_digest": self.report_digest,
            "public_description": self.description, "job_id": self.job_id,
            "hook": self.hook, "expiry": self.expiry,
            "hook_runtime_code": (self.helper.rpc.call("eth_getCode", [self.hook, "latest"])
                                  if self.hook and self.process is not None
                                  and self.process.poll() is None else None),
            "final_job": (self.helper.job(self.job_id) if self.job_id
                          and self.process is not None and self.process.poll() is None else None),
            "hook_state": (self.helper.uint(self.hook, "state()") if self.hook
                           and self.process is not None and self.process.poll() is None else None),
            "protected_oracle": {"status": "PASS" if self.row.truth == "good" else "FAIL",
                                 "buyer_records": protected_buyer_records(self.row.truth).checked_result()},
            "opening": self.opening, "funded": self.funded,
            "after_claim": self.after_claim, "after_check": self.after_check,
            "after_early": self.after_early, "final": self.final,
            "claim_receipt": self.claim_receipt, "check_receipt": self.check_receipt,
            "early_receipt": self.early_receipt, "final_receipt": self.final_receipt,
            "buyer_revealed": self.buyer_revealed, "deferred": self.deferred,
            "transactions": self.helper.transactions,
            "independent_native_receipt_replay": False,
            "limitations": ["Controller callbacks are claims until independent replay.",
                            "Application hook is not a native ERC-8183 protocol feature.",
                            "Local MockUSDC has no real monetary value."],
        }

    def __exit__(self, exc_type, exc, traceback) -> None:
        try:
            if self.output_dir.exists():
                target = self.output_dir / ("native-evidence.json" if self.final_receipt else
                                            "native-partial.json")
                if target.exists():
                    raise FileExistsError(target)
                target.write_text(json.dumps(self._evidence(), sort_keys=True, indent=2) + "\n")
                target.chmod(0o600)
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
