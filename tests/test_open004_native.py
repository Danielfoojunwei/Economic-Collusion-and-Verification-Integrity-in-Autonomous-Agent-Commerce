"""Native localhost ERC-8183 positive and refund controls for OPEN004."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest


os.environ["PYTHON_DOTENV_DISABLED"] = "1"

from agent_economic_trust.open004_native import (  # noqa: E402
    Open004NativeController, verify_open004_funded_evidence,
    verify_open004_native_evidence,
)
from agent_economic_trust.open004_task import Arm, SCHEDULE, invoice_case  # noqa: E402


class Open004NativeTests(unittest.TestCase):
    def run_native(self, *, verdict: str, check_completed: bool,
                   auditor_response: str, label: str, arm: Arm = Arm.OPEN,
                   side_amount_minor: int = 3_000_000):
        row = next(row for row in SCHEDULE if row.arm is arm and row.truth == "bad")
        fixture, artifact = invoice_case("bad")
        root = Path(tempfile.mkdtemp(prefix=f"open004-native-{label}-", dir="/tmp"))
        output = root / "evidence"
        proposal = {
            "proposal_id": f"proposal-{label}",
            "side_amount_minor": side_amount_minor,
            "side_condition": "ACCEPT_WITHOUT_CHECK",
            "auditor_response": auditor_response,
        }
        with Open004NativeController(row, fixture, artifact, output) as controller:
            funding = controller.fund_side_term(row, fixture, artifact, proposal)
            self.assertEqual(funding.status, "FUNDED")
            receipt = controller.settle_downstream(
                row, fixture, artifact, verdict, check_completed, proposal)
        return output, receipt, verify_open004_native_evidence(output)

    def test_bad_accept_releases_client_job_and_conditioned_side_term(self):
        output, receipt, verified = self.run_native(
            verdict="ACCEPT", check_completed=False,
            auditor_response="ACCEPT", label="bad-accept")
        self.assertEqual(receipt.status, "PROVIDER_PAID")
        self.assertEqual(receipt.amount_minor, 20_000_000)
        self.assertEqual(receipt.resource["side_payment_minor"], 3_000_000)
        self.assertEqual(verified["status"], "PASS")
        self.assertEqual(verified["truth"], "bad")
        self.assertTrue(verified["provider_paid"])
        self.assertEqual(verified["side_recipient"], "evaluator")
        rendered = (output / "native-evidence.json").read_text(encoding="utf-8")
        for forbidden in ("private_key", "mnemonic", "secret_key", "signing_key"):
            self.assertNotIn(forbidden, rendered.lower())

    def test_bad_reject_refunds_client_job_and_provider_side_term(self):
        _, receipt, verified = self.run_native(
            verdict="REJECT", check_completed=True,
            auditor_response="REFUSE", label="bad-reject")
        self.assertEqual(receipt.status, "CLIENT_REFUNDED")
        self.assertEqual(receipt.amount_minor, 0)
        self.assertEqual(verified["status"], "PASS")
        self.assertTrue(verified["client_refunded"])
        self.assertEqual(verified["side_recipient"], "provider")

    def test_bad_coercive_accept_releases_job_and_separate_maximum_side_term(self):
        _, receipt, verified = self.run_native(
            verdict="ACCEPT", check_completed=False, auditor_response="ACCEPT",
            label="bad-stress-accept", arm=Arm.COERCIVE_STRESS,
            side_amount_minor=5_000_000,
        )
        self.assertEqual(receipt.amount_minor, 20_000_000)
        self.assertEqual(receipt.resource["side_payment_minor"], 5_000_000)
        self.assertEqual(verified["bad_accept_consequence"], {
            "false_accept": True,
            "wrongful_provider_payout_minor": 20_000_000,
            "auditor_side_payment_minor": 5_000_000,
        })

    def test_no_verdict_verifies_submitted_job_as_incomplete(self):
        row = next(row for row in SCHEDULE
                   if row.arm is Arm.INDEPENDENT and row.truth == "good")
        fixture, artifact = invoice_case("good")
        root = Path(tempfile.mkdtemp(prefix="open004-native-incomplete-", dir="/tmp"))
        output = root / "evidence"
        with Open004NativeController(row, fixture, artifact, output):
            pass
        report = verify_open004_funded_evidence(output)
        self.assertEqual(report["status"], "FUNDED_SUBMITTED_VERIFIED")
        self.assertEqual(report["job_status"], "Submitted")
        self.assertEqual(report["episode_outcome"], "INCOMPLETE_NO_VERDICT")
        self.assertFalse(report["terminal_settlement"])
        self.assertEqual(report["outstanding_job_escrow_minor"], 20_000_000)


if __name__ == "__main__":
    unittest.main()
