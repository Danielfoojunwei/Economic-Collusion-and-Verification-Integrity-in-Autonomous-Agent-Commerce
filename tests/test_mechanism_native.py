"""Actual localhost receipt closure and corruption controls; no model calls."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent_economic_trust.mechanism_native import (
    MechanismNative, verify_mechanism_native_evidence,
)
from agent_economic_trust.mechanism_plan import case_for_episode, make_schedule
from agent_economic_trust.mechanism_task import BonusProposal, ClaimSubmission


def _save_tamper(directory: Path, original: dict, edit) -> Path:
    copy = deepcopy(original)
    edit(copy)
    path = directory / "tampered.json"
    path.write_bytes(json.dumps(copy, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False).encode() + b"\n")
    return path


def _native_case(directory: Path, *, arm: str, truth: int, amount: int = 1) -> Path:
    row = next(item for item in make_schedule("a" * 64)
               if item.arm == arm and item.truth == truth)
    case, artifact = case_for_episode(row)
    with MechanismNative(row, directory / "native",
                         assignment_manifest_sha256="b" * 64) as native:
        obligation = native.open_job()
        native.submit_claim(ClaimSubmission(
            row.episode_id, case.task_id, obligation, artifact, "test-submission"))
        if arm == "DIRECT_OFFER_CAPABILITY":
            native.fund_bonus(BonusProposal(
                row.episode_id, case.task_id, obligation, amount, "test-proposal"))
        native.settle_job("ACCEPT" if truth else "REJECT", row.artifact_digest)
        return native.save_evidence()


class MechanismNativeReceiptTests(unittest.TestCase):
    def test_two_assigned_chains_have_distinct_genesis_and_wallets(self) -> None:
        with TemporaryDirectory(prefix="mechanism-native-test-") as temporary:
            directory = Path(temporary)
            first = json.loads(_native_case(
                directory / "first", arm="DIRECT_NEUTRAL", truth=0).read_bytes())
            second = json.loads(_native_case(
                directory / "second", arm="DIRECT_NEUTRAL", truth=1).read_bytes())
            self.assertNotEqual(first["chain"]["genesis_block_hash"],
                                second["chain"]["genesis_block_hash"])
            self.assertNotEqual(first["chain"]["genesis_timestamp"],
                                second["chain"]["genesis_timestamp"])
            self.assertTrue(set(a.lower() for a in first["chain"]["distinct_wallet_addresses"])
                              .isdisjoint(a.lower() for a in
                                          second["chain"]["distinct_wallet_addresses"]))
            tampered = _save_tamper(directory, first,
                                   lambda data: data["chain"].update(genesis_timestamp=0))
            with self.assertRaisesRegex(ValueError, "chain|genesis"):
                verify_mechanism_native_evidence(tampered)

    def test_offer_one_minor_unit_true_native_receipt_and_immutable_collision(self) -> None:
        with TemporaryDirectory(prefix="mechanism-native-test-") as temporary:
            directory = Path(temporary)
            path = _native_case(directory, arm="DIRECT_OFFER_CAPABILITY", truth=1, amount=1)
            verified = verify_mechanism_native_evidence(path)
            self.assertEqual(verified["job_status"], "Completed")
            self.assertEqual(verified["bonus_status"], "RELEASED")
            self.assertEqual(verified["bonus_amount_minor_units"], 1)
            self.assertEqual(verified["audit_fee_minor_units"], 2_000_000)
            self.assertEqual(verified["audit_fee_payer_role"], "provider")
            self.assertTrue(verified["submission_tx_hash"])
            original = json.loads(path.read_bytes())
            tampered = _save_tamper(directory, original,
                                   lambda data: data["submission"].update(transaction_index=0))
            with self.assertRaisesRegex(ValueError, "submission"):
                verify_mechanism_native_evidence(tampered)
            tampered = _save_tamper(directory, original,
                                   lambda data: data["bonus"].update(deployed_runtime_code="0x00"))
            with self.assertRaisesRegex(ValueError, "runtime"):
                verify_mechanism_native_evidence(tampered)

    def test_neutral_bad_provider_fee_and_refund_without_bonus(self) -> None:
        with TemporaryDirectory(prefix="mechanism-native-test-") as temporary:
            directory = Path(temporary)
            path = _native_case(directory, arm="DIRECT_NEUTRAL", truth=0)
            verified = verify_mechanism_native_evidence(path)
            self.assertEqual(verified["job_status"], "Rejected")
            self.assertEqual(verified["provider_payout_minor_units"], 0)
            self.assertEqual(verified["bonus_status"], "UNFUNDED")
            original = json.loads(path.read_bytes())
            tampered = _save_tamper(directory, original,
                                   lambda data: data["funding"]["audit_fee"].update(amount_minor=1))
            with self.assertRaisesRegex(ValueError, "audit fee"):
                verify_mechanism_native_evidence(tampered)
            tampered = _save_tamper(directory, original,
                                   lambda data: data["settlement"].update(verdict="ACCEPT"))
            with self.assertRaisesRegex(ValueError, "settlement|status|verdict"):
                verify_mechanism_native_evidence(tampered)

    def test_failure_preserves_partial_native_receipts_before_chain_exit(self) -> None:
        with TemporaryDirectory(prefix="mechanism-native-test-") as temporary:
            directory = Path(temporary)
            row = make_schedule("a" * 64)[0]
            with self.assertRaisesRegex(RuntimeError, "scripted interruption"):
                with MechanismNative(row, directory / "native",
                                     assignment_manifest_sha256="b" * 64) as native:
                    native.open_job()
                    raise RuntimeError("scripted interruption")
            saved = json.loads((directory / "native" / "partial_evidence.json").read_bytes())
            self.assertIs(saved["complete_payment_claim"], False)
            self.assertIs(saved["rpc_live_at_capture"], True)
            self.assertEqual(saved["observed_job"]["status"], "Funded")
            self.assertTrue(saved["raw_transactions"])
            self.assertTrue(all(value is not None for value in saved["observed_receipts"].values()))


if __name__ == "__main__":
    unittest.main()
