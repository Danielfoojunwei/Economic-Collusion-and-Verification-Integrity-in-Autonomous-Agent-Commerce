"""Native payout custody control and receipt-tampering negatives."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from verify_erc8183_receiver_control import verify_directory, verify_record


class ReceiverControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="erc8183-receiver-")
        cls.output = Path(cls.temp.name) / "native"
        subprocess.run([sys.executable, str(ROOT / "scripts/run_erc8183_receiver_control.py"),
                        "--output", str(cls.output)], cwd=ROOT, check=True,
                       capture_output=True, text=True, timeout=120)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def record(self, name: str) -> dict:
        return json.loads((self.output / name / "evidence.json").read_text())

    def test_three_fixed_cases_replay_from_raw_receipts(self) -> None:
        report = verify_directory(self.output)
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["live_agent_collusion_evidence"])
        self.assertEqual([(r["case"], r["provider_delta_minor"], r["evaluator_delta_minor"])
                          for r in report["cases"]],
                         [("direct-approve", 18_000_000, 2_000_000),
                          ("evaluator-receiver-approve", 0, 20_000_000),
                          ("evaluator-receiver-reject", 0, 0)])

    def test_receiver_assignment_calldata_cannot_be_relabelled(self) -> None:
        record = self.record("evaluator-receiver-approve")
        assignment = next(tx for tx in record["transactions"]
                          if tx["step"] == "job.assign_evaluator_receiver")
        # The second 32-byte argument is the receiver, not the evaluator's identity label.
        assignment["raw_transaction"]["input"] = assignment["raw_transaction"]["input"][:-40] + record["actors"]["provider"][2:].lower()
        with self.assertRaisesRegex(ValueError, "calldata argument 1"):
            verify_record(record)

    def test_reverted_guard_cannot_be_forged_as_success(self) -> None:
        record = self.record("evaluator-receiver-approve")
        guard = next(tx for tx in record["transactions"] if tx["step"] == "guard.same_nominal_role")
        guard["raw_receipt"]["status"] = "0x1"
        guard["status"] = guard["expected_status"] = 1
        with self.assertRaisesRegex(ValueError, "raw transaction or receipt"):
            verify_record(record)

    def test_completion_payee_and_amount_cannot_be_relabelled(self) -> None:
        original = self.record("evaluator-receiver-approve")
        record = deepcopy(original)
        terminal = next(tx for tx in record["transactions"] if tx["step"] == "job.complete")
        release = next(log for log in terminal["raw_receipt"]["logs"] if int(log["data"], 16) == 18_000_000)
        release["topics"][2] = "0x" + "0" * 24 + record["actors"]["provider"][2:].lower()
        with self.assertRaisesRegex(ValueError, "saved event differs from raw receipt"):
            verify_record(record)
        record = deepcopy(original)
        terminal = next(tx for tx in record["transactions"] if tx["step"] == "job.complete")
        release = next(log for log in terminal["raw_receipt"]["logs"] if int(log["data"], 16) == 18_000_000)
        release["data"] = "0x" + format(17_000_000, "064x")
        with self.assertRaisesRegex(ValueError, "saved event differs from raw receipt"):
            verify_record(record)

    def test_rejection_cannot_be_misreported_as_a_paid_job(self) -> None:
        record = self.record("evaluator-receiver-reject")
        record["final"]["balances_minor_units"]["evaluator"] = 20_000_000
        with self.assertRaisesRegex(ValueError, "final: balances disagree"):
            verify_record(record)

    def test_existing_native_output_cannot_be_overwritten(self) -> None:
        result = subprocess.run([sys.executable, str(ROOT / "scripts/run_erc8183_receiver_control.py"),
                                 "--output", str(self.output)], cwd=ROOT,
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to overwrite native receiver evidence", result.stderr)


if __name__ == "__main__":
    unittest.main()
