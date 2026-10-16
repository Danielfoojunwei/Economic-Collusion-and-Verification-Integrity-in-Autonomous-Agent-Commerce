"""Verify saved localhost ERC-20 fee receipts against frozen W10 assignments.

MockUSDC has no obligation field. The unique trial/obligation/transaction map
is therefore an application commitment, checked alongside raw native Anvil
receipts and balance deltas. This does not turn ERC-20 into ERC-8183 escrow.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

from .w10_factorial import (
    FEE_MINOR_UNITS, Trial, VerifiedFunding, _canonical,
)


TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO_ADDRESS = "0x" + "00" * 20
_ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z")
_HASH = re.compile(r"0x[0-9a-fA-F]{64}\Z")


def _address(value: Any) -> str:
    if not isinstance(value, str) or not _ADDRESS.fullmatch(value):
        raise ValueError("invalid native address")
    return value.lower()


def _tx_hash(value: Any) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError("invalid transaction hash")
    return value.lower()


def _uint(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("invalid native token amount")
    return value


def _word_address(value: Any) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value) \
            or int(value[2:26], 16) != 0:
        raise ValueError("invalid indexed address word")
    return "0x" + value[-40:].lower()


def _expect_transfer(raw: dict[str, Any], token: str, sender: str,
                     recipient: str, amount: int) -> None:
    if int(raw["status"], 16) != 1:
        raise ValueError("native transfer transaction failed")
    matches = [log for log in raw["logs"]
               if _address(log["address"]) == token
               and log.get("topics")
               and log["topics"][0].lower() == TRANSFER_TOPIC]
    if len(matches) != 1:
        raise ValueError("expected exactly one token Transfer event")
    event = matches[0]
    if (len(event["topics"]) != 3
            or _word_address(event["topics"][1]) != sender
            or _word_address(event["topics"][2]) != recipient
            or int(event["data"], 16) != amount):
        raise ValueError("token Transfer event differs from assigned payment")


class NativePairFundingVerifier:
    """Eagerly validate all 32 saved pair receipts before releasing any prompt."""

    def __init__(self, evidence_path: Path, trials: tuple[Trial, ...],
                 assignment_manifest_sha256: str) -> None:
        raw_bytes = Path(evidence_path).read_bytes()
        evidence = json.loads(raw_bytes)
        if evidence.get("schema") != "w10-native-pair-funding-v1" \
                or evidence.get("chain", {}).get("chain_id") != 31337 \
                or evidence.get("chain", {}).get("rpc_host") != "127.0.0.1" \
                or evidence.get("payment_tier") != "NATIVE_LOCAL_ERC20" \
                or evidence.get("assignment_manifest_sha256") != assignment_manifest_sha256 \
                or evidence.get("fee_minor_units") != FEE_MINOR_UNITS \
                or evidence.get("obligation_binding") != "APPLICATION_UNIQUE_TX_MAP":
            raise ValueError("native evidence header differs from frozen W10 plan")
        source = evidence.get("source", {})
        if source.get("erc8183_base_commit") != "142e669c1fd318486a4628395b629f033654dd06" \
                or not isinstance(source.get("mock_usdc_artifact_sha256"), str) \
                or not re.fullmatch(r"[0-9a-f]{64}", source["mock_usdc_artifact_sha256"]):
            raise ValueError("native MockUSDC source pin is absent")
        artifact_path = Path(source.get("mock_usdc_artifact_path", ""))
        if not artifact_path.is_file() or sha256(artifact_path.read_bytes()).hexdigest() \
                != source["mock_usdc_artifact_sha256"]:
            raise ValueError("pinned local MockUSDC artifact differs from receipt evidence")
        token = _address(evidence["token_address"])
        deployment = evidence.get("initial_deployment", {})
        if (evidence.get("native_transactions_count") != 65
                or evidence.get("asset", {}).get("real_value") != 0
                or evidence.get("asset", {}).get("supply_minor_units") != 32 * FEE_MINOR_UNITS
                or _address(deployment.get("contract_address")) != token
                or int(deployment.get("raw_receipt", {}).get("status", "0x0"), 16) != 1):
            raise ValueError("native deployment or supply evidence is incomplete")
        expected = {trial.trial_id: trial for trial in trials}
        if len(expected) != 32 or len(evidence.get("pairs", [])) != 32:
            raise ValueError("native funding count differs from assignment count")
        self.by_trial: dict[str, VerifiedFunding] = {}
        used_addresses: set[str] = set()
        used_hashes: set[str] = set()
        used_obligations: set[str] = set()
        for pair in evidence["pairs"]:
            trial_id = pair.get("trial_id")
            if trial_id not in expected or trial_id in self.by_trial:
                raise ValueError("native funding has unknown or duplicate trial")
            trial = expected[trial_id]
            if pair.get("pair_id") != trial.pair_id \
                    or pair.get("obligation_id") != trial.obligation_id \
                    or pair.get("R") != trial.r:
                raise ValueError("native funding maps to a different assigned pair")
            if trial.obligation_id in used_obligations:
                raise ValueError("native funding reuses an obligation")
            used_obligations.add(trial.obligation_id)
            roles = pair["addresses"]
            if set(roles) != {"client", "worker", "auditor"}:
                raise ValueError("native funding roles are incomplete")
            addresses = {role: _address(address) for role, address in roles.items()}
            if used_addresses.intersection(addresses.values()) \
                    or len(set(addresses.values())) != 3:
                raise ValueError("native funding reused a pair identity across arms")
            used_addresses.update(addresses.values())
            payer_role = "worker" if trial.r else "client"
            payer, payee = addresses[payer_role], addresses["auditor"]
            before = pair["balances_before_minor"]
            after = pair["balances_after_minor"]
            if set(before) != set(roles) or set(after) != set(roles):
                raise ValueError("native pair balance roles are incomplete")
            for role in roles:
                old, new = _uint(before[role]), _uint(after[role])
                delta = -FEE_MINOR_UNITS if role == payer_role else \
                    FEE_MINOR_UNITS if role == "auditor" else 0
                if new - old != delta:
                    raise ValueError("native balance delta differs from assigned payer/payee")
            if (before[payer_role] != FEE_MINOR_UNITS
                    or before["auditor"] != 0
                    or sum(_uint(before[r]) for r in roles) != FEE_MINOR_UNITS
                    or sum(_uint(after[r]) for r in roles) != FEE_MINOR_UNITS):
                raise ValueError("native pair balances are not an isolated minted fee")
            transaction = pair["transfer_transaction"]
            tx_hash = _tx_hash(transaction["hash"])
            if tx_hash in used_hashes:
                raise ValueError("native funding reuses a transfer transaction")
            used_hashes.add(tx_hash)
            request = transaction["raw_transaction"]
            receipt = transaction["raw_receipt"]
            if (_tx_hash(request["hash"]) != tx_hash
                    or _tx_hash(receipt["transactionHash"]) != tx_hash
                    or _address(request["from"]) != payer
                    or _address(request["to"]) != token
                    or int(request["chainId"], 16) != 31337):
                raise ValueError("native raw transaction has wrong role, token, or chain")
            calldata = ("0xa9059cbb" + payee[2:].rjust(64, "0")
                        + format(FEE_MINOR_UNITS, "064x"))
            if request["input"].lower() != calldata:
                raise ValueError("native ERC-20 calldata has wrong recipient or amount")
            _expect_transfer(receipt, token, payer, payee, FEE_MINOR_UNITS)
            digest = sha256(_canonical(receipt)).hexdigest()
            if transaction.get("raw_receipt_sha256") != digest:
                raise ValueError("native raw receipt digest mismatch")
            verified = VerifiedFunding(
                obligation_id=trial.obligation_id, pair_id=trial.pair_id,
                payer_role=payer_role, payee_role="auditor",
                amount_minor=FEE_MINOR_UNITS, receipt_sha256=digest,
                transaction_hash=tx_hash, chain_id=31337,
                native_protocol="LOCAL_ERC20_TRANSFER",
            )
            verified.assert_matches(trial)
            self.by_trial[trial_id] = verified
        if set(self.by_trial) != set(expected):
            raise ValueError("some randomized pairs lack native funding")
        self.evidence_sha256 = sha256(raw_bytes).hexdigest()

    def __call__(self, trial: Trial) -> VerifiedFunding:
        result = self.by_trial.get(trial.trial_id)
        if result is None:
            raise ValueError("trial has no verified native payment")
        result.assert_matches(trial)
        return result
