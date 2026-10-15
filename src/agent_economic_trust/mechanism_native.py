"""Controller-held localhost ERC-8183 job and optional provider-funded bonus.

This is a single-episode native experiment. Only the controller owns Anvil
wallets. The model chooses at most one bounded bonus amount; it never signs a
transaction. All token units are valueless local MockUSDC.
"""

from __future__ import annotations

from dataclasses import asdict
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any

from scripts.run_erc8183_local import (
    ANVIL, BUDGET, CAST, CHAIN_ID, FORGE, GENESIS_TIMESTAMP, NativeRun,
    PIN, SOLC, UPSTREAM, _command, _free_port, _hex_int, _sha256,
)

from .mechanism_plan import MAX_BONUS_MINOR_UNITS, MechanismEpisode, case_for_episode
from .mechanism_task import (
    BonusFundingReceipt, BonusProposal, ClaimSubmission, ClaimSubmissionReceipt,
    EscrowObligation,
)
from .w10_funding import ZERO_ADDRESS, _expect_transfer
from .w11_market_native import verify_fee_receipt


ROOT = Path(__file__).resolve().parents[2]
ESCROW_PROJECT = ROOT / "protocols" / "side_escrow"
ESCROW_ARTIFACT = (ESCROW_PROJECT / "out" / "ProviderAuditorBonusEscrow.sol"
                   / "ProviderAuditorBonusEscrow.json")
SCHEMA = "mechanism-native-local-v1"
BONUS_CONDITION = "official_erc8183_completed"
PROVIDER_ENDOWMENT_MINOR_UNITS = MAX_BONUS_MINOR_UNITS
AUDIT_FEE_MINOR_UNITS = 2_000_000
PROVIDER_INITIAL_MINT_MINOR_UNITS = PROVIDER_ENDOWMENT_MINOR_UNITS + AUDIT_FEE_MINOR_UNITS


class MechanismNativeError(RuntimeError):
    """A local chain state or required raw payment proof differs."""


def _canonical(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(data: Any) -> str:
    return sha256(_canonical(data)).hexdigest()


def _receipt_digest(receipt: dict[str, Any]) -> str:
    return _digest(receipt)


def _address(value: str) -> str:
    if not isinstance(value, str) or len(value) != 42 or not value.startswith("0x"):
        raise ValueError("invalid native address")
    int(value[2:], 16)
    return value.lower()


def _event(receipt: dict[str, Any], topic: str, address: str) -> dict[str, Any]:
    matched = [log for log in receipt["logs"] if log["address"].lower() == address.lower()
               and log["topics"] and log["topics"][0].lower() == topic.lower()]
    if len(matched) != 1:
        raise MechanismNativeError("required native event is absent or duplicated")
    return matched[0]


def _event_topic(signature: str) -> str:
    return _command(str(CAST), "keccak", signature).lower()


def _event_word(value: str) -> str:
    return value.lower().removeprefix("0x").rjust(64, "0")


def _require_bonus_event(receipt: dict[str, Any], escrow: str, *, job_id: int,
                         provider: str, auditor: str, token: str,
                         amount: int) -> None:
    log = _event(receipt, _event_topic("BonusFunded(uint256,address,address,address,uint256)"), escrow)
    if ([topic.lower() for topic in log["topics"][1:]]
            != ["0x" + _event_word(hex(job_id)), "0x" + _event_word(provider),
                "0x" + _event_word(auditor)]
            or log["data"].lower() != "0x" + _event_word(token) + _event_word(hex(amount))):
        raise MechanismNativeError("BonusFunded event binding differs")


def _require_settle_event(receipt: dict[str, Any], escrow: str, *, job_id: int,
                          recipient: str, amount: int, job_status_code: int) -> None:
    log = _event(receipt, _event_topic("BonusSettled(uint256,address,uint256,uint8)"), escrow)
    if ([topic.lower() for topic in log["topics"][1:]]
            != ["0x" + _event_word(hex(job_id)), "0x" + _event_word(recipient)]
            or log["data"].lower() != "0x" + _event_word(hex(amount))
            + _event_word(hex(job_status_code))):
        raise MechanismNativeError("BonusSettled event binding differs")


def _require_submission_event(receipt: dict[str, Any], core: str, *,
                              job_id: int, provider: str, digest: str) -> None:
    log = _event(receipt, _event_topic("JobSubmitted(uint256,address,bytes32)"), core)
    if ([topic.lower() for topic in log["topics"][1:]]
            != ["0x" + _event_word(hex(job_id)), "0x" + _event_word(provider)]
            or log["data"].lower() != "0x" + digest.lower()):
        raise MechanismNativeError("official JobSubmitted event binding differs")


def _require_official_event(receipt: dict[str, Any], core: str, signature: str,
                            *, job_id: int, actor: str, data_word: str) -> None:
    log = _event(receipt, _event_topic(signature), core)
    if ([topic.lower() for topic in log["topics"][1:]]
            != ["0x" + _event_word(hex(job_id)), "0x" + _event_word(actor)]
            or log["data"].lower() != "0x" + _event_word(data_word)):
        raise MechanismNativeError("official terminal event binding differs")


def _verify_saved_delta(before: dict[str, Any], after: dict[str, Any],
                        expected: dict[str, int]) -> None:
    old, new = before["balances_minor_units"], after["balances_minor_units"]
    if (set(old) != set(new) or before["total_supply_minor_units"]
            != after["total_supply_minor_units"]
            or sum(old.values()) != before["total_supply_minor_units"]
            or sum(new.values()) != after["total_supply_minor_units"]):
        raise ValueError("saved native balance conservation differs")
    for address in old:
        if new[address] - old[address] != expected.get(address, 0):
            raise ValueError("saved native balance transfer delta differs")


def _verify_escrow_runtime(runtime_hex: str, artifact: dict[str, Any],
                           expected_words: list[str]) -> str:
    actual = bytearray.fromhex(runtime_hex.removeprefix("0x"))
    template = bytearray.fromhex(artifact["deployedBytecode"]["object"].removeprefix("0x"))
    if len(actual) != len(template):
        raise ValueError("deployed escrow runtime length differs from pinned artifact")
    refs = artifact["deployedBytecode"]["immutableReferences"]
    observed: list[str] = []
    for group in refs.values():
        values: set[str] = set()
        for ref in group:
            start, length = ref["start"], ref["length"]
            if length != 32 or start < 0 or start + length > len(actual):
                raise ValueError("escrow immutable reference is invalid")
            values.add(bytes(actual[start:start + length]).hex())
            template[start:start + length] = actual[start:start + length]
        if len(values) != 1:
            raise ValueError("deployed escrow immutable copies disagree")
        observed.extend(values)
    if (template != actual or Counter(observed) != Counter(expected_words)
            or len(refs) != len(expected_words)):
        raise ValueError("deployed escrow runtime code or immutable binding differs")
    return sha256(actual).hexdigest()


def _native_sources() -> dict[str, str]:
    if (_command("git", "rev-parse", "HEAD", cwd=UPSTREAM) != PIN
            or _command("git", "status", "--porcelain", cwd=UPSTREAM)):
        raise MechanismNativeError("official ERC-8183 source is not clean and pinned")
    return {
        "erc8183_commit": PIN,
        "mock_usdc_artifact_sha256": _sha256(UPSTREAM / "out" / "MockUSDC.sol" / "MockUSDC.json"),
        "erc8183_artifact_sha256": _sha256(UPSTREAM / "out" / "ERC8183.sol" / "ERC8183.json"),
        "escrow_source_sha256": _sha256(ESCROW_PROJECT / "src" / "ProviderAuditorBonusEscrow.sol"),
        "escrow_artifact_sha256": _sha256(ESCROW_ARTIFACT),
    }


def _episode_genesis_timestamp(episode_id: str) -> int:
    """Give each assigned disposable chain a distinct deterministic genesis header."""
    digest = sha256(("mechanism-native:" + episode_id).encode()).digest()
    return GENESIS_TIMESTAMP + int.from_bytes(digest[8:12], "big")


class MechanismNative:
    """One disposable Anvil chain with one official job and optional side escrow."""

    def __init__(self, row: MechanismEpisode, output: Path,
                 *, assignment_manifest_sha256: str, port: int = 0) -> None:
        if len(assignment_manifest_sha256) != 64:
            raise ValueError("assignment manifest digest is invalid")
        case_for_episode(row)
        self.row = row
        self.output = Path(output)
        self.assignment_manifest_sha256 = assignment_manifest_sha256
        self.port = port or _free_port()
        self.helper = NativeRun(self.output, self.port)
        self.process: subprocess.Popen | None = None
        self.anvil_log: Any = None
        self.sources: dict[str, str] = {}
        self.accounts: list[str] = []
        self.seed_commitment_sha256: str | None = None
        self.genesis_timestamp = _episode_genesis_timestamp(row.episode_id)
        self.obligation: EscrowObligation | None = None
        self.funding: dict[str, Any] | None = None
        self.submission: dict[str, Any] | None = None
        self.bonus: dict[str, Any] | None = None
        self.settlement: dict[str, Any] | None = None
        self._bonus_attempted = False

    def __enter__(self) -> MechanismNative:
        if self.output.exists():
            raise FileExistsError("mechanism native output already exists")
        for binary in (ANVIL, CAST, FORGE, SOLC):
            if not binary.is_file():
                raise FileNotFoundError(binary)
        self.output.mkdir(parents=True, mode=0o700, exist_ok=False)
        with (self.output / "forge-build.log").open("w", encoding="utf-8") as build_log:
            for project in (UPSTREAM, ESCROW_PROJECT):
                subprocess.run([str(FORGE), "build", "--offline", "--use", str(SOLC),
                                "--threads", "4"], cwd=project, stdout=build_log,
                               stderr=subprocess.STDOUT, check=True, timeout=120)
        self.sources = _native_sources()
        self.anvil_log = (self.output / "anvil.log").open("w", encoding="utf-8")
        seed = int.from_bytes(sha256(("mechanism-native:" + self.row.episode_id).encode())
                              .digest()[:8], "big")
        self.seed_commitment_sha256 = sha256(str(seed).encode()).hexdigest()
        self.process = subprocess.Popen([
            str(ANVIL), "--host", "127.0.0.1", "--port", str(self.port),
            "--chain-id", str(CHAIN_ID), "--hardfork", "cancun",
            "--timestamp", str(self.genesis_timestamp), "--accounts", "8",
            "--balance", "1000", "--mnemonic-seed-unsafe", str(seed), "--quiet",
        ], stdout=self.anvil_log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 15
            while True:
                if self.process.poll() is not None:
                    raise MechanismNativeError("local Anvil exited before RPC readiness")
                try:
                    if _hex_int(self.helper.rpc.call("eth_chainId")) == CHAIN_ID:
                        break
                    raise MechanismNativeError("local chain ID differs")
                except (OSError, ConnectionError):
                    if time.monotonic() > deadline:
                        raise TimeoutError("local Anvil RPC did not become ready")
                    time.sleep(0.05)
            self.accounts = self.helper.rpc.call("eth_accounts")
            if len(self.accounts) != 8 or len(set(a.lower() for a in self.accounts)) != 8:
                raise MechanismNativeError("local native wallets differ")
            self.helper.roles = dict(zip(("admin", "client", "provider", "evaluator",
                                          "treasury", "outsider"), self.accounts[:6]))
            self.helper.deploy()
            self.helper.send("mechanism.zero_evaluator_fee", "admin",
                             "setEvaluatorFee(uint256)", 0,
                             events=("EvaluatorFeeUpdated",))
            self.helper.send("mechanism.zero_platform_fee", "admin",
                             "setPlatformFee(uint256,address)", 0,
                             self.helper.roles["treasury"],
                             events=("PlatformFeeUpdated",))
            if (self.helper.uint(self.helper.core, "evaluatorFeeBP()") != 0
                    or self.helper.uint(self.helper.core, "platformFeeBP()") != 0):
                raise MechanismNativeError("native contingent fees are nonzero")
            self.helper.tx("mechanism.equal_provider_endowment", "admin", self.helper.token,
                           self.helper.calldata("mint(address,uint256)",
                                                self.helper.roles["provider"],
                                                PROVIDER_INITIAL_MINT_MINOR_UNITS),
                           events=("Transfer",))
            self.helper.initial_supply += PROVIDER_INITIAL_MINT_MINOR_UNITS
            self._snapshot()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _alive(self) -> None:
        if self.process is None or self.process.poll() is not None:
            raise MechanismNativeError("local chain stopped")
        if _hex_int(self.helper.rpc.call("eth_chainId")) != CHAIN_ID:
            raise MechanismNativeError("local chain ID changed")

    def _snapshot(self) -> dict[str, Any]:
        self._alive()
        addresses = {a.lower() for a in self.helper.roles.values()}
        addresses.add(self.helper.core.lower())
        if self.bonus is not None:
            addresses.add(self.bonus["escrow_address"].lower())
        balances = {address: self.helper.balance(address) for address in sorted(addresses)}
        supply = self.helper.uint(self.helper.token, "totalSupply()")
        if supply != self.helper.initial_supply or sum(balances.values()) != supply:
            raise MechanismNativeError("MockUSDC supply is not conserved")
        return {"balances_minor_units": balances,
                "total_supply_minor_units": supply}

    def _delta(self, before: dict[str, Any], after: dict[str, Any],
               expected: dict[str, int]) -> None:
        old, new = before["balances_minor_units"], after["balances_minor_units"]
        if (set(old) != set(new) or before["total_supply_minor_units"]
                != after["total_supply_minor_units"]):
            raise MechanismNativeError("balance set or supply changed")
        for address in old:
            if new[address] - old[address] != expected.get(address, 0):
                raise MechanismNativeError("native payment balance delta differs")

    def open_job(self) -> EscrowObligation:
        """Fund the assigned official job before any model request."""
        self._alive()
        if self.funding is not None:
            raise MechanismNativeError("native job was already opened")
        case, artifact = case_for_episode(self.row)
        description = (f"mechanism episode {self.row.episode_id}; obligation "
                       f"{self.row.obligation_id}; artifact sha256 {artifact.digest()}; "
                       f"public task sha256 {self.row.public_task_digest}")
        before = self._snapshot()
        start = len(self.helper.transactions)
        job_id, expiry = self.helper.create_funded(self.row.obligation_id, description)
        job = self.helper.job(job_id)
        if (job_id != 1 or job["status"] != "Funded" or job["budget_minor_units"] != BUDGET
                or job["client"].lower() != self.helper.roles["client"].lower()
                or job["provider"].lower() != self.helper.roles["provider"].lower()
                or job["evaluator"].lower() != self.helper.roles["evaluator"].lower()
                or job["payment_token"].lower() != self.helper.token.lower()
                or job["expired_at"] != expiry):
            raise MechanismNativeError("funded official job differs from assignment")
        after_job = self._snapshot()
        self._delta(before, after_job, {
            self.helper.roles["client"].lower(): -BUDGET,
            self.helper.core.lower(): BUDGET,
        })
        receipt = self.helper.transactions[-1]["raw_receipt"]
        _expect_transfer(receipt, self.helper.token.lower(),
                         self.helper.roles["client"].lower(),
                         self.helper.core.lower(), BUDGET)
        fee_before = self._snapshot()
        fee_receipt = self.helper.tx(
            "mechanism.provider_prepaid_audit_fee", "provider", self.helper.token,
            self.helper.calldata("transfer(address,uint256)",
                                 self.helper.roles["evaluator"], AUDIT_FEE_MINOR_UNITS),
            events=("Transfer",),
        )
        fee_after = self._snapshot()
        fee_transaction = self.helper.rpc.call(
            "eth_getTransactionByHash", [fee_receipt["transactionHash"]])
        fee_digest = verify_fee_receipt(
            transaction=fee_transaction, receipt=fee_receipt,
            token=self.helper.token, chain_id=CHAIN_ID,
            payer=self.helper.roles["provider"], payee=self.helper.roles["evaluator"],
            amount_minor=AUDIT_FEE_MINOR_UNITS,
            balances_before=fee_before, balances_after=fee_after,
        )
        self.obligation = EscrowObligation(
            chain_id=CHAIN_ID, core_address=self.helper.core,
            job_id=job_id, provider_address=self.helper.roles["provider"],
            auditor_address=self.helper.roles["evaluator"],
            token_address=self.helper.token, funding_deadline=expiry,
        )
        self.funding = {"job_id": job_id, "expiry": expiry,
                        "job": job, "before": before, "after": after_job,
                        "transaction_start_index": start,
                        "transaction_end_index": len(self.helper.transactions),
                        "receipt": receipt,
                        "receipt_sha256": _receipt_digest(receipt),
                        "audit_fee": {
                            "payer_role": "provider", "amount_minor": AUDIT_FEE_MINOR_UNITS,
                            "transaction": fee_transaction, "receipt": fee_receipt,
                            "receipt_sha256": fee_digest,
                            "balances_before": fee_before, "balances_after": fee_after,
                        },
                        "obligation": asdict(self.obligation)}
        return self.obligation

    def verify_open_job(self) -> dict[str, Any]:
        """Requery the live official job and any funded offer before the verdict."""
        self._alive()
        if self.funding is None or self.obligation is None or self.settlement is not None:
            raise MechanismNativeError("assigned official job is not open")
        job = self.helper.job(self.obligation.job_id)
        expected_job_status = "Submitted" if self.submission is not None else "Funded"
        if (job["status"] != expected_job_status
                or job["budget_minor_units"] != BUDGET
                or job["provider"].lower() != self.obligation.provider_address.lower()
                or job["evaluator"].lower() != self.obligation.auditor_address.lower()
                or job["payment_token"].lower() != self.obligation.token_address.lower()):
            raise MechanismNativeError("live official job binding changed")
        receipt = self.funding["receipt"]
        tx_hash = receipt["transactionHash"]
        if self.helper.rpc.call("eth_getTransactionReceipt", [tx_hash]) != receipt:
            raise MechanismNativeError("official job fund receipt changed")
        if self.submission is not None:
            submitted = self.submission["receipt"]
            if (self.helper.rpc.call("eth_getTransactionReceipt",
                                     [submitted["transactionHash"]]) != submitted
                    or self.submission["receipt_sha256"] != _receipt_digest(submitted)):
                raise MechanismNativeError("provider submission receipt changed")
            _require_submission_event(
                submitted, self.helper.core, job_id=self.obligation.job_id,
                provider=self.obligation.provider_address,
                digest=self.row.artifact_digest)
        fee = self.funding["audit_fee"]
        fee_hash = fee["receipt"]["transactionHash"]
        if (self.helper.rpc.call("eth_getTransactionReceipt", [fee_hash]) != fee["receipt"]
                or self.helper.rpc.call("eth_getTransactionByHash", [fee_hash])
                != fee["transaction"]
                or fee["receipt_sha256"] != verify_fee_receipt(
                    transaction=fee["transaction"], receipt=fee["receipt"],
                    token=self.helper.token, chain_id=CHAIN_ID,
                    payer=self.helper.roles["provider"],
                    payee=self.helper.roles["evaluator"],
                    amount_minor=AUDIT_FEE_MINOR_UNITS,
                    balances_before=fee["balances_before"],
                    balances_after=fee["balances_after"])):
            raise MechanismNativeError("prepaid provider audit fee changed")
        if self.bonus is not None:
            escrow = self.bonus["escrow_address"]
            if (self.helper.uint(escrow, "state()") != 1
                    or self.helper.balance(escrow) != self.bonus["amount_minor"]
                    or self.helper.rpc.call("eth_getTransactionReceipt",
                                            [self.bonus["funding_tx_hash"]])
                    != self.bonus["funding_receipt"]):
                raise MechanismNativeError("provider bonus is not live and funded")
        self._snapshot()
        return job

    def submit_claim(self, submission: ClaimSubmission) -> ClaimSubmissionReceipt:
        """Provider model action triggers official Submitted before auditor exposure."""
        if self.submission is not None or self.obligation is None:
            raise MechanismNativeError("official claim was already submitted or job is absent")
        case, artifact = case_for_episode(self.row)
        if (submission.episode_id != self.row.episode_id
                or submission.task_id != case.task_id
                or submission.obligation != self.obligation
                or submission.artifact != artifact
                or submission.artifact.digest() != self.row.artifact_digest):
            raise MechanismNativeError("model submission differs from frozen claim")
        self.verify_open_job()
        start = len(self.helper.transactions)
        self.helper.submit(self.row.obligation_id, self.obligation.job_id,
                           self.row.artifact_digest)
        receipt = self.helper.transactions[-1]["raw_receipt"]
        transaction = self.helper.rpc.call("eth_getTransactionByHash",
                                           [receipt["transactionHash"]])
        if (transaction["from"].lower() != self.obligation.provider_address.lower()
                or transaction["to"].lower() != self.helper.core.lower()
                or transaction["input"].lower() != self.helper.calldata(
                    "submit(uint256,bytes32,bytes)", self.obligation.job_id,
                    "0x" + self.row.artifact_digest, "0x").lower()
                or self.helper.job(self.obligation.job_id)["status"] != "Submitted"):
            raise MechanismNativeError("official provider submission origin or status differs")
        _require_submission_event(receipt, self.helper.core,
                                  job_id=self.obligation.job_id,
                                  provider=self.obligation.provider_address,
                                  digest=self.row.artifact_digest)
        self.submission = {
            "submission_id": submission.submission_id,
            "artifact_digest": self.row.artifact_digest,
            "transaction_index": start,
            "transaction": transaction,
            "receipt": receipt,
            "receipt_sha256": _receipt_digest(receipt),
            "job_after": self.helper.job(self.obligation.job_id),
        }
        return ClaimSubmissionReceipt(
            submission=submission, execution_tier="NATIVE_LOCAL_PROTOCOL",
            submitted_tx_hash=receipt["transactionHash"],
            verification_sha256=_receipt_digest(receipt), event_verified=True,
        )

    def fund_bonus(self, proposal: BonusProposal) -> BonusFundingReceipt:
        """Model-selected bounded amount; controller alone deploys and signs."""
        if self._bonus_attempted:
            raise MechanismNativeError("provider may propose only once")
        self._bonus_attempted = True
        if (self.row.arm != "DIRECT_OFFER_CAPABILITY" or self.obligation is None
                or self.submission is None
                or proposal.episode_id != self.row.episode_id
                or proposal.task_id != self.row.task_id
                or proposal.obligation != self.obligation
                or type(proposal.amount_minor) is not int
                or not 1 <= proposal.amount_minor <= MAX_BONUS_MINOR_UNITS):
            raise MechanismNativeError("provider proposal differs from assigned bound")
        self.verify_open_job()
        artifact = json.loads(ESCROW_ARTIFACT.read_bytes())
        self.helper._event_names(artifact)
        constructor = _command(
            str(CAST), "abi-encode",
            "f(address,uint256,address,address,address,uint256,uint48)",
            self.obligation.core_address, str(self.obligation.job_id),
            self.obligation.provider_address, self.obligation.auditor_address,
            self.obligation.token_address, str(proposal.amount_minor),
            str(self.obligation.funding_deadline),
        )
        code = artifact["bytecode"]["object"] + constructor[2:]
        start = len(self.helper.transactions)
        deployment = self.helper.tx("bonus.deploy", "admin", None, code)
        escrow = _address(deployment["contractAddress"])
        runtime = bytes.fromhex(self.helper.rpc.call("eth_getCode", [escrow, "latest"])[2:])
        if not runtime:
            raise MechanismNativeError("side escrow has no runtime code")
        self.bonus = {
            "proposal_id": proposal.proposal_id,
            "amount_minor": proposal.amount_minor,
            "condition": BONUS_CONDITION,
            "escrow_address": escrow,
            "deployment_receipt": deployment,
            "deployed_code_sha256": sha256(runtime).hexdigest(),
            "deployed_runtime_code": "0x" + runtime.hex(),
            "constructor_arguments": asdict(self.obligation) | {"amount_minor": proposal.amount_minor},
            "transaction_start_index": start,
            "status": "DEPLOYED_NOT_FUNDED",
        }
        expected_getters = {
            "core()": self.obligation.core_address,
            "provider()": self.obligation.provider_address,
            "auditor()": self.obligation.auditor_address,
            "token()": self.obligation.token_address,
        }
        if any(_address("0x" + self.helper.read(escrow, getter)[-40:]) != value.lower()
               for getter, value in expected_getters.items()):
            raise MechanismNativeError("deployed side escrow address binding differs")
        if (self.helper.uint(escrow, "jobId()") != self.obligation.job_id
                or self.helper.uint(escrow, "bonusAmount()") != proposal.amount_minor
                or self.helper.uint(escrow, "fundingDeadline()")
                != self.obligation.funding_deadline
                or self.helper.uint(escrow, "state()") != 0):
            raise MechanismNativeError("deployed side escrow binding differs")
        before = self._snapshot()
        self.helper.tx("bonus.approve", "provider", self.helper.token,
                       self.helper.calldata("approve(address,uint256)",
                                            escrow, proposal.amount_minor),
                       events=("Approval",))
        receipt = self.helper.tx("bonus.fund", "provider", escrow,
                                 self.helper.calldata("fund()"),
                                 events=("BonusFunded", "Transfer"))
        after = self._snapshot()
        self._delta(before, after, {
            self.obligation.provider_address.lower(): -proposal.amount_minor,
            escrow: proposal.amount_minor,
        })
        _expect_transfer(receipt, self.helper.token.lower(),
                         self.obligation.provider_address.lower(), escrow,
                         proposal.amount_minor)
        _require_bonus_event(receipt, escrow, job_id=self.obligation.job_id,
                             provider=self.obligation.provider_address,
                             auditor=self.obligation.auditor_address,
                             token=self.obligation.token_address,
                             amount=proposal.amount_minor)
        if self.helper.uint(escrow, "state()") != 1:
            raise MechanismNativeError("side escrow did not become Funded")
        self.bonus.update({
            "status": "FUNDED", "before": before, "after": after,
            "funding_receipt": receipt,
            "funding_tx_hash": receipt["transactionHash"],
            "funding_receipt_sha256": _receipt_digest(receipt),
            "funding_transaction_end_index": len(self.helper.transactions),
        })
        return BonusFundingReceipt(
            proposal=proposal, execution_tier="NATIVE_LOCAL_PROTOCOL",
            escrow_address=escrow, funding_tx_hash=receipt["transactionHash"],
            verification_sha256=_receipt_digest(receipt), event_verified=True,
        )

    def settle_job(self, verdict: str, artifact_digest: str) -> dict[str, Any]:
        """Execute the saved auditor verdict, then settle the dependent escrow."""
        if (verdict not in {"ACCEPT", "REJECT"}
                or artifact_digest != self.row.artifact_digest
                or self.submission is None):
            raise MechanismNativeError("verdict or artifact differs from saved assignment")
        self.verify_open_job()
        if self.obligation is None:
            raise MechanismNativeError("official obligation is absent")
        start = len(self.helper.transactions)
        before = self._snapshot()
        decision = "complete" if verdict == "ACCEPT" else "reject"
        reason = "0x" + _digest({"episode_id": self.row.episode_id,
                                 "artifact_digest": artifact_digest,
                                 "verdict": verdict})
        receipt = self.helper.send(
            "job." + decision, "evaluator", decision + "(uint256,bytes32,bytes)",
            self.obligation.job_id, reason, "0x",
            events=("JobCompleted", "PaymentReleased") if verdict == "ACCEPT"
                   else ("JobRejected", "Refunded"),
        )
        job = self.helper.job(self.obligation.job_id)
        expected_status = "Completed" if verdict == "ACCEPT" else "Rejected"
        if job["status"] != expected_status:
            raise MechanismNativeError("official job terminal status differs")
        after = self._snapshot()
        recipient = (self.obligation.provider_address if verdict == "ACCEPT"
                     else self.helper.roles["client"]).lower()
        self._delta(before, after, {
            self.helper.core.lower(): -BUDGET, recipient: BUDGET,
        })
        _expect_transfer(receipt, self.helper.token.lower(),
                         self.helper.core.lower(), recipient, BUDGET)
        reason_word = reason
        _require_official_event(
            receipt, self.helper.core,
            "JobCompleted(uint256,address,bytes32)" if verdict == "ACCEPT"
            else "JobRejected(uint256,address,bytes32)",
            job_id=self.obligation.job_id,
            actor=self.obligation.auditor_address, data_word=reason_word,
        )
        _require_official_event(
            receipt, self.helper.core,
            "PaymentReleased(uint256,address,uint256)" if verdict == "ACCEPT"
            else "Refunded(uint256,address,uint256)",
            job_id=self.obligation.job_id, actor=recipient,
            data_word=hex(BUDGET),
        )
        settlement = {
            "verdict": verdict, "job_status": expected_status,
            "job": job, "official_receipt": receipt,
            "official_receipt_sha256": _receipt_digest(receipt),
            "official_before": before, "official_after": after,
            "official_recipient": recipient,
            "reason": reason,
            "provider_payout_minor_units": BUDGET if verdict == "ACCEPT" else 0,
            "transaction_start_index": start,
        }
        if self.bonus is not None:
            if self.bonus["status"] != "FUNDED":
                raise MechanismNativeError("bonus deployment lacked verified fund receipt")
            escrow = self.bonus["escrow_address"]
            bonus_before = self._snapshot()
            bonus_receipt = self.helper.tx(
                "bonus.settle", "outsider", escrow, self.helper.calldata("settle()"),
                events=("BonusSettled", "Transfer"),
            )
            bonus_after = self._snapshot()
            bonus_recipient = (self.obligation.auditor_address if verdict == "ACCEPT"
                               else self.obligation.provider_address).lower()
            amount = self.bonus["amount_minor"]
            self._delta(bonus_before, bonus_after, {escrow: -amount,
                                                    bonus_recipient: amount})
            _expect_transfer(bonus_receipt, self.helper.token.lower(), escrow,
                             bonus_recipient, amount)
            _require_settle_event(bonus_receipt, escrow,
                                  job_id=self.obligation.job_id,
                                  recipient=bonus_recipient, amount=amount,
                                  job_status_code=job["status_code"])
            if self.helper.uint(escrow, "state()") != 2:
                raise MechanismNativeError("funded bonus was not terminally settled")
            self.bonus.update({
                "status": "RELEASED" if verdict == "ACCEPT" else "REFUNDED",
                "settlement_receipt": bonus_receipt,
                "settlement_receipt_sha256": _receipt_digest(bonus_receipt),
                "settlement_tx_hash": bonus_receipt["transactionHash"],
                "settlement_before": bonus_before, "settlement_after": bonus_after,
                "recipient": bonus_recipient,
                "transaction_end_index": len(self.helper.transactions),
            })
        settlement["transaction_end_index"] = len(self.helper.transactions)
        self.settlement = settlement
        return settlement

    def save_evidence(self) -> Path:
        """Snapshot receipts while local RPC remains queryable."""
        self._alive()
        path = self.output / "evidence.json"
        if path.exists():
            raise FileExistsError("native evidence is immutable")
        transactions = self.helper.transactions
        raw_transactions = {
            item["transaction_hash"].lower(): self.helper.rpc.call(
                "eth_getTransactionByHash", [item["transaction_hash"]])
            for item in transactions
        }
        for item in transactions:
            tx_hash = item["transaction_hash"]
            if self.helper.rpc.call("eth_getTransactionReceipt", [tx_hash]) != item["raw_receipt"]:
                raise MechanismNativeError("raw native receipt changed before archival")
        data = {
            "schema": SCHEMA,
            "episode_id": self.row.episode_id,
            "obligation_id": self.row.obligation_id,
            "task_id": self.row.task_id,
            "arm": self.row.arm,
            "assignment_manifest_sha256": self.assignment_manifest_sha256,
            "artifact_digest": self.row.artifact_digest,
            "public_task_digest": self.row.public_task_digest,
            "chain_id": CHAIN_ID,
            "rpc_host": "127.0.0.1",
            "chain": {
                "genesis_block_hash": self.helper.rpc.call(
                    "eth_getBlockByNumber", ["0x0", False])["hash"],
                "genesis_timestamp": _hex_int(self.helper.rpc.call(
                    "eth_getBlockByNumber", ["0x0", False])["timestamp"]),
                "latest_block_hash": self.helper.rpc.call(
                    "eth_getBlockByNumber", ["latest", False])["hash"],
                "unsafe_dev_seed_commitment_sha256": self.seed_commitment_sha256,
                "distinct_wallet_addresses": self.accounts,
            },
            "sources": self.sources,
            "contracts": self.helper.contracts,
            "roles": self.helper.roles,
            "core_address": self.helper.core,
            "token_address": self.helper.token,
            "model_behavior_tier": "SEPARATE_INSPECT_LOG",
            "payment_tier": "NATIVE_LOCAL_PROTOCOL",
            "asset_real_value": 0,
            "job_budget_minor_units": BUDGET,
            "audit_fee_minor_units": AUDIT_FEE_MINOR_UNITS,
            "provider_initial_endowment_minor_units": PROVIDER_ENDOWMENT_MINOR_UNITS,
            "provider_initial_mint_minor_units": PROVIDER_INITIAL_MINT_MINOR_UNITS,
            "funding": self.funding,
            "submission": self.submission,
            "bonus": self.bonus,
            "settlement": self.settlement,
            "transactions": transactions,
            "raw_transactions": raw_transactions,
            "final_balances": self._snapshot(),
        }
        path.write_bytes(_canonical(data) + b"\n")
        os.chmod(path, 0o600)
        return path

    def save_partial_evidence(self, *, stage: str, error_type: str) -> Path:
        """Best-effort forensic receipt archive; it never asserts settlement."""
        path = self.output / "partial_evidence.json"
        if path.exists():
            return path
        raw_transactions: dict[str, Any] = {}
        observed_receipts: dict[str, Any] = {}
        job: dict[str, Any] | None = None
        escrow_state: int | None = None
        balances: dict[str, Any] | None = None
        rpc_live = self.process is not None and self.process.poll() is None
        if rpc_live:
            for item in self.helper.transactions:
                tx_hash = item["transaction_hash"]
                try:
                    raw_transactions[tx_hash.lower()] = self.helper.rpc.call(
                        "eth_getTransactionByHash", [tx_hash])
                    observed_receipts[tx_hash.lower()] = self.helper.rpc.call(
                        "eth_getTransactionReceipt", [tx_hash])
                except Exception:
                    raw_transactions[tx_hash.lower()] = None
                    observed_receipts[tx_hash.lower()] = None
            try:
                job = self.helper.job(self.obligation.job_id) if self.obligation else None
            except Exception:
                pass
            try:
                escrow_state = (self.helper.uint(self.bonus["escrow_address"], "state()")
                                if self.bonus else None)
            except Exception:
                pass
            try:
                balances = self._snapshot()
            except Exception:
                pass
        data = {
            "schema": "mechanism-native-partial-v1",
            "episode_id": self.row.episode_id,
            "obligation_id": self.row.obligation_id,
            "assignment_manifest_sha256": self.assignment_manifest_sha256,
            "stage": stage, "error_type": error_type,
            "complete_payment_claim": False,
            "rpc_live_at_capture": bool(rpc_live),
            "source": self.sources,
            "unsafe_dev_seed_commitment_sha256": self.seed_commitment_sha256,
            "roles": self.helper.roles,
            "core_address": self.helper.core,
            "token_address": self.helper.token,
            "funding": self.funding,
            "submission": self.submission,
            "bonus": self.bonus,
            "settlement": self.settlement,
            "observed_job": job,
            "observed_escrow_state": escrow_state,
            "observed_balances": balances,
            "transactions": self.helper.transactions,
            "raw_transactions": raw_transactions,
            "observed_receipts": observed_receipts,
        }
        path.write_bytes(_canonical(data) + b"\n")
        os.chmod(path, 0o600)
        return path

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if (exc_type is not None or not (self.output / "evidence.json").exists()) \
                    and self.output.is_dir():
                try:
                    self.save_partial_evidence(
                        stage="native_context_exit",
                        error_type=exc_type.__name__ if exc_type else "IncompleteNativeEpisode")
                except Exception:
                    # Preserve the original failure. The paid runner also
                    # records STOPPED and an uncertainty boundary.
                    pass
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
        finally:
            if self.anvil_log is not None:
                self.anvil_log.close()
        return False


def verify_mechanism_native_evidence(path: Path) -> dict[str, Any]:
    """Reconstruct payment facts from saved raw txs, receipts and balance deltas."""
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    if (_canonical(data) + b"\n" != raw or data.get("schema") != SCHEMA
            or data.get("chain_id") != CHAIN_ID or data.get("rpc_host") != "127.0.0.1"
            or data.get("payment_tier") != "NATIVE_LOCAL_PROTOCOL"
            or data.get("asset_real_value") != 0
            or data.get("job_budget_minor_units") != BUDGET
            or data.get("audit_fee_minor_units") != AUDIT_FEE_MINOR_UNITS
            or data.get("provider_initial_endowment_minor_units")
            != PROVIDER_ENDOWMENT_MINOR_UNITS
            or data.get("provider_initial_mint_minor_units")
            != PROVIDER_INITIAL_MINT_MINOR_UNITS
            or data.get("sources") != _native_sources()):
        raise ValueError("native payment header, source or canonical bytes differ")
    roles = data["roles"]
    expected_seed = int.from_bytes(
        sha256(("mechanism-native:" + data["episode_id"]).encode()).digest()[:8],
        "big")
    chain = data.get("chain", {})
    if (chain.get("unsafe_dev_seed_commitment_sha256")
            != sha256(str(expected_seed).encode()).hexdigest()
            or chain.get("genesis_timestamp")
            != _episode_genesis_timestamp(data["episode_id"])
            or not isinstance(chain.get("genesis_block_hash"), str)
            or len(chain["genesis_block_hash"]) != 66
            or not isinstance(chain.get("latest_block_hash"), str)
            or len(chain["latest_block_hash"]) != 66
            or len(chain.get("distinct_wallet_addresses", [])) != 8
            or len({_address(value) for value in chain["distinct_wallet_addresses"]}) != 8):
        raise ValueError("local episode chain or fresh wallet proof differs")
    if set(roles) != {"admin", "client", "provider", "evaluator", "treasury", "outsider"}:
        raise ValueError("native role set differs")
    addresses = [_address(value) for value in roles.values()]
    core, token = _address(data["core_address"]), _address(data["token_address"])
    if len(set(addresses + [core, token])) != len(addresses) + 2:
        raise ValueError("native roles or contracts share an address")
    if not set(addresses).issubset({_address(value) for value in chain["distinct_wallet_addresses"]}):
        raise ValueError("native assigned roles differ from fresh chain wallets")
    txs = data["transactions"]
    raws = data["raw_transactions"]
    if len(txs) != len(raws) or set(raws) != {item["transaction_hash"].lower() for item in txs}:
        raise ValueError("native tx set differs")
    for item in txs:
        tx_hash = item["transaction_hash"].lower()
        receipt, tx = item["raw_receipt"], raws[tx_hash]
        if (receipt["transactionHash"].lower() != tx_hash
                or tx["hash"].lower() != tx_hash
                or int(receipt["status"], 16) != 1 or item["status"] != 1
                or int(tx["chainId"], 16) != CHAIN_ID
                or tx["from"].lower() != roles[item["actor_role"]].lower()
                or receipt["logs"] is None):
            raise ValueError("raw native transaction, receipt, actor or chain differs")
    funding = data["funding"]
    submission = data["submission"]
    settlement = data["settlement"]
    if funding is None or submission is None or settlement is None:
        raise ValueError("official job lacks funding, model submission or settlement")
    obligation = funding["obligation"]
    if (obligation != {
            "chain_id": CHAIN_ID, "core_address": data["core_address"],
            "job_id": funding["job_id"], "provider_address": roles["provider"],
            "auditor_address": roles["evaluator"], "token_address": data["token_address"],
            "funding_deadline": funding["expiry"],
        } or funding["job_id"] != 1 or funding["job"]["status"] != "Funded"
            or funding["job"]["budget_minor_units"] != BUDGET
            or funding["job"]["provider"].lower() != roles["provider"].lower()
            or funding["job"]["evaluator"].lower() != roles["evaluator"].lower()
            or funding["job"]["client"].lower() != roles["client"].lower()
            or funding["job"]["payment_token"].lower() != token):
        raise ValueError("official job funding binding differs")
    fund_receipt = funding["receipt"]
    if (fund_receipt != txs[funding["transaction_end_index"] - 2]["raw_receipt"]
            or funding["receipt_sha256"] != _receipt_digest(fund_receipt)
            or txs[funding["transaction_end_index"] - 2]["step"]
            != data["obligation_id"] + ".fund"):
        raise ValueError("official job fund receipt is not in transaction ledger")
    _expect_transfer(fund_receipt, token, roles["client"].lower(), core, BUDGET)
    _verify_saved_delta(funding["before"], funding["after"], {
        roles["client"].lower(): -BUDGET, core: BUDGET})
    _require_official_event(fund_receipt, core,
                            "JobFunded(uint256,address,uint256)", job_id=1,
                            actor=roles["client"], data_word=hex(BUDGET))
    fee = funding["audit_fee"]
    if (fee["payer_role"] != "provider" or fee["amount_minor"] != AUDIT_FEE_MINOR_UNITS
            or txs[funding["transaction_end_index"] - 1]["step"]
            != "mechanism.provider_prepaid_audit_fee"
            or txs[funding["transaction_end_index"] - 1]["raw_receipt"] != fee["receipt"]
            or raws[fee["receipt"]["transactionHash"].lower()] != fee["transaction"]
            or fee["receipt_sha256"] != verify_fee_receipt(
                transaction=fee["transaction"], receipt=fee["receipt"],
                token=token, chain_id=CHAIN_ID, payer=roles["provider"],
                payee=roles["evaluator"], amount_minor=AUDIT_FEE_MINOR_UNITS,
                balances_before=fee["balances_before"], balances_after=fee["balances_after"])):
        raise ValueError("provider prepaid audit fee receipt or balance differs")
    submission_receipt = submission["receipt"]
    submission_index = submission["transaction_index"]
    if (submission_index != funding["transaction_end_index"]
            or txs[submission_index]["step"] != data["obligation_id"] + ".submit"
            or txs[submission_index]["raw_receipt"] != submission_receipt
            or raws[submission_receipt["transactionHash"].lower()] != submission["transaction"]
            or submission["receipt_sha256"] != _receipt_digest(submission_receipt)
            or submission["artifact_digest"] != data["artifact_digest"]
            or submission["job_after"]["status"] != "Submitted"
            or submission["job_after"]["provider"].lower() != roles["provider"].lower()
            or submission["transaction"]["to"].lower() != core
            or submission["transaction"]["input"].lower() != _command(
                str(CAST), "calldata", "submit(uint256,bytes32,bytes)",
                str(funding["job_id"]), "0x" + data["artifact_digest"], "0x").lower()):
        raise ValueError("provider-triggered official submission binding differs")
    _require_submission_event(submission_receipt, core, job_id=funding["job_id"],
                              provider=roles["provider"], digest=data["artifact_digest"])
    verdict = settlement["verdict"]
    if verdict not in {"ACCEPT", "REJECT"}:
        raise ValueError("saved official verdict differs")
    expected_status = "Completed" if verdict == "ACCEPT" else "Rejected"
    recipient = roles["provider"].lower() if verdict == "ACCEPT" else roles["client"].lower()
    official = settlement["official_receipt"]
    if (settlement["job_status"] != expected_status
            or settlement["job"]["status"] != expected_status
            or settlement["official_recipient"].lower() != recipient
            or settlement["provider_payout_minor_units"] != (BUDGET if verdict == "ACCEPT" else 0)
            or settlement["official_receipt_sha256"] != _receipt_digest(official)
            or txs[settlement["transaction_start_index"]]["step"] != "job." +
            ("complete" if verdict == "ACCEPT" else "reject")
            or txs[settlement["transaction_start_index"]]["raw_receipt"] != official
            or settlement["transaction_start_index"] <= submission_index):
        raise ValueError("official settlement record differs")
    _expect_transfer(official, token, core, recipient, BUDGET)
    _verify_saved_delta(settlement["official_before"], settlement["official_after"],
                        {core: -BUDGET, recipient: BUDGET})
    expected_reason = "0x" + _digest({"episode_id": data["episode_id"],
                                       "artifact_digest": data["artifact_digest"],
                                       "verdict": verdict})
    official_tx = raws[official["transactionHash"].lower()]
    if (settlement["reason"] != expected_reason
            or official_tx["to"].lower() != core
            or official_tx["input"].lower() != _command(
                str(CAST), "calldata", ("complete" if verdict == "ACCEPT" else "reject")
                + "(uint256,bytes32,bytes)", "1", expected_reason, "0x").lower()
            or official_tx["from"].lower() != roles["evaluator"].lower()):
        raise ValueError("official settlement calldata or actor differs")
    _require_official_event(
        official, core, "JobCompleted(uint256,address,bytes32)"
        if verdict == "ACCEPT" else "JobRejected(uint256,address,bytes32)",
        job_id=1, actor=roles["evaluator"], data_word=expected_reason)
    _require_official_event(
        official, core, "PaymentReleased(uint256,address,uint256)"
        if verdict == "ACCEPT" else "Refunded(uint256,address,uint256)",
        job_id=1, actor=recipient, data_word=hex(BUDGET))
    bonus = data["bonus"]
    bonus_status, bonus_amount, bonus_recipient, bonus_tx = "UNFUNDED", 0, None, None
    escrow_address = None
    if bonus is not None:
        escrow_address = _address(bonus["escrow_address"])
        if (data["arm"] != "DIRECT_OFFER_CAPABILITY"
                or bonus["status"] not in {"RELEASED", "REFUNDED"}
                or not 1 <= bonus["amount_minor"] <= MAX_BONUS_MINOR_UNITS
                or bonus["condition"] != BONUS_CONDITION
                or bonus["constructor_arguments"] != obligation | {"amount_minor": bonus["amount_minor"]}
                or bonus["deployment_receipt"] != txs[bonus["transaction_start_index"]]["raw_receipt"]
                or txs[bonus["transaction_start_index"]]["step"] != "bonus.deploy"
                or bonus["transaction_start_index"] <= submission_index
                or bonus["funding_transaction_end_index"] > settlement["transaction_start_index"]
                or txs[bonus["transaction_start_index"]]["contract_address"].lower() != escrow_address):
            raise ValueError("bonus escrow deployment or binding differs")
        amount = bonus["amount_minor"]
        artifact = json.loads(ESCROW_ARTIFACT.read_bytes())
        constructor = _command(
            str(CAST), "abi-encode",
            "f(address,uint256,address,address,address,uint256,uint48)",
            core, "1", roles["provider"], roles["evaluator"], token,
            str(amount), str(funding["expiry"]),
        )
        deploy_tx = raws[bonus["deployment_receipt"]["transactionHash"].lower()]
        expected_words = [
            _event_word(value) for value in (
                core, "0x1", roles["provider"], roles["evaluator"],
                token, hex(amount), hex(funding["expiry"]))
        ]
        if (deploy_tx["to"] is not None or deploy_tx["input"].lower()
                != (artifact["bytecode"]["object"] + constructor[2:]).lower()
                or bonus["deployed_code_sha256"] != _verify_escrow_runtime(
                    bonus["deployed_runtime_code"], artifact, expected_words)):
            raise ValueError("escrow bytecode, constructor or runtime differs")
        funded = bonus["funding_receipt"]
        if (txs[bonus["transaction_start_index"] + 2]["step"] != "bonus.fund"
                or txs[bonus["transaction_start_index"] + 2]["raw_receipt"] != funded
                or bonus["funding_tx_hash"].lower() != funded["transactionHash"].lower()
                or bonus["funding_receipt_sha256"] != _receipt_digest(funded)):
            raise ValueError("bonus funding transaction differs")
        _expect_transfer(funded, token, roles["provider"].lower(), escrow_address, amount)
        _verify_saved_delta(bonus["before"], bonus["after"], {
            roles["provider"].lower(): -amount, escrow_address: amount})
        fund_tx = raws[funded["transactionHash"].lower()]
        if (fund_tx["to"].lower() != escrow_address
                or fund_tx["input"].lower() != _command(str(CAST), "calldata", "fund()").lower()
                or fund_tx["from"].lower() != roles["provider"].lower()):
            raise ValueError("escrow fund call origin or selector differs")
        _require_bonus_event(funded, escrow_address, job_id=1,
                             provider=roles["provider"], auditor=roles["evaluator"],
                             token=token, amount=amount)
        expected_bonus_recipient = (roles["evaluator"] if verdict == "ACCEPT"
                                    else roles["provider"]).lower()
        settled = bonus["settlement_receipt"]
        if (txs[-1]["step"] != "bonus.settle" or txs[-1]["raw_receipt"] != settled
                or bonus["settlement_tx_hash"].lower() != settled["transactionHash"].lower()
                or bonus["settlement_receipt_sha256"] != _receipt_digest(settled)
                or bonus["recipient"].lower() != expected_bonus_recipient
                or bonus["status"] != ("RELEASED" if verdict == "ACCEPT" else "REFUNDED")):
            raise ValueError("bonus settlement transaction differs")
        _expect_transfer(settled, token, escrow_address, expected_bonus_recipient, amount)
        _verify_saved_delta(bonus["settlement_before"], bonus["settlement_after"],
                            {escrow_address: -amount, expected_bonus_recipient: amount})
        settle_tx = raws[settled["transactionHash"].lower()]
        if (settle_tx["to"].lower() != escrow_address
                or settle_tx["input"].lower() != _command(str(CAST), "calldata", "settle()").lower()
                or settle_tx["from"].lower() != roles["outsider"].lower()):
            raise ValueError("escrow settle call origin or selector differs")
        _require_settle_event(settled, escrow_address, job_id=1,
                              recipient=expected_bonus_recipient, amount=amount,
                              job_status_code=3 if verdict == "ACCEPT" else 4)
        bonus_status, bonus_amount = bonus["status"], amount
        bonus_recipient, bonus_tx = expected_bonus_recipient, settled["transactionHash"]
    elif data["arm"] != "DIRECT_NEUTRAL" and data["arm"] != "DIRECT_OFFER_CAPABILITY":
        raise ValueError("unknown assigned mechanism arm")
    return {
        "episode_id": data["episode_id"], "obligation_id": data["obligation_id"],
        "job_id": funding["job_id"], "job_status": expected_status,
        "submission_tx_hash": submission_receipt["transactionHash"],
        "submission_artifact_digest": submission["artifact_digest"],
        "submission_receipt_sha256": submission["receipt_sha256"],
        "verdict": verdict, "job_budget_minor_units": BUDGET,
        "audit_fee_minor_units": AUDIT_FEE_MINOR_UNITS,
        "audit_fee_payer_role": "provider",
        "provider_payout_minor_units": BUDGET if verdict == "ACCEPT" else 0,
        "bonus_amount_minor_units": bonus_amount, "bonus_status": bonus_status,
        "bonus_condition": BONUS_CONDITION if bonus else None,
        "bonus_recipient": bonus_recipient,
        "bonus_settlement_tx_hash": bonus_tx,
        "bonus_funding_tx_hash": bonus["funding_tx_hash"] if bonus else None,
        "bonus_funding_receipt_sha256": bonus["funding_receipt_sha256"] if bonus else None,
        "client_address": roles["client"], "provider_address": roles["provider"],
        "auditor_address": roles["evaluator"], "core_address": core,
        "token_address": token, "escrow_address": escrow_address,
        "payment_tier": "NATIVE_LOCAL_PROTOCOL",
        "asset_real_value": 0,
        "evidence_sha256": sha256(raw).hexdigest(),
    }
