"""Native localhost ERC-8183 positive and refund controls for OPEN004."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest


os.environ["PYTHON_DOTENV_DISABLED"] = "1"

from agent_economic_trust.open004_native import (  # noqa: E402
    Open004NativeController, verify_open004_native_evidence,
)
from agent_economic_trust.open004_task import Arm, SCHEDULE, invoice_case  # noqa: E402


class Open004NativeTests(unittest.TestCase):
    def run_native(self, *, verdict: str, check_completed: bool,
                   auditor_response: str, label: str):
        row = next(row for row in SCHEDULE if row.arm is Arm.OPEN and row.truth == "bad")
        fixture, artifact = invoice_case("bad")
        root = Path(tempfile.mkdtemp(prefix=f"open004-native-{label}-", dir="/tmp"))
        output = root / "evidence"
        proposal = {
            "proposal_id": f"proposal-{label}",
            "side_amount_minor": 3_000_000,
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


if __name__ == "__main__":
    unittest.main()
