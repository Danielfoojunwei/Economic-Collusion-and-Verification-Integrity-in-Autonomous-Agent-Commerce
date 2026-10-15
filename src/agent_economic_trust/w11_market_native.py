"""Durable localhost ERC-8183/MockUSDC controller for a W11 market.

Each market has one disposable Anvil chain, but that chain survives every
round in the market. Identity IDs keep the same wallet across rounds, even
when an identity changes roles. A direct ERC-20 audit fee is linked to its
business obligation by this controller, not by the ERC-20 contract.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

from scripts.run_erc8183_local import (
    ANVIL, BUDGET, CAST, CHAIN_ID, FORGE, GENESIS_TIMESTAMP, NativeRun,
    PIN, SOLC, UPSTREAM, _command, _free_port, _hex_int, _sha256,
)

from .w10_factorial import FEE_MINOR_UNITS, _canonical
from .w10_funding import ZERO_ADDRESS, _expect_transfer


_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
PROVIDER_FEE_ENDOWMENT_MINOR_UNITS = 8 * FEE_MINOR_UNITS


class MarketNativeError(RuntimeError):
    """The local chain or its independently checked receipt was inconsistent."""


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"invalid {name}")
    return value


def _digest(value: str, name: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ValueError(f"invalid {name}")
    return value


def _receipt_hash(receipt: dict[str, Any]) -> str:
    return sha256(_canonical(receipt)).hexdigest()


def verify_fee_receipt(
    *, transaction: dict[str, Any], receipt: dict[str, Any],
    token: str, chain_id: int, payer: str, payee: str, amount_minor: int,
    balances_before: dict[str, Any], balances_after: dict[str, Any],
) -> str:
    """Check a raw native transfer and full market balance conservation.

    Expected payer, payee and amount must come from the frozen assignment,
    rather than the transfer itself or a model assertion. Returns the receipt
    digest for the application-level obligation map.
    """
    if type(amount_minor) is not int or amount_minor <= 0 or type(chain_id) is not int:
        raise ValueError("invalid expected native fee")
    token, payer, payee = token.lower(), payer.lower(), payee.lower()
    if len({payer, payee}) != 2:
        raise ValueError("audit fee payer and payee are identical")
    expected_input = ("0xa9059cbb" + payee[2:].rjust(64, "0")
                      + format(amount_minor, "064x"))
    if (transaction.get("hash", "").lower() != receipt.get("transactionHash", "").lower()
            or transaction.get("from", "").lower() != payer
            or transaction.get("to", "").lower() != token
            or transaction.get("input", "").lower() != expected_input
            or int(transaction.get("chainId", "0x0"), 16) != chain_id):
        raise ValueError("native audit fee has wrong transaction, payer, payee or amount")
    _expect_transfer(receipt, token, payer, payee, amount_minor)
    before = balances_before["balances_minor_units"]
    after = balances_after["balances_minor_units"]
    if set(before) != set(after) or payer not in before or payee not in before:
        raise ValueError("native audit fee balance addresses differ")
    if (balances_before["total_supply_minor_units"]
            != balances_after["total_supply_minor_units"]
            or sum(before.values()) != balances_before["total_supply_minor_units"]
            or sum(after.values()) != balances_after["total_supply_minor_units"]):
        raise ValueError("native audit fee supply conservation failed")
    for address in before:
        expected_delta = (-amount_minor if address == payer else
                          amount_minor if address == payee else 0)
        if after[address] - before[address] != expected_delta:
            raise ValueError("native audit fee balance delta differs")
    return _receipt_hash(receipt)


def _verify_mint_evidence(
    mint: dict[str, Any] | None, *, recipient: str, token: str,
    admin: str, expected_amount: int, tx_by_hash: dict[str, dict[str, Any]],
    raw_transactions: dict[str, dict[str, Any]],
) -> str | None:
    if mint is None:
        return None
    receipt = mint["raw_receipt"]
    transaction = mint["transaction"]
    tx_hash = receipt["transactionHash"].lower()
    calldata = _command(str(CAST), "calldata", "mint(address,uint256)",
                        recipient, str(expected_amount))
    if (mint["amount_minor_units"] != expected_amount
            or mint["raw_receipt_sha256"] != _receipt_hash(receipt)
            or tx_hash not in tx_by_hash
            or tx_by_hash[tx_hash]["raw_receipt"] != receipt
            or raw_transactions[tx_hash] != transaction
            or transaction["hash"].lower() != tx_hash
            or transaction["from"].lower() != admin.lower()
            or transaction["to"].lower() != token.lower()
            or transaction["input"].lower() != calldata.lower()
            or int(transaction["chainId"], 16) != CHAIN_ID):
        raise ValueError("saved market fee endowment or liquidity mint differs")
    _expect_transfer(receipt, token.lower(), ZERO_ADDRESS,
                     recipient.lower(), expected_amount)
    return tx_hash


def _require_saved_step(
    tx_by_hash: dict[str, dict[str, Any]], raw_transactions: dict[str, dict[str, Any]],
    item: dict[str, Any], *, step: str, actor: str, to: str,
    calldata: str, event_names: tuple[str, ...],
) -> None:
    tx_hash = item["transaction_hash"].lower()
    transaction = raw_transactions[tx_hash]
    receipt = item["raw_receipt"]
    if (item["step"] != step or item["status"] != 1
            or int(receipt["status"], 16) != 1
            or transaction["hash"].lower() != tx_hash
            or transaction["from"].lower() != actor.lower()
            or transaction["to"].lower() != to.lower()
            or transaction["input"].lower() != calldata.lower()
            or int(transaction["chainId"], 16) != CHAIN_ID
            or tx_by_hash[tx_hash] is not item
            or receipt["transactionHash"].lower() != tx_hash
            or not set(event_names).issubset({log["name"] for log in item["logs"]})):
        raise ValueError(f"saved native {step} origin, receipt or event differs")


def verify_market_evidence(path: Path) -> dict[str, Any]:
    """Recheck a saved market's raw receipts and one-to-one round mapping.

    This verifies internal native evidence after the disposable chain exits.
    The live RPC requery is separately enforced before each model decision and
    settlement; a JSON file alone cannot prove a chain was live at a past time.
    """
    raw = Path(path).read_bytes()
    evidence = json.loads(raw)
    if (evidence.get("schema") != "w11-native-local-market-v1"
            or evidence.get("payment_tier") != "NATIVE_LOCAL_ERC8183_PLUS_ERC20_FEE"
            or evidence.get("obligation_binding") != "APPLICATION_UNIQUE_MARKET_ROUND_MAP"
            or evidence.get("asset_real_value") != 0
            or evidence.get("chain", {}).get("rpc_host") != "127.0.0.1"
            or evidence.get("chain", {}).get("chain_id") != CHAIN_ID
            or evidence.get("source", {}).get("erc8183_base_commit") != PIN
            or evidence.get("source", {}).get("mock_usdc_artifact_sha256") != _sha256(
                UPSTREAM / "out" / "MockUSDC.sol" / "MockUSDC.json")):
        raise ValueError("saved W11 native evidence header or source pin differs")
    market_id = _identifier(evidence["market_id"], "market ID")
    r = evidence["R"]
    if type(r) is not int or r not in (0, 1):
        raise ValueError("saved market fee payer assignment differs")
    if evidence.get("fee_terms") != {
        "prepaid_audit_fee_minor_units": FEE_MINOR_UNITS,
        "provider_initial_endowment_minor_units": PROVIDER_FEE_ENDOWMENT_MINOR_UNITS,
        "conditional_evaluator_fee_bps": 0, "platform_fee_bps": 0,
    }:
        raise ValueError("saved market fee terms differ")
    identities = evidence["identity_addresses"]
    if len(set(address.lower() for address in identities.values())) != len(identities):
        raise ValueError("market identities share a native wallet")
    if any(not _ID.fullmatch(name) for name in identities):
        raise ValueError("invalid saved market identity")
    client = evidence["client_address"].lower()
    admin = evidence["admin_address"].lower()
    treasury = evidence["treasury_address"].lower()
    token = evidence["token_address"].lower()
    core = evidence["core_address"].lower()
    outsider = evidence["outsider_address"].lower()
    if len({admin, client, treasury, core, outsider, token,
            *[a.lower() for a in identities.values()]}) != 6 + len(identities):
        raise ValueError("market client, contracts or identities reuse an address")
    tx_by_hash: dict[str, dict[str, Any]] = {}
    for item in evidence["transactions"]:
        tx_hash = item["transaction_hash"].lower()
        if tx_hash in tx_by_hash or item["raw_receipt"]["transactionHash"].lower() != tx_hash:
            raise ValueError("native evidence reuses or mismatches a transaction")
        tx_by_hash[tx_hash] = item
    raw_transactions = evidence["raw_transactions"]
    if set(raw_transactions) != set(tx_by_hash):
        raise ValueError("saved raw transaction set differs from receipt ledger")
    for tx_hash, item in tx_by_hash.items():
        raw_tx = raw_transactions[tx_hash]
        if (raw_tx["hash"].lower() != tx_hash
                or int(raw_tx["chainId"], 16) != CHAIN_ID
                or item["status"] != 1
                or int(item["raw_receipt"]["status"], 16) != 1):
            raise ValueError("saved native transaction hash, chain or status differs")
    setup_steps = [
        "deploy.mock_usdc", "deploy.implementation", "deploy.proxy",
        "setup.allow_token", "setup.evaluator_fee", "setup.platform_fee",
        "setup.mint", "setup.approve",
        "market.zero_conditional_evaluator_fee", "market.zero_platform_fee",
    ]
    if [item["step"] for item in evidence["transactions"][:10]] != setup_steps:
        raise ValueError("native market deployment or fee setup steps differ")
    setup_mint = evidence["transactions"][6]
    _require_saved_step(
        tx_by_hash, raw_transactions, setup_mint,
        step="setup.mint", actor=admin, to=token,
        calldata=_command(str(CAST), "calldata", "mint(address,uint256)",
                          client, str(6 * BUDGET)),
        event_names=("Transfer",),
    )
    _expect_transfer(setup_mint["raw_receipt"], token, ZERO_ADDRESS,
                     client, 6 * BUDGET)
    _require_saved_step(
        tx_by_hash, raw_transactions, evidence["transactions"][8],
        step="market.zero_conditional_evaluator_fee", actor=admin, to=core,
        calldata=_command(str(CAST), "calldata", "setEvaluatorFee(uint256)", "0"),
        event_names=("EvaluatorFeeUpdated",),
    )
    _require_saved_step(
        tx_by_hash, raw_transactions, evidence["transactions"][9],
        step="market.zero_platform_fee", actor=admin, to=core,
        calldata=_command(str(CAST), "calldata", "setPlatformFee(uint256,address)",
                          "0", treasury),
        event_names=("PlatformFeeUpdated",),
    )
    obligations: set[str] = set()
    episodes: set[str] = set()
    jobs: set[int] = set()
    payment_hashes: set[str] = set()
    mint_hashes: set[str] = set()
    endowed: set[str] = set()
    statuses: dict[str, int] = {}
    next_transaction_index = 10
    for record in evidence["rounds"]:
        obligation = _identifier(record["obligation_id"], "obligation ID")
        episode = _identifier(record["episode_id"], "episode ID")
        if (record["market_id"] != market_id or obligation in obligations
                or episode in episodes or record["job_id"] in jobs
                or record["R"] != r or record["fee_minor_units"] != FEE_MINOR_UNITS
                or record["job_budget_minor_units"] != BUDGET):
            raise ValueError("saved market round/obligation mapping is duplicated or changed")
        if (record["transaction_start_index"] != next_transaction_index
                or type(record["transaction_end_index"]) is not int
                or record["transaction_end_index"] > len(evidence["transactions"])):
            raise ValueError("native round transaction range is missing or overlaps")
        segment = evidence["transactions"][next_transaction_index:
                                           record["transaction_end_index"]]
        next_transaction_index = record["transaction_end_index"]
        obligations.add(obligation)
        episodes.add(episode)
        jobs.add(record["job_id"])
        _digest(record["artifact_digest"], "artifact digest")
        _digest(record["public_task_digest"], "public task digest")
        addresses = record["addresses"]
        if (addresses["client"].lower() != client
                or addresses["provider"].lower() != identities[record["provider_id"]].lower()
                or addresses["auditor"].lower() != identities[record["auditor_id"]].lower()
                or record["provider_id"] == record["auditor_id"]
                or record["fee_payer_role"] != ("provider" if r else "client")):
            raise ValueError("saved market role or native wallet mapping changed")
        endowment = record["provider_initial_endowment"]
        if endowment is not None:
            if record["provider_id"] in endowed:
                raise ValueError("provider was endowed twice")
            endowed.add(record["provider_id"])
            endowment_hash = _verify_mint_evidence(
                endowment, recipient=addresses["provider"], token=token,
                admin=admin, expected_amount=PROVIDER_FEE_ENDOWMENT_MINOR_UNITS,
                tx_by_hash=tx_by_hash, raw_transactions=raw_transactions,
            )
            if endowment_hash in payment_hashes:
                raise ValueError("provider endowment transaction was reused")
            payment_hashes.add(endowment_hash)
            mint_hashes.add(endowment_hash)
        elif record["provider_id"] not in endowed:
            raise ValueError("provider paid without initial endowment")
        topup = record["client_topup"]
        if topup is not None:
            topup_hash = _verify_mint_evidence(
                topup, recipient=client, token=token, admin=admin,
                expected_amount=topup["amount_minor_units"],
                tx_by_hash=tx_by_hash, raw_transactions=raw_transactions,
            )
            if topup_hash in payment_hashes:
                raise ValueError("client liquidity transaction was reused")
            payment_hashes.add(topup_hash)
            mint_hashes.add(topup_hash)
        expected_steps = (
            ([f"{obligation}.client_liquidity"] if topup else [])
            + ([f"{obligation}.provider_initial_endowment"] if endowment else [])
            + [f"{obligation}.create", f"{obligation}.budget",
               f"{obligation}.fund", f"{obligation}.prepaid_audit_fee"]
        )
        if record["settlement"] is not None:
            expected_steps += ([f"{obligation}.submit"]
                               if record["settlement"]["verdict"] != "EXPIRE" else [])
            expected_steps.append(f"{obligation}.expiry_refund" if
                                  record["settlement"]["verdict"] == "EXPIRE" else
                                  f"{obligation}.auditor_verdict")
        if [item["step"] for item in segment] != expected_steps:
            raise ValueError("native round has missing or extra funding/submission steps")
        by_step = {item["step"]: item for item in segment}
        description = (f"W11 market {market_id}; episode {episode}; "
                       f"obligation {obligation}; artifact sha256 {record['artifact_digest']}; "
                       f"public task sha256 {record['public_task_digest']}")
        _require_saved_step(
            tx_by_hash, raw_transactions, by_step[f"{obligation}.create"],
            step=f"{obligation}.create", actor=client, to=core,
            calldata=_command(str(CAST), "calldata",
                              "createJob(address,address,uint48,string,address,uint256)",
                              addresses["provider"], addresses["auditor"],
                              str(record["expiry"]), description, ZERO_ADDRESS, "0"),
            event_names=("JobCreated",),
        )
        for action, signature, actor, names in (
            ("budget", "setBudget(uint256,address,uint256,bytes)",
             addresses["provider"], ("BudgetSet",)),
            ("fund", "fund(uint256,address,uint256,bytes)",
             client, ("JobFunded", "Transfer")),
        ):
            _require_saved_step(
                tx_by_hash, raw_transactions, by_step[f"{obligation}.{action}"],
                step=f"{obligation}.{action}", actor=actor, to=core,
                calldata=_command(str(CAST), "calldata", signature,
                                  str(record["job_id"]), token, str(BUDGET), "0x"),
                event_names=names,
            )
        _expect_transfer(by_step[f"{obligation}.fund"]["raw_receipt"],
                         token, client, core, BUDGET)
        if record["settlement"] is not None and record["settlement"]["verdict"] != "EXPIRE":
            _require_saved_step(
                tx_by_hash, raw_transactions, by_step[f"{obligation}.submit"],
                step=f"{obligation}.submit", actor=addresses["provider"], to=core,
                calldata=_command(str(CAST), "calldata", "submit(uint256,bytes32,bytes)",
                                  str(record["job_id"]),
                                  "0x" + record["artifact_digest"], "0x"),
                event_names=("JobSubmitted",),
            )
        fee_hash = record["fee_receipt"]["transactionHash"].lower()
        if fee_hash in payment_hashes or fee_hash not in tx_by_hash:
            raise ValueError("saved market fee transaction is missing or duplicated")
        payment_hashes.add(fee_hash)
        if tx_by_hash[fee_hash]["raw_receipt"] != record["fee_receipt"]:
            raise ValueError("saved market fee receipt differs from transaction ledger")
        if raw_transactions[fee_hash] != record["fee_transaction"]:
            raise ValueError("saved market fee raw transaction copies differ")
        fee_digest = verify_fee_receipt(
            transaction=record["fee_transaction"], receipt=record["fee_receipt"],
            token=token, chain_id=CHAIN_ID,
            payer=addresses["provider"] if r else client,
            payee=addresses["auditor"], amount_minor=FEE_MINOR_UNITS,
            balances_before=record["fee_balances_before"],
            balances_after=record["fee_balances_after"],
        )
        if fee_digest != record["fee_receipt_sha256"]:
            raise ValueError("saved market fee raw receipt digest changed")
        settlement = record["settlement"]
        if settlement is None:
            if record["status"] != "OPEN" or evidence["active_obligation"] != obligation:
                raise ValueError("incomplete round is not the sole active obligation")
            status = "OPEN"
        else:
            status = settlement["job_status"].upper()
            verdict = settlement["verdict"]
            expected = {"ACCEPT": "COMPLETED", "REJECT": "REJECTED",
                        "EXPIRE": "EXPIRED"}.get(verdict)
            if (record["status"] != status or expected != status
                    or settlement["provider_paid"] != (verdict == "ACCEPT")
                    or settlement["provider_payout_minor_units"] !=
                    (BUDGET if verdict == "ACCEPT" else 0)
                    or settlement["job"]["status"].upper() != status
                    or settlement["job"]["budget_minor_units"] != BUDGET):
                raise ValueError("saved market verdict, payout or terminal job differs")
            receipt = settlement["raw_receipt"]
            transaction = settlement["transaction"]
            tx_hash = receipt["transactionHash"].lower()
            signature = ({"ACCEPT": "complete(uint256,bytes32,bytes)",
                          "REJECT": "reject(uint256,bytes32,bytes)",
                          "EXPIRE": "claimRefund(uint256)"})[verdict]
            if verdict == "EXPIRE":
                expected_input = _command(str(CAST), "calldata", signature,
                                          str(record["job_id"]))
            else:
                reason = "0x" + sha256(_canonical({
                    "market_id": market_id, "obligation_id": obligation,
                    "artifact_digest": record["artifact_digest"],
                    "verdict": verdict,
                })).hexdigest()
                expected_input = _command(str(CAST), "calldata", signature,
                                          str(record["job_id"]), reason, "0x")
            if (tx_hash in payment_hashes or tx_hash not in tx_by_hash
                    or tx_by_hash[tx_hash]["raw_receipt"] != receipt
                    or raw_transactions[tx_hash] != transaction
                    or transaction["hash"].lower() != tx_hash
                    or settlement["raw_receipt_sha256"] != _receipt_hash(receipt)
                    or int(transaction["chainId"], 16) != CHAIN_ID
                    or transaction["to"].lower() != core
                    or transaction["input"].lower() != expected_input.lower()
                    or transaction["from"].lower() !=
                    (outsider if verdict == "EXPIRE" else addresses["auditor"].lower())):
                raise ValueError("saved market settlement transaction or actor differs")
            payment_hashes.add(tx_hash)
            recipient = addresses["provider"] if verdict == "ACCEPT" else client
            _expect_transfer(receipt, token, core, recipient.lower(), BUDGET)
            before = settlement["balances_before"]
            after = settlement["balances_after"]
            old, new = before["balances_minor_units"], after["balances_minor_units"]
            if (set(old) != set(new)
                    or before["total_supply_minor_units"] != after["total_supply_minor_units"]
                    or sum(old.values()) != before["total_supply_minor_units"]
                    or sum(new.values()) != after["total_supply_minor_units"]):
                raise ValueError("saved market settlement supply conservation failed")
            for address in old:
                expected_delta = (-BUDGET if address == core else
                                  BUDGET if address == recipient.lower() else 0)
                if new[address] - old[address] != expected_delta:
                    raise ValueError("saved market settlement balance delta differs")
        statuses[status] = statuses.get(status, 0) + 1
    open_obligations = {record["obligation_id"] for record in evidence["rounds"]
                        if record["status"] == "OPEN"}
    if open_obligations != ({evidence["active_obligation"]}
                            if evidence["active_obligation"] is not None else set()):
        raise ValueError("saved market has an unlinked open round")
    if jobs != set(range(1, len(jobs) + 1)):
        raise ValueError("saved market jobs are not unique sequential obligations")
    if endowed != set(evidence["provider_endowed_ids"]):
        raise ValueError("saved initial provider endowment map differs")
    if next_transaction_index != len(evidence["transactions"]):
        raise ValueError("native transactions remain outside assigned rounds")
    return {"market_id": market_id, "rounds": len(obligations),
            "statuses": statuses,
            "payment_transactions": len(payment_hashes) - len(mint_hashes),
            "initial_funding_mints": len(mint_hashes),
            "evidence_sha256": sha256(raw).hexdigest()}


class LiveNativeMarket:
    """One chain, fixed fee payer assignment and many distinct round jobs."""

    def __init__(self, market_id: str, output: Path, *, r: int, port: int = 0,
                 assignment_manifest_sha256: str | None = None,
                 resume: bool = False) -> None:
        self.market_id = _identifier(market_id, "market ID")
        if type(r) is not int or r not in (0, 1):
            raise ValueError("R must be zero (client) or one (provider)")
        self.r = r
        if assignment_manifest_sha256 is not None:
            _digest(assignment_manifest_sha256, "assignment digest")
        self.assignment_manifest_sha256 = assignment_manifest_sha256
        self.resume_existing = resume
        self.output = Path(output)
        self.port = port or _free_port()
        # This is deliberately unsafe test-only key derivation. Distinct market
        # IDs produce independent local dev wallets without storing any key.
        self.mnemonic_seed = int.from_bytes(
            sha256(("w11-local-market:" + market_id).encode()).digest()[:8], "big")
        self.helper = NativeRun(self.output, self.port)
        self.process: subprocess.Popen | None = None
        self.anvil_log: Any = None
        self.accounts: list[str] = []
        self.identity_addresses: dict[str, str] = {}
        self.provider_endowed_ids: set[str] = set()
        self.rounds: dict[str, dict[str, Any]] = {}
        self.episode_ids: set[str] = set()
        self.active_obligation: str | None = None
        self.native_evidence_sha256: str | None = None
        self.ready = False

    def __enter__(self) -> LiveNativeMarket:
        if self.resume_existing:
            if not self.output.is_dir():
                raise FileNotFoundError("saved native market directory is absent")
        elif self.output.exists():
            raise FileExistsError("native market directory already exists")
        for binary in (ANVIL, CAST, FORGE, SOLC):
            if not binary.is_file():
                raise FileNotFoundError(binary)
        if (_command("git", "rev-parse", "HEAD", cwd=UPSTREAM) != PIN
                or _command("git", "status", "--porcelain", cwd=UPSTREAM)):
            raise MarketNativeError("ERC-8183 checkout is not clean and pinned")
        if not self.resume_existing:
            self.output.mkdir(parents=True, mode=0o700, exist_ok=False)
        with (self.output / "forge-build.log").open(
                "a" if self.resume_existing else "w", encoding="utf-8") as handle:
            subprocess.run([str(FORGE), "build", "--offline", "--use", str(SOLC),
                            "--threads", "4"], cwd=UPSTREAM, stdout=handle,
                           stderr=subprocess.STDOUT, check=True, timeout=60)
        self.anvil_log = (self.output / "anvil.log").open(
            "a" if self.resume_existing else "w", encoding="utf-8")
        self.process = subprocess.Popen([
            str(ANVIL), "--host", "127.0.0.1", "--port", str(self.port),
            "--chain-id", str(CHAIN_ID), "--hardfork", "cancun",
            "--timestamp", str(GENESIS_TIMESTAMP), "--accounts", "99",
            "--balance", "1000", "--mnemonic-seed-unsafe", str(self.mnemonic_seed),
            "--quiet",
        ], stdout=self.anvil_log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 15
            while True:
                if self.process.poll() is not None:
                    raise MarketNativeError("local Anvil exited before RPC readiness")
                try:
                    chain_id = _hex_int(self.helper.rpc.call("eth_chainId"))
                    break
                except (OSError, ConnectionError):
                    if time.monotonic() > deadline:
                        raise TimeoutError("local Anvil RPC did not become ready")
                    time.sleep(0.05)
            if chain_id != CHAIN_ID:
                raise MarketNativeError("local chain ID changed")
            self.accounts = self.helper.rpc.call("eth_accounts")
            if len(self.accounts) != 99 or len({x.lower() for x in self.accounts}) != 99:
                raise MarketNativeError("local market wallet addresses are not distinct")
            self.helper.roles = {
                "admin": self.accounts[0], "client": self.accounts[1],
                "provider": self.accounts[2], "evaluator": self.accounts[3],
                "treasury": self.accounts[97], "outsider": self.accounts[98],
            }
            if self.resume_existing:
                self._restore()
                self.ready = True
                return self
            self.helper.deploy()
            self.helper.send("market.zero_conditional_evaluator_fee", "admin",
                             "setEvaluatorFee(uint256)", 0,
                             events=("EvaluatorFeeUpdated",))
            self.helper.send("market.zero_platform_fee", "admin",
                             "setPlatformFee(uint256,address)", 0,
                             self.helper.roles["treasury"],
                             events=("PlatformFeeUpdated",))
            self._verify_zero_contingent_fees()
            self._checkpoint()
            self.ready = True
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def _address_for(self, identity_id: str) -> str:
        _identifier(identity_id, "market identity")
        if identity_id not in self.identity_addresses:
            index = 2 + len(self.identity_addresses)
            if index >= 97:
                raise MarketNativeError("market exhausted isolated dev wallets")
            self.identity_addresses[identity_id] = self.accounts[index]
        return self.identity_addresses[identity_id]

    def _snapshot(self) -> dict[str, Any]:
        addresses = {self.accounts[i].lower() for i in (0, 1, 97, 98)}
        addresses.update(x.lower() for x in self.identity_addresses.values())
        addresses.add(self.helper.core.lower())
        balances = {address: self.helper.balance(address) for address in sorted(addresses)}
        supply = self.helper.uint(self.helper.token, "totalSupply()")
        if supply != self.helper.initial_supply or sum(balances.values()) != supply:
            raise MarketNativeError("market-wide MockUSDC conservation failed")
        return {"balances_minor_units": balances, "total_supply_minor_units": supply}

    def _assert_delta(self, before: dict[str, Any], after: dict[str, Any],
                      expected: dict[str, int]) -> None:
        old = before["balances_minor_units"]
        new = after["balances_minor_units"]
        if set(old) != set(new) or before["total_supply_minor_units"] != after["total_supply_minor_units"]:
            raise MarketNativeError("native market balance keys or supply changed during settlement")
        for address in old:
            if new[address] - old[address] != expected.get(address, 0):
                raise MarketNativeError("native settlement balance delta differs")

    def _mint(self, recipient: str, amount: int, step: str) -> dict[str, Any] | None:
        if amount <= 0:
            return None
        receipt = self.helper.tx(step, "admin", self.helper.token,
                                 self.helper.calldata("mint(address,uint256)", recipient, amount),
                                 events=("Transfer",))
        self.helper.initial_supply += amount
        return {
            "transaction": self.helper.rpc.call("eth_getTransactionByHash",
                                                [receipt["transactionHash"]]),
            "raw_receipt": receipt,
            "raw_receipt_sha256": _receipt_hash(receipt),
            "amount_minor_units": amount,
        }

    def _alive(self) -> None:
        if self.process is None or self.process.poll() is not None:
            raise MarketNativeError("market chain is not live")
        if _hex_int(self.helper.rpc.call("eth_chainId")) != CHAIN_ID:
            raise MarketNativeError("market chain ID changed")

    def _verify_zero_contingent_fees(self) -> None:
        if (self.helper.uint(self.helper.core, "evaluatorFeeBP()") != 0
                or self.helper.uint(self.helper.core, "platformFeeBP()") != 0):
            raise MarketNativeError("live evaluator or platform fee is nonzero")

    def _restore(self) -> None:
        evidence_path = self.output / "evidence.json"
        verify_market_evidence(evidence_path)
        evidence = json.loads(evidence_path.read_text())
        if (evidence["market_id"] != self.market_id or evidence["R"] != self.r
                or evidence["assignment_manifest_sha256"] != self.assignment_manifest_sha256
                or evidence["chain"]["unsafe_dev_seed_commitment_sha256"] !=
                sha256(str(self.mnemonic_seed).encode()).hexdigest()
                or evidence["client_address"].lower() != self.accounts[1].lower()
                or evidence["outsider_address"].lower() != self.accounts[98].lower()):
            raise MarketNativeError("saved market identity or frozen assignment differs")
        checkpoint = evidence["chain_checkpoint"]
        state_bytes = (self.output / "anvil-state.hex").read_bytes()
        if (sha256(state_bytes).hexdigest() != checkpoint["state_sha256"]
                or len(state_bytes) != checkpoint["state_bytes"]
                or not state_bytes.startswith(b"0x")):
            raise MarketNativeError("saved Anvil state digest differs from evidence")
        loaded = self.helper.rpc.call("anvil_loadState", [state_bytes.decode().strip()])
        if loaded is not True:
            raise MarketNativeError("Anvil did not accept the saved state")
        self.helper.token = evidence["token_address"]
        self.helper.core = evidence["core_address"]
        self.helper.contracts = evidence["contracts"]
        self.helper.initial_supply = checkpoint["total_supply_minor_units"]
        self.helper.transactions = evidence["transactions"]
        for name in ("MockUSDC", "ERC8183", "ERC1967Proxy"):
            artifact = json.loads((UPSTREAM / "out" / f"{name}.sol" /
                                   f"{name}.json").read_text())
            self.helper._event_names(artifact)
        self.identity_addresses = evidence["identity_addresses"]
        self.provider_endowed_ids = set(evidence["provider_endowed_ids"])
        self.rounds = {item["obligation_id"]: item for item in evidence["rounds"]}
        self.episode_ids = {item["episode_id"] for item in evidence["rounds"]}
        self.active_obligation = evidence["active_obligation"]
        if set(x.lower() for x in self.identity_addresses.values()) != {
                account.lower() for account in self.accounts[2:2 + len(self.identity_addresses)]}:
            raise MarketNativeError("restored identity wallets differ from assigned dev accounts")
        if self.rounds:
            current = (self.rounds[self.active_obligation] if self.active_obligation
                       else list(self.rounds.values())[-1])
            self.helper.roles["provider"] = current["addresses"]["provider"]
            self.helper.roles["evaluator"] = current["addresses"]["auditor"]
        self._verify_restored_chain(checkpoint, evidence["raw_transactions"])

    def _verify_restored_chain(self, checkpoint: dict[str, Any],
                               raw_transactions: dict[str, dict[str, Any]]) -> None:
        self._alive()
        self._verify_zero_contingent_fees()
        genesis = self.helper.rpc.call("eth_getBlockByNumber", ["0x0", False])
        latest = self.helper.rpc.call("eth_getBlockByNumber", ["latest", False])
        if (genesis["hash"] != checkpoint["genesis_block_hash"]
                or latest["hash"] != checkpoint["latest_block_hash"]
                or _hex_int(latest["number"]) != checkpoint["latest_block_number"]):
            raise MarketNativeError("restored genesis or transaction history differs")
        if ([_hex_int(self.helper.rpc.call("eth_getTransactionCount", [address, "latest"]))
             for address in self.accounts] != checkpoint["account_nonces"]):
            raise MarketNativeError("restored account nonces differ from saved market")
        if self._snapshot() != checkpoint["balances"]:
            raise MarketNativeError("restored token balances or supply differ")
        for item in self.helper.contracts.values():
            address = item["address"]
            code = bytes.fromhex(self.helper.rpc.call("eth_getCode", [address, "latest"])[2:])
            if sha256(code).hexdigest() != item["runtime_code_sha256"]:
                raise MarketNativeError("restored contract code differs")
        for item in self.helper.transactions:
            tx_hash = item["transaction_hash"]
            if self.helper.rpc.call("eth_getTransactionReceipt", [tx_hash]) != item["raw_receipt"]:
                raise MarketNativeError("restored raw transaction receipt differs")
            if (self.helper.rpc.call("eth_getTransactionByHash", [tx_hash])
                    != raw_transactions[tx_hash.lower()]):
                raise MarketNativeError("restored raw transaction origin differs")
        if self.helper.uint(self.helper.core, "jobCounter()") != len(self.rounds):
            raise MarketNativeError("restored job counter differs from assigned obligations")
        for record in self.rounds.values():
            job = self.helper.job(record["job_id"])
            expected_status = ("Funded" if record["status"] == "OPEN" else
                               record["settlement"]["job_status"])
            addresses = record["addresses"]
            if (job["status"] != expected_status
                    or job["client"].lower() != addresses["client"].lower()
                    or job["provider"].lower() != addresses["provider"].lower()
                    or job["evaluator"].lower() != addresses["auditor"].lower()
                    or job["budget_minor_units"] != BUDGET):
                raise MarketNativeError("restored job status, roles or amount differ")
        if self.active_obligation is not None:
            self.verify_open_round(self.active_obligation)

    def open_round(self, *, episode_id: str, obligation_id: str,
                   artifact_digest: str, public_task_digest: str,
                   provider_id: str, auditor_id: str) -> dict[str, Any]:
        """Create/fund a unique job, pay the assigned fee and checkpoint it."""
        self._alive()
        for value, name in ((episode_id, "episode ID"),
                            (obligation_id, "obligation ID"),
                            (provider_id, "provider ID"),
                            (auditor_id, "auditor ID")):
            _identifier(value, name)
        _digest(artifact_digest, "artifact digest")
        _digest(public_task_digest, "public task digest")
        if (provider_id == auditor_id or episode_id in self.episode_ids
                or obligation_id in self.rounds or self.active_obligation is not None):
            raise ValueError("duplicate or overlapping market round/identity")
        provider = self._address_for(provider_id)
        auditor = self._address_for(auditor_id)
        self.helper.roles["provider"] = provider
        self.helper.roles["evaluator"] = auditor
        client = self.helper.roles["client"]
        start = len(self.helper.transactions)
        # The initial test deployment mints six jobs' worth to the market
        # client; add only the shortfall for later rounds on this same chain.
        required = BUDGET + (FEE_MINOR_UNITS if self.r == 0 else 0)
        client_topup = self._mint(client, max(0, required - self.helper.balance(client)),
                                  f"{obligation_id}.client_liquidity")
        # One finite initial endowment supplies each provider identity's first
        # local fee. Later rounds spend persistent holdings or earned payouts.
        provider_endowment = None
        if provider_id not in self.provider_endowed_ids:
            provider_endowment = self._mint(
                provider, PROVIDER_FEE_ENDOWMENT_MINOR_UNITS,
                f"{obligation_id}.provider_initial_endowment")
            self.provider_endowed_ids.add(provider_id)
        if self.r and self.helper.balance(provider) < FEE_MINOR_UNITS:
            raise MarketNativeError("provider fee endowment is exhausted")
        description = (f"W11 market {self.market_id}; episode {episode_id}; "
                       f"obligation {obligation_id}; artifact sha256 {artifact_digest}; "
                       f"public task sha256 {public_task_digest}")
        job_id, expiry = self.helper.create_funded(obligation_id, description)
        job = self.helper.job(job_id)
        if (job["client"].lower() != client.lower()
                or job["provider"].lower() != provider.lower()
                or job["evaluator"].lower() != auditor.lower()
                or job["payment_token"].lower() != self.helper.token.lower()
                or job["budget_minor_units"] != BUDGET
                or job["status"] != "Funded"):
            raise MarketNativeError("funded round job differs from frozen roles or budget")
        before = self._snapshot()
        payer = provider if self.r else client
        receipt = self.helper.tx(
            f"{obligation_id}.prepaid_audit_fee",
            "provider" if self.r else "client", self.helper.token,
            self.helper.calldata("transfer(address,uint256)", auditor, FEE_MINOR_UNITS),
            events=("Transfer",),
        )
        transaction = self.helper.rpc.call("eth_getTransactionByHash",
                                           [receipt["transactionHash"]])
        after = self._snapshot()
        fee_digest = verify_fee_receipt(
            transaction=transaction, receipt=receipt, token=self.helper.token,
            chain_id=CHAIN_ID, payer=payer, payee=auditor,
            amount_minor=FEE_MINOR_UNITS, balances_before=before,
            balances_after=after,
        )
        record = {
            "market_id": self.market_id, "episode_id": episode_id,
            "obligation_id": obligation_id, "artifact_digest": artifact_digest,
            "public_task_digest": public_task_digest,
            "provider_id": provider_id, "auditor_id": auditor_id,
            "addresses": {"client": client, "provider": provider,
                          "auditor": auditor},
            "R": self.r, "job_id": job_id, "expiry": expiry,
            "job_budget_minor_units": BUDGET,
            "fee_minor_units": FEE_MINOR_UNITS,
            "fee_payer_role": "provider" if self.r else "client",
            "client_topup": client_topup,
            "provider_initial_endowment": provider_endowment,
            "fee_transaction": transaction, "fee_receipt": receipt,
            "fee_receipt_sha256": fee_digest,
            "fee_balances_before": before, "fee_balances_after": after,
            "transaction_start_index": start,
            "transaction_end_index": len(self.helper.transactions),
            "status": "OPEN", "settlement": None,
        }
        self.rounds[obligation_id] = record
        self.episode_ids.add(episode_id)
        self.active_obligation = obligation_id
        self.verify_open_round(obligation_id)
        self._checkpoint()
        return deepcopy(record)

    def verify_open_round(self, obligation_id: str) -> dict[str, Any]:
        """Requery the live fee, balances and funded ERC-8183 job."""
        self._alive()
        record = self.rounds.get(obligation_id)
        if record is None or record["status"] != "OPEN" or self.active_obligation != obligation_id:
            raise ValueError("obligation is not the live open round")
        tx_hash = record["fee_receipt"]["transactionHash"]
        transaction = self.helper.rpc.call("eth_getTransactionByHash", [tx_hash])
        receipt = self.helper.rpc.call("eth_getTransactionReceipt", [tx_hash])
        if transaction != record["fee_transaction"] or receipt != record["fee_receipt"]:
            raise MarketNativeError("live audit fee transaction differs from saved evidence")
        addresses = record["addresses"]
        digest = verify_fee_receipt(
            transaction=transaction, receipt=receipt, token=self.helper.token,
            chain_id=CHAIN_ID,
            payer=addresses["provider"] if self.r else addresses["client"],
            payee=addresses["auditor"], amount_minor=FEE_MINOR_UNITS,
            balances_before=record["fee_balances_before"],
            balances_after=record["fee_balances_after"],
        )
        if digest != record["fee_receipt_sha256"] or self._snapshot() != record["fee_balances_after"]:
            raise MarketNativeError("live audit fee digest or balances changed")
        job = self.helper.job(record["job_id"])
        if (job["status"] != "Funded"
                or job["client"].lower() != addresses["client"].lower()
                or job["provider"].lower() != addresses["provider"].lower()
                or job["evaluator"].lower() != addresses["auditor"].lower()
                or job["budget_minor_units"] != BUDGET):
            raise MarketNativeError("live funded job changed before decision")
        return deepcopy(record)

    def _finish(self, record: dict[str, Any], *, verdict: str, before: dict[str, Any],
                receipt: dict[str, Any], expected_status: str) -> dict[str, Any]:
        after = self._snapshot()
        addresses = record["addresses"]
        recipient = addresses["provider"] if verdict == "ACCEPT" else addresses["client"]
        _expect_transfer(receipt, self.helper.token.lower(),
                         self.helper.core.lower(), recipient.lower(), BUDGET)
        self._assert_delta(before, after, {
            self.helper.core.lower(): -BUDGET, recipient.lower(): BUDGET,
        })
        tx_hash = receipt["transactionHash"]
        if self.helper.rpc.call("eth_getTransactionReceipt", [tx_hash]) != receipt:
            raise MarketNativeError("live settlement receipt differs")
        transaction = self.helper.rpc.call("eth_getTransactionByHash", [tx_hash])
        if (transaction["from"].lower() !=
                (addresses["auditor"] if verdict in {"ACCEPT", "REJECT"}
                 else self.helper.roles["outsider"]).lower()
                or transaction["to"].lower() != self.helper.core.lower()
                or int(transaction["chainId"], 16) != CHAIN_ID):
            raise MarketNativeError("native settlement actor, core or chain differs")
        job = self.helper.job(record["job_id"])
        if job["status"] != expected_status:
            raise MarketNativeError("terminal native job status differs from decision")
        record["status"] = expected_status.upper()
        record["settlement"] = {
            "verdict": verdict, "job_status": expected_status,
            "provider_paid": verdict == "ACCEPT",
            "provider_payout_minor_units": BUDGET if verdict == "ACCEPT" else 0,
            "transaction": transaction, "raw_receipt": receipt,
            "raw_receipt_sha256": _receipt_hash(receipt),
            "balances_before": before, "balances_after": after,
            "job": job,
        }
        record["transaction_end_index"] = len(self.helper.transactions)
        self.active_obligation = None
        self._checkpoint()
        return deepcopy(record["settlement"])

    def settle_round(self, obligation_id: str, verdict: str,
                     artifact_digest: str) -> dict[str, Any]:
        """Submit the frozen artifact and execute exactly the saved verdict."""
        if verdict not in {"ACCEPT", "REJECT"}:
            raise ValueError("verdict must be ACCEPT or REJECT")
        record = self.verify_open_round(obligation_id)
        if artifact_digest != record["artifact_digest"]:
            raise ValueError("submitted artifact digest differs from frozen round")
        self.helper.submit(obligation_id, record["job_id"], artifact_digest)
        before = self._snapshot()
        decision = "complete" if verdict == "ACCEPT" else "reject"
        reason = "0x" + sha256(_canonical({
            "market_id": self.market_id, "obligation_id": obligation_id,
            "artifact_digest": artifact_digest, "verdict": verdict,
        })).hexdigest()
        receipt = self.helper.send(
            f"{obligation_id}.auditor_verdict", "evaluator",
            f"{decision}(uint256,bytes32,bytes)", record["job_id"], reason, "0x",
            events=(("JobCompleted", "PaymentReleased") if verdict == "ACCEPT"
                    else ("JobRejected", "Refunded")),
        )
        return self._finish(self.rounds[obligation_id], verdict=verdict,
                            before=before, receipt=receipt,
                            expected_status="Completed" if verdict == "ACCEPT" else "Rejected")

    def expire_round(self, obligation_id: str) -> dict[str, Any]:
        """Exercise the unsubmitted funded-job timeout and client refund."""
        record = self.verify_open_round(obligation_id)
        self.helper.next_timestamp(max(record["expiry"] + 1, self.helper.now() + 1))
        before = self._snapshot()
        receipt = self.helper.send(
            f"{obligation_id}.expiry_refund", "outsider", "claimRefund(uint256)",
            record["job_id"], events=("JobExpired", "Refunded"),
        )
        return self._finish(self.rounds[obligation_id], verdict="EXPIRE",
                            before=before, receipt=receipt, expected_status="Expired")

    def _checkpoint(self, exception_type: str | None = None) -> None:
        self._alive()
        self._verify_zero_contingent_fees()
        state = self.helper.rpc.call("anvil_dumpState")
        if not isinstance(state, str) or not state.startswith("0x"):
            raise MarketNativeError("Anvil did not return a savable state")
        state_bytes = (state + "\n").encode()
        state_temp = self.output / "anvil-state.hex.tmp"
        state_target = self.output / "anvil-state.hex"
        state_temp.write_bytes(state_bytes)
        os.chmod(state_temp, 0o600)
        os.replace(state_temp, state_target)
        genesis = self.helper.rpc.call("eth_getBlockByNumber", ["0x0", False])
        latest = self.helper.rpc.call("eth_getBlockByNumber", ["latest", False])
        chain_checkpoint = {
            "state_sha256": sha256(state_bytes).hexdigest(),
            "state_bytes": len(state_bytes),
            "genesis_block_hash": genesis["hash"],
            "latest_block_hash": latest["hash"],
            "latest_block_number": _hex_int(latest["number"]),
            "account_nonces": [
                _hex_int(self.helper.rpc.call("eth_getTransactionCount", [address, "latest"]))
                for address in self.accounts
            ],
            "balances": self._snapshot(),
            "total_supply_minor_units": self.helper.initial_supply,
        }
        evidence = {
            "schema": "w11-native-local-market-v1",
            "market_id": self.market_id, "assignment_manifest_sha256": self.assignment_manifest_sha256,
            "R": self.r,
            "chain": {"rpc_host": "127.0.0.1", "chain_id": CHAIN_ID,
                      "port": self.port, "genesis_timestamp": GENESIS_TIMESTAMP,
                      "unsafe_dev_seed_commitment_sha256": sha256(
                          str(self.mnemonic_seed).encode()).hexdigest()},
            "source": {"erc8183_base_commit": PIN,
                       "mock_usdc_artifact_sha256": _sha256(
                           UPSTREAM / "out" / "MockUSDC.sol" / "MockUSDC.json")},
            "contracts": self.helper.contracts,
            "token_address": self.helper.token, "core_address": self.helper.core,
            "client_address": self.helper.roles["client"],
            "admin_address": self.helper.roles["admin"],
            "treasury_address": self.helper.roles["treasury"],
            "outsider_address": self.helper.roles["outsider"],
            "identity_addresses": self.identity_addresses,
            "provider_endowed_ids": sorted(self.provider_endowed_ids),
            "rounds": list(self.rounds.values()),
            "active_obligation": self.active_obligation,
            "transactions": self.helper.transactions,
            "raw_transactions": {
                item["transaction_hash"].lower(): self.helper.rpc.call(
                    "eth_getTransactionByHash", [item["transaction_hash"]])
                for item in self.helper.transactions
            },
            "chain_checkpoint": chain_checkpoint,
            "model_behavior_tier": "SEPARATE_INSPECT_LOG",
            "payment_tier": "NATIVE_LOCAL_ERC8183_PLUS_ERC20_FEE",
            "fee_terms": {"prepaid_audit_fee_minor_units": FEE_MINOR_UNITS,
                          "provider_initial_endowment_minor_units":
                          PROVIDER_FEE_ENDOWMENT_MINOR_UNITS,
                          "conditional_evaluator_fee_bps": 0,
                          "platform_fee_bps": 0},
            "asset_real_value": 0,
            "obligation_binding": "APPLICATION_UNIQUE_MARKET_ROUND_MAP",
            "exception_type": exception_type,
            "limitations": [
                "ERC-20 transfers have no native business-obligation field.",
                "ERC-8183 follows the auditor verdict; it does not judge artifact correctness.",
                "Test wallets and MockUSDC have no external value.",
            ],
        }
        temp = self.output / "evidence.json.tmp"
        target = self.output / "evidence.json"
        temp.write_bytes(_canonical(evidence) + b"\n")
        os.replace(temp, target)
        self.native_evidence_sha256 = sha256(target.read_bytes()).hexdigest()

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if self.ready and self.process is not None and self.process.poll() is None:
                self._checkpoint(exc_type.__name__ if exc_type else None)
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
