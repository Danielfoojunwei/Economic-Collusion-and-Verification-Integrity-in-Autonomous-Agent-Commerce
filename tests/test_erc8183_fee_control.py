"""Native zero-model ERC-8183 fee economics and independent evidence negatives."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from verify_erc8183_fee_control import verify_directory, verify_record


class FeeNativeControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="erc8183-fee-control-")
        cls.output = Path(cls.tmp.name) / "native"
        subprocess.run([sys.executable, str(ROOT / "scripts/run_erc8183_fee_control.py"),
                        "--output", str(cls.output)], cwd=ROOT, check=True,
                       capture_output=True, text=True, timeout=120)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def load(self, name: str) -> dict:
        return json.loads((self.output / name / "evidence.json").read_text())

    def test_all_nine_native_cases_and_balances(self) -> None:
        report = verify_directory(self.output)
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["live_agent_collusion_evidence"])
        self.assertEqual(len(report["cases"]), 9)
        by_case = {row["case"]: row for row in report["cases"]}
        for arm in ("native_contingent", "client_prepaid"):
            self.assertEqual(by_case[f"{arm}-good-checked-accept"]["provider_gain_minor"], 18_000_000)
            self.assertEqual(by_case[f"{arm}-bad-unchecked-accept"]["provider_gain_minor"], 18_000_000)
            self.assertEqual(by_case[f"{arm}-bad-checked-reject"]["provider_gain_minor"], 0)
        self.assertEqual(by_case["native_contingent-bad-checked-reject"]["client_loss_minor"], 0)
        self.assertEqual(by_case["client_prepaid-bad-checked-reject"]["client_loss_minor"], 2_000_000)
        self.assertEqual(by_case["native-bad-prior-claim-reject"]["client_loss_minor"], 5_000_000)
        self.assertTrue(by_case["native-bad-prior-claim-reject"]["prior_claim_blocked"])

    def test_fail_closed_if_primary_row_contains_prior_settlement(self) -> None:
        evidence = self.load("native_contingent-good-checked-accept")
        evidence["preterminal_job"]["settled_amount_minor_units"] = 5_000_000
        with self.assertRaisesRegex(ValueError, "prior settlement"):
            verify_record(evidence)

    def test_fail_closed_if_prior_claim_fee_is_misattributed_to_reject(self) -> None:
        evidence = self.load("native-bad-prior-claim-reject")
        evidence["guard"] = "PASS"
        with self.assertRaisesRegex(ValueError, "prior claim not blocked"):
            verify_record(evidence)

    def test_fail_closed_on_native_fee_or_prepay_tampering(self) -> None:
        fee = self.load("native_contingent-good-checked-accept")
        terminal = next(tx for tx in fee["transactions"] if tx["step"] == "job.complete")
        event = next(log for log in terminal["raw_receipt"]["logs"]
                     if log["data"].lower() == "0x" + format(2_000_000, "064x"))
        event["data"] = "0x" + format(3_000_000, "064x")
        with self.assertRaisesRegex(ValueError, "raw log differs"):
            verify_record(fee)
        prepaid = self.load("client_prepaid-bad-checked-reject")
        prepay = next(tx for tx in prepaid["transactions"] if tx["step"] == "terms.client_prepay")
        prepay["raw_transaction"]["from"] = prepaid["actors"]["provider"]
        with self.assertRaisesRegex(ValueError, "raw transaction/receipt differs"):
            verify_record(prepaid)

    def test_fail_closed_on_wrong_verdict_or_hidden_truth_claim(self) -> None:
        evidence = self.load("native_contingent-bad-checked-reject")
        evidence["case"]["truth"] = "good"
        with self.assertRaisesRegex(ValueError, "case label and assignment differ"):
            verify_record(evidence)
        evidence = self.load("native_contingent-bad-checked-reject")
        evidence["invoice"]["buyer_records"]["purchase_order_amount_cents"] = 400
        with self.assertRaisesRegex(ValueError, "private invoice"):
            verify_record(evidence)

    def test_existing_native_output_cannot_be_overwritten(self) -> None:
        result = subprocess.run([sys.executable, str(ROOT / "scripts/run_erc8183_fee_control.py"),
                                 "--output", str(self.output)], cwd=ROOT,
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to overwrite native evidence", result.stderr)


if __name__ == "__main__":
    unittest.main()
