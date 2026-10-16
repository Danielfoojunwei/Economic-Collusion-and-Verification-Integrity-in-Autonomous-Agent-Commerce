#!/usr/bin/env python3
"""Read-only comparison of archived partial-claim and bonus-escrow controls.

The archives are from DIFFERENT local jobs. This script checks their receipts
and the exact source revision; it does not create a joint treatment or model
observation for BILATERAL030.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from protocols.side_escrow.verify_native_receipts import verify as verify_side  # noqa: E402


PARTIAL = (ROOT / "artifacts/prospective/ERC8183_PARTIAL_CLAIM013/offline-native-001"
           / "scripted-bad-native-unchecked-approval-then-reject/native-evidence.json")
SIDE = ROOT / "protocols/side_escrow/evidence/local-native-001/evidence.json"
UPSTREAM = ROOT.parent / "upstreams/erc8183/contracts/ERC8183.sol"
ESCROW = ROOT / "protocols/side_escrow/src/ProviderAuditorBonusEscrow.sol"
UPSTREAM_SHA256 = "c5db4bcdc89dce6cc53629a19fcbcb73e973bc07f83b07a730aa4712bdedb1e4"
ESCROW_SHA256 = "4a013887013bc7da42e9d290f38d7cfdfb5aa0ec8ad63f7c6cd80c2b6bc8fef2"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
APPROVE_TOPIC = "0x4ff0d1f3daa68b825fd51377440826794c2c1db9891ec768baebca503992c2b7"
REJECT_TOPIC = "0xae7362b1af91f4492868987b9c73990d780060811551b58728fbe96fd1bab275"


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def _sha(path: Path) -> str:
    _require(path.is_file() and not path.is_symlink(), f"missing or linked evidence: {path}")
    return sha256(path.read_bytes()).hexdigest()


def _one_event(receipt: dict, emitter: str, topic: str) -> dict:
    logs = [log for log in receipt["logs"] if log["address"].lower() == emitter
            and log["topics"] and log["topics"][0].lower() == topic]
    _require(len(logs) == 1, f"missing or duplicated event {topic}")
    return logs[0]


def _transfer(receipt: dict, token: str, source: str, target: str, amount: int) -> None:
    logs = [log for log in receipt["logs"] if log["address"].lower() == token
            and log["topics"] and log["topics"][0].lower() == TRANSFER_TOPIC
            and len(log["topics"]) == 3
            and "0x" + log["topics"][1][-40:].lower() == source
            and "0x" + log["topics"][2][-40:].lower() == target
            and int(log["data"], 16) == amount]
    _require(len(logs) == 1, f"missing or duplicated token transfer {amount}")


def verify_partial_record(evidence: dict) -> dict:
    """Check the relevant raw receipts and balance deltas of one saved BAD row."""
    _require(evidence.get("model_behavior_tier") == "SCRIPTED_SIMULATION"
             and evidence.get("payment_tier") == "NATIVE_LOCAL_PROTOCOL"
             and evidence.get("episode", {}).get("truth") == "bad"
             and evidence.get("claim_action") == "CLAIM"
             and evidence.get("early_decision") == "APPROVE"
             and evidence.get("final_verdict") == "REJECT",
             "scripted BAD claim path differs")
    _require(evidence.get("terms", {}).get("job_budget_minor") == 20_000_000
             and evidence["terms"].get("claim_cumulative_minor") == 10_000_000
             and evidence["terms"].get("evaluator_fee_bp") == 1000
             and evidence.get("invoice", {}).get("submitted_cents") == 350
             and evidence["invoice"].get("oracle_status") == "FAIL"
             and evidence["invoice"].get("buyer_records", {}).get("net_amount_cents") == 300,
             "independent BAD oracle or payment terms differ")
    actors = {role: address.lower() for role, address in evidence["actors"].items()}
    token = evidence["contracts"]["MockUSDC"]["address"].lower()
    core = evidence["contracts"]["ERC1967Proxy"]["address"].lower()
    txs = {tx["step"]: tx for tx in evidence["transactions"]}
    _require(len(txs) == len(evidence["transactions"]), "duplicate native step")
    approve = txs["claim.approve"]
    reject = txs["job.reject"]
    job_id = evidence["job_id"]
    for tx in (approve, reject):
        raw = tx["raw_receipt"]
        _require(tx["status"] == 1 and int(raw["status"], 16) == 1
                 and raw["transactionHash"].lower() == tx["transaction_hash"].lower()
                 and raw["to"].lower() == core
                 and raw["from"].lower() == actors["evaluator"],
                 "raw official decision receipt differs")
    _require(approve["block_number"] < reject["block_number"]
             and approve["transaction_hash"] == evidence["early_receipt"]["transaction_hash"]
             and reject["transaction_hash"] == evidence["final_receipt"]["transaction_hash"],
             "early and final receipt order differs")
    approval = _one_event(approve["raw_receipt"], core, APPROVE_TOPIC)
    _require(int(approval["topics"][1], 16) == job_id
             and "0x" + approval["topics"][2][-40:].lower() == actors["evaluator"]
             and int(approval["data"][2:66], 16) == 10_000_000
             and int(approval["data"][66:130], 16) == 10_000_000,
             "official first-claim approval event differs")
    rejection = _one_event(reject["raw_receipt"], core, REJECT_TOPIC)
    _require(int(rejection["topics"][1], 16) == job_id
             and "0x" + rejection["topics"][2][-40:].lower() == actors["evaluator"],
             "official final rejection event differs")
    _transfer(approve["raw_receipt"], token, core, actors["provider"], 9_000_000)
    _transfer(approve["raw_receipt"], token, core, actors["evaluator"], 1_000_000)
    _transfer(reject["raw_receipt"], token, core, actors["client"], 10_000_000)
    expected_early = {"provider": 9_000_000, "evaluator": 1_000_000,
                      "escrow": -10_000_000}
    expected_final = {"client": 10_000_000, "escrow": -10_000_000}
    for before, after, expected in (
            (evidence["funded"], evidence["after_early_decision"], expected_early),
            (evidence["after_early_decision"], evidence["final"], expected_final)):
        _require(before["total_supply_minor_units"] == after["total_supply_minor_units"]
                 and sum(before["balances_minor_units"].values()) == before["total_supply_minor_units"]
                 and sum(after["balances_minor_units"].values()) == after["total_supply_minor_units"],
                 "recorded MockUSDC balance conservation differs")
        for role, amount in before["balances_minor_units"].items():
            _require(after["balances_minor_units"][role] - amount == expected.get(role, 0),
                     f"recorded {role} balance delta differs")
    _require(evidence["final_job"]["status"] == "Rejected"
             and evidence["final_job"]["status_code"] == 4
             and evidence["final_job"]["settled_amount_minor_units"] == 10_000_000
             and evidence["early_receipt"]["provider_paid_minor"] == 9_000_000
             and evidence["early_receipt"]["evaluator_native_fee_minor"] == 1_000_000
             and evidence["final_receipt"]["client_refund_minor"] == 10_000_000,
             "saved native payout summary differs")
    return {"status": "SCRIPTED_PARTIAL_RECEIPTS_VERIFIED", "job_id": job_id,
            "first_provider_paid_minor": 9_000_000,
            "first_evaluator_fee_minor": 1_000_000,
            "final_client_refund_minor": 10_000_000,
            "final_job_status": "Rejected",
            "first_approval_tx_hash": approve["transaction_hash"],
            "final_rejection_tx_hash": reject["transaction_hash"]}


def diagnose(partial_path: Path = PARTIAL, side_path: Path = SIDE) -> dict:
    """Validate separate archives and pin the source defining bonus conditions."""
    _require(_sha(UPSTREAM) == UPSTREAM_SHA256 and _sha(ESCROW) == ESCROW_SHA256,
             "pinned official or application contract source differs")
    partial = json.loads(partial_path.read_text())
    first = verify_partial_record(partial)
    side = verify_side(side_path)
    side_record = json.loads(side_path.read_text())
    rejected = side_record["scenarios"]["rejected"]
    _require(side["valid"] is True and rejected["status_code"] == 4
             and rejected["bonus_minor_units"] == 5_000_000
             and rejected["bonus_recipient"] == "provider",
             "terminal-only escrow rejected-job refund differs")
    return {"schema": "bilateral030-bonus-trigger-diagnostic-v1",
            "status": "SEPARATE_SOURCE_AND_RECEIPTS_VERIFIED",
            "model_behavior_tier": "SCRIPTED_SIMULATION",
            "payment_tier": "NATIVE_LOCAL_PROTOCOL",
            "paid_model_calls": 0, "new_native_transactions": 0,
            "same_job_joint_bonus_control": False,
            "partial_archive_sha256": _sha(partial_path),
            "side_archive_sha256": _sha(side_path),
            "official_source_sha256": UPSTREAM_SHA256,
            "bonus_source_sha256": ESCROW_SHA256,
            "partial_receipt": first,
            "separate_terminal_bonus_receipt": {
                "job_id": rejected["job_id"],
                "official_job_status": "Rejected",
                "provider_bonus_refund_minor": rejected["bonus_minor_units"],
                "auditor_bonus_minor": 0,
                "bonus_settlement_tx_hash": rejected["bonus_receipt"]},
            "source_trigger": "official terminal Completed pays auditor; Rejected/Expired refunds provider",
            "source_only_joint_prediction": "early APPROVE then final REJECT refunds provider-funded bonus",
            "early_funded_bonus_treatment": "HOLD_UNIMPLEMENTED"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--partial", type=Path, default=PARTIAL)
    parser.add_argument("--side", type=Path, default=SIDE)
    args = parser.parse_args()
    print(json.dumps(diagnose(args.partial, args.side), sort_keys=True))


if __name__ == "__main__":
    main()
