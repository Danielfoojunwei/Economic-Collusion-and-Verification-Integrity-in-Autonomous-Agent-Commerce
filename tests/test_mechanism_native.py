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
from agent_economic_trust.debit_pilot_plan import (
    case_for_episode as debit_case_for_episode, make_schedule as make_debit_schedule,
)
from agent_economic_trust.mechanism_task import BonusProposal, ClaimSubmission


def _save_tamper(directory: Path, original: dict, edit) -> Path:
    copy = deepcopy(original)
    edit(copy)
    path = directory / "tampered.json"
    path.write_bytes(json.dumps(copy, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False).encode() + b"\n")
    return path


def _native_case(directory: Path, *, arm: str, truth: int, amount: int = 1,
                 check_debit_condition: str | None = None,
                 invoke_check: bool = True) -> Path:
    row = next(item for item in make_schedule("a" * 64)
               if item.arm == arm and item.truth == truth)
    case, artifact = case_for_episode(row)
    with MechanismNative(row, directory / "native",
                         assignment_manifest_sha256="b" * 64,
                         check_debit_condition=check_debit_condition) as native:
        obligation = native.open_job()
        native.submit_claim(ClaimSubmission(
            row.episode_id, case.task_id, obligation, artifact, "test-submission"))
        if arm == "DIRECT_OFFER_CAPABILITY":
            native.fund_bonus(BonusProposal(
                row.episode_id, case.task_id, obligation, amount, "test-proposal"))
        if check_debit_condition and invoke_check:
            native.charge_check("test-check")
        native.settle_job("ACCEPT" if truth else "REJECT", row.artifact_digest)
        return native.save_evidence()


class MechanismNativeReceiptTests(unittest.TestCase):
    def test_bad_claim_wrong_accept_releases_five_million_bonus_after_d1_debit(self) -> None:
        """Positive control for the 003 wrongful-settlement payment path."""
        row = next(item for item in make_debit_schedule("a" * 64)
                   if item.cell == "BAD-DIRECT-B1-D1")
        self.assertEqual(row.truth, 0)
        self.assertEqual(row.bonus_minor_units, 5_000_000)
        case, artifact = debit_case_for_episode(row)
        with TemporaryDirectory(prefix="mechanism-native-positive-control-") as temporary:
            directory = Path(temporary)
            with MechanismNative(row, directory / "native",
                                 assignment_manifest_sha256="b" * 64,
                                 check_debit_condition="D1") as native:
                obligation = native.open_job()
                native.submit_claim(ClaimSubmission(
                    row.episode_id, case.task_id, obligation, artifact,
                    "positive-control-submission"))
                native.fund_bonus(BonusProposal(
                    row.episode_id, case.task_id, obligation, 5_000_000,
                    "positive-control-assigned-bonus"))
                debit_receipt = native.charge_check("positive-control-check")
                self.assertEqual(debit_receipt.amount_minor, 1_000_000)
                self.assertTrue(debit_receipt.transfer_verified)
                native.settle_job("ACCEPT", row.artifact_digest)  # deliberately wrong for BAD
                evidence = native.save_evidence()

            verified = verify_mechanism_native_evidence(evidence)
            saved = json.loads(evidence.read_bytes())
            roles = {name: address.lower() for name, address in saved["roles"].items()}
            self.assertEqual((verified["verdict"], verified["job_status"]),
                             ("ACCEPT", "Completed"))
            self.assertEqual(verified["provider_payout_minor_units"], 20_000_000)
            self.assertEqual(verified["bonus_status"], "RELEASED")
            self.assertEqual(verified["bonus_amount_minor_units"], 5_000_000)
            self.assertEqual(verified["bonus_recipient"], roles["evaluator"])
            self.assertEqual(verified["check_debit_condition"], "D1")
            self.assertEqual(verified["check_debit_minor_units"], 1_000_000)
            self.assertEqual(verified["check_debit_sink_address"].lower(),
                             roles["outsider"])
            self.assertEqual(verified["check_debit_tx_hash"],
                             debit_receipt.transaction_hash)
            self.assertLess(saved["submission"]["transaction_index"],
                            saved["bonus"]["transaction_start_index"])
            self.assertLess(saved["bonus"]["funding_transaction_end_index"] - 1,
                            saved["check_debit"]["transaction_index"])
            self.assertLess(saved["check_debit"]["transaction_index"],
                            saved["settlement"]["transaction_start_index"])
            before = saved["check_debit"]["balances_before"]["balances_minor_units"]
            after = saved["check_debit"]["balances_after"]["balances_minor_units"]
            self.assertEqual(after[roles["evaluator"]] - before[roles["evaluator"]],
                             -1_000_000)
            self.assertEqual(after[roles["outsider"]] - before[roles["outsider"]],
                             1_000_000)
            final = saved["final_balances"]
            self.assertEqual(sum(final["balances_minor_units"].values()),
                             final["total_supply_minor_units"])

    def test_assigned_check_debit_d0_d1_and_skip_have_separate_native_proofs(self) -> None:
        with TemporaryDirectory(prefix="mechanism-native-test-") as temporary:
            directory = Path(temporary)
            for condition in ("D0", "D1"):
                with self.subTest(condition=condition):
                    path = _native_case(directory / condition, arm="DIRECT_NEUTRAL",
                                        truth=0, check_debit_condition=condition)
                    summary = verify_mechanism_native_evidence(path)
                    self.assertTrue(summary["check_invoked"])
                    self.assertEqual(summary["check_debit_minor_units"],
                                     1_000_000 if condition == "D1" else 0)
                    self.assertEqual(bool(summary["check_debit_tx_hash"]),
                                     condition == "D1")
                    saved = json.loads(path.read_bytes())
                    if condition == "D1":
                        tampered = _save_tamper(directory, saved,
                            lambda data: data["check_debit"].update(amount_minor=1))
                        with self.assertRaisesRegex(ValueError, "check debit"):
                            verify_mechanism_native_evidence(tampered)
                        tampered = _save_tamper(directory, saved,
                            lambda data: data["check_debit"].update(
                                sink_address=data["roles"]["provider"]))
                        with self.assertRaisesRegex(ValueError, "check debit"):
                            verify_mechanism_native_evidence(tampered)
                    else:
                        tampered = _save_tamper(directory, saved,
                            lambda data: data["check_debit"].update(
                                verification_sha256="0" * 64))
                        with self.assertRaisesRegex(ValueError, "D0"):
                            verify_mechanism_native_evidence(tampered)
            skipped = _native_case(directory / "skipped", arm="DIRECT_NEUTRAL",
                                   truth=0, check_debit_condition="D1",
                                   invoke_check=False)
            summary = verify_mechanism_native_evidence(skipped)
            self.assertFalse(summary["check_invoked"])
            self.assertIsNone(summary["check_debit_tx_hash"])

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
