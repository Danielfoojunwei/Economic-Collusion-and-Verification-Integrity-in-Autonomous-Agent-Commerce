"""Boundary tests for the scripted AP2 purchase/invoice decision adapter."""

from __future__ import annotations

import unittest

from agent_economic_trust.ap2_invoice_control import dispatch_invoice_verdict
from agent_economic_trust.core import OracleStatus


class Ap2InvoiceControlTests(unittest.TestCase):
    def test_valid_purchase_does_not_certify_bad_invoice_under_guard(self):
        self.assertEqual(dispatch_invoice_verdict(
            requested_verdict="ACCEPT", ap2_purchase_authorized=True,
            oracle_status=OracleStatus.FAIL, strict=False), "ACCEPT")
        self.assertEqual(dispatch_invoice_verdict(
            requested_verdict="ACCEPT", ap2_purchase_authorized=True,
            oracle_status=OracleStatus.FAIL, strict=True), "REJECT")

    def test_good_invoice_can_be_paid_under_both_adapters(self):
        for strict in (False, True):
            self.assertEqual(dispatch_invoice_verdict(
                requested_verdict="ACCEPT", ap2_purchase_authorized=True,
                oracle_status=OracleStatus.PASS, strict=strict), "ACCEPT")

    def test_missing_authorization_and_inconclusive_oracle_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "authorization was not verified"):
            dispatch_invoice_verdict(
                requested_verdict="ACCEPT", ap2_purchase_authorized=False,
                oracle_status=OracleStatus.PASS, strict=True)
        with self.assertRaisesRegex(ValueError, "conclusive independent oracle"):
            dispatch_invoice_verdict(
                requested_verdict="ACCEPT", ap2_purchase_authorized=True,
                oracle_status=OracleStatus.INCONCLUSIVE, strict=True)
        with self.assertRaisesRegex(ValueError, "invalid scripted verdict"):
            dispatch_invoice_verdict(
                requested_verdict="APPROVE", ap2_purchase_authorized=True,
                oracle_status=OracleStatus.PASS, strict=True)


if __name__ == "__main__":
    unittest.main()
