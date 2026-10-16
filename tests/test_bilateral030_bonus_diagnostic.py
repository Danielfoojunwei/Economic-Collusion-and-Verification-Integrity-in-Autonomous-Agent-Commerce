"""Receipt tamper checks for the read-only BILATERAL030 trigger diagnostic."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.diagnose_bilateral030_bonus import PARTIAL, SIDE, diagnose, verify_partial_record


class Bilateral030BonusDiagnosticTest(unittest.TestCase):
    def test_separate_archives_are_explicit(self) -> None:
        result = diagnose()
        self.assertEqual(result["status"], "SEPARATE_SOURCE_AND_RECEIPTS_VERIFIED")
        self.assertFalse(result["same_job_joint_bonus_control"])
        self.assertEqual(result["early_funded_bonus_treatment"], "HOLD_UNIMPLEMENTED")
        self.assertEqual(result["partial_receipt"]["first_provider_paid_minor"], 9_000_000)
        self.assertEqual(result["partial_receipt"]["first_evaluator_fee_minor"], 1_000_000)
        self.assertEqual(result["separate_terminal_bonus_receipt"]["provider_bonus_refund_minor"],
                         5_000_000)

    def test_wrong_early_payee_in_raw_transfer_is_rejected(self) -> None:
        evidence = copy.deepcopy(json.loads(PARTIAL.read_text()))
        tx = next(tx for tx in evidence["transactions"] if tx["step"] == "claim.approve")
        tx["raw_receipt"]["logs"][2]["topics"][2] = tx["raw_receipt"]["logs"][0]["topics"][2]
        with self.assertRaisesRegex(ValueError, "token transfer"):
            verify_partial_record(evidence)

    def test_wrong_bonus_refund_recipient_is_rejected(self) -> None:
        evidence = json.loads(SIDE.read_text())
        evidence["scenarios"]["rejected"]["bonus_recipient"] = "evaluator"
        with TemporaryDirectory() as temp:
            path = Path(temp) / "side.json"
            path.write_text(json.dumps(evidence))
            with self.assertRaises(ValueError):
                diagnose(side_path=path)


if __name__ == "__main__":
    unittest.main()
