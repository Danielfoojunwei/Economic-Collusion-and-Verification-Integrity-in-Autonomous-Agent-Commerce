"""Truth isolation and full-block budget checks for prospective x402 study."""

from dataclasses import replace
from decimal import Decimal
import unittest

from agent_economic_trust.x402_audit_retainer import (
    AUDITOR_WALLET, FEE_MINOR, RetainerAssignment, digest, intake_body,
    public_receipt, public_report,
)
from scripts.preview_x402_retainer import price_preview
from scripts.run_x402_retainer_offline import rows


class RetainerDesignTests(unittest.TestCase):
    def setUp(self):
        self.row = RetainerAssignment("x402010-test-row-a1", "invoice-test-obligation-a1",
                                      "good", "provider")

    def test_public_receipt_and_report_do_not_leak_truth(self):
        bad = replace(self.row, truth="bad")
        self.assertEqual(public_report(self.row), public_report(bad))
        self.assertEqual(intake_body(self.row), intake_body(bad))
        body = intake_body(self.row)
        self.assertEqual(body["acknowledgment"], "PAID_INTAKE_ONLY")
        self.assertIs(body["proves_invoice_quality"], False)
        self.assertIsNone(body["audit_verdict"])
        self.assertNotIn("expected_amount_cents", body)
        verified = {"status": "PASS", "protocol_settled": True,
                    "payer_role": "provider", "payee": AUDITOR_WALLET,
                    "amount_minor_units": FEE_MINOR, "body_sha256": digest(body),
                    "transaction_hash": "0x" + "12" * 32}
        receipt = public_receipt(self.row, verified)
        self.assertIs(receipt["proves_invoice_quality"], False)
        self.assertNotIn("truth", receipt)
        self.assertNotIn("signature", receipt)

    def test_receipt_fails_closed_on_other_payer_or_body(self):
        body = intake_body(self.row)
        verified = {"status": "PASS", "protocol_settled": True,
                    "payer_role": "provider", "payee": AUDITOR_WALLET,
                    "amount_minor_units": FEE_MINOR, "body_sha256": digest(body),
                    "transaction_hash": "0x" + "12" * 32}
        for field, value in (("payer_role", "buyer"), ("payee", "0x" + "22" * 20),
                             ("amount_minor_units", FEE_MINOR + 1),
                             ("body_sha256", "0" * 64),
                             ("protocol_settled", False)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                public_receipt(self.row, {**verified, field: value})

    def test_assignment_and_matrix_bounds(self):
        self.assertEqual({(r.truth, r.payer_role) for r in rows()},
                         {("good", "provider"), ("bad", "provider"),
                          ("good", "buyer"), ("bad", "buyer")})
        self.assertEqual(len({r.obligation_id for r in rows()}), 4)
        for change in ({"truth": "maybe"}, {"payer_role": "auditor"},
                       {"obligation_id": "bad/invoice"}):
            with self.assertRaises(ValueError):
                replace(self.row, **change).validate()

    def test_historical_full_block_is_a_preview_not_authorization(self):
        preview = price_preview(refresh=False)
        self.assertEqual(Decimal(preview["full_new_block_usd"]),
                         Decimal("23.4958422"))
        self.assertEqual(preview["rows"], 4)
        self.assertIn("HISTORICAL", preview["price_origin"])


if __name__ == "__main__":
    unittest.main()
