"""Independent negative replay of real local ERC-8183 milestone receipts."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from agent_economic_trust.partial_claim_native import PartialClaimNativeController
from agent_economic_trust.partial_claim_native_verifier import verify_file, verify_record
from agent_economic_trust.partial_claim_plan import (CLIENT_PREPAID, NATIVE_CONTINGENT,
                                                     PartialClaimRow)


class PartialClaimVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="partial-claim-verifier-")
        base = Path(cls.tmp.name)
        cls.records = {}
        cases = (
            ("native_approved", NATIVE_CONTINGENT, "APPROVE", True, True),
            ("prepaid_approved", CLIENT_PREPAID, "APPROVE", False, True),
            ("native_deferred", NATIVE_CONTINGENT, "DEFER", False, True),
            ("native_interrupted", NATIVE_CONTINGENT, "APPROVE", True, False),
            ("native_pending", NATIVE_CONTINGENT, None, True, False),
        )
        for label, fee, early, checked, terminal in cases:
            row = PartialClaimRow("test-" + label, "invoice-test-" + label,
                                  "bad", fee, "NO_CONTACT")
            destination = base / label
            with PartialClaimNativeController(row, destination) as native:
                native.file_claim(row)
                if checked:
                    native.buy_check(row, "check-" + label)
                if early is not None:
                    native.early_decide(row, early)
                if terminal:
                    native.reveal_final(row)
                    native.finalize(row, "REJECT")
            evidence = destination / ("native-evidence.json" if terminal
                                      else "native-partial.json")
            cls.records[label] = (row, evidence, json.loads(evidence.read_text()))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_approved_bad_claim_survives_final_rejection(self) -> None:
        row, path, _ = self.records["native_approved"]
        result = verify_file(path, row)
        self.assertEqual(result["status"], "COMPLETE_VERIFIED")
        self.assertEqual(result["first_provider_paid_minor"], 9_000_000)
        self.assertEqual(result["first_evaluator_fee_minor"], 1_000_000)
        self.assertEqual(result["client_refund_minor"], 10_000_000)
        self.assertEqual(result["cumulative_client_outlay_minor"], 10_000_000)
        self.assertEqual(result["terminal_verdict"], "REJECT")

    def test_prepay_and_defer_have_distinct_economics(self) -> None:
        prepaid = verify_file(self.records["prepaid_approved"][1])
        deferred = verify_file(self.records["native_deferred"][1])
        self.assertEqual((prepaid["first_provider_paid_minor"],
                          prepaid["first_evaluator_fee_minor"],
                          prepaid["cumulative_client_outlay_minor"]),
                         (9_000_000, 0, 11_000_000))
        self.assertEqual((deferred["first_provider_paid_minor"],
                          deferred["client_refund_minor"],
                          deferred["cumulative_client_outlay_minor"]),
                         (0, 20_000_000, 0))

    def test_paid_prefix_is_verified_without_a_terminal_claim(self) -> None:
        row, path, record = self.records["native_interrupted"]
        result = verify_file(path, row)
        self.assertEqual(result["status"], "PARTIAL_NATIVE_VERIFIED")
        self.assertEqual(result["first_provider_paid_minor"], 9_000_000)
        self.assertEqual(result["escrow_remaining_minor"], 10_000_000)
        self.assertIsNone(result["terminal_verdict"])
        tampered = deepcopy(record)
        tampered["native_final_claim"] = True
        with self.assertRaises(ValueError):
            verify_record(tampered, row)

    def test_submitted_claim_with_paid_check_and_no_decision_is_partial(self) -> None:
        row, path, record = self.records["native_pending"]
        result = verify_file(path, row)
        self.assertEqual(result["status"], "PARTIAL_NATIVE_VERIFIED")
        self.assertEqual(result["first_provider_paid_minor"], 0)
        self.assertEqual(result["escrow_remaining_minor"], 20_000_000)
        self.assertIsNone(result["terminal_verdict"])
        tampered = deepcopy(record)
        tampered["final_verdict"] = "REJECT"
        with self.assertRaisesRegex(ValueError, "pending claim has no early decision"):
            verify_record(tampered, row)

    def test_rejects_wrong_assignment_and_claim_binding(self) -> None:
        row, _, record = self.records["native_approved"]
        wrong = PartialClaimRow(row.episode_id, row.obligation_id + "-other",
                                row.truth, row.fee_term, row.contact)
        with self.assertRaises(ValueError):
            verify_record(record, wrong)
        for field, value in (("job_id", 2),
                             ("obligation_id", "invoice-other"),
                             ("proof_hash", "0" * 64),
                             ("pending_claim_hash", "0x" + "00" * 32)):
            tampered = deepcopy(record)
            tampered["claim_binding"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_record(tampered, row)

    def test_rejects_raw_transaction_and_event_tamper(self) -> None:
        row, _, record = self.records["native_approved"]
        for step, part, mutate in (
            ("claim.approve", "raw_transaction", lambda t: t.update({"from": record["actors"]["provider"]})),
            ("claim.submit", "raw_transaction", lambda t: t.update({"input": "0xdeadbeef"})),
            ("job.reject", "raw_receipt", lambda t: t.update({"status": "0x0"})),
        ):
            tampered = deepcopy(record)
            tx = next(t for t in tampered["transactions"] if t["step"] == step)
            mutate(tx[part])
            with self.subTest(step=step, part=part), self.assertRaises(ValueError):
                verify_record(tampered, row)
        tampered = deepcopy(record)
        tx = next(t for t in tampered["transactions"] if t["step"] == "claim.approve")
        log = next(x for x in tx["raw_receipt"]["logs"]
                   if x["topics"][0].lower() ==
                   next(y["topics"][0].lower() for y in tx["logs"]
                        if y["name"] == "ClaimApproved"))
        log["topics"][0] = "0x" + "00" * 32
        with self.assertRaises(ValueError):
            verify_record(tampered, row)

    def test_rejects_forged_callback_or_balance(self) -> None:
        row, _, record = self.records["native_approved"]
        for path, value in ((('early_receipt', 'provider_paid_minor'), 0),
                            (('final_receipt', 'client_refund_minor'), 20_000_000),
                            (('final', 'balances_minor_units', 'client'), 42)):
            tampered = deepcopy(record)
            current = tampered
            for key in path[:-1]:
                current = current[key]
            current[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(ValueError):
                verify_record(tampered, row)


if __name__ == "__main__":
    unittest.main()
