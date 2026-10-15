"""Negative handoff and upstream-schema checks for the ACP mock control."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import unittest

from jsonschema import ValidationError

from protocols.acp_retail.audit_handoff_control import (
    dispatch_invoice_verdict, execute_mock_checkout, intent_reference,
    validate_mock_checkout,
)
from scripts.run_acp_audit_handoff_control import ACP_UPSTREAM


@unittest.skipUnless(
    (ACP_UPSTREAM / "spec/2026-04-17/json-schema/schema.agentic_checkout.json").is_file(),
    "pinned ACP schema not installed")
class AcpAuditHandoffControlTests(unittest.TestCase):
    def setUp(self):
        self.a_digest = sha256(b"report-a").hexdigest()
        self.b_digest = sha256(b"report-b").hexdigest()
        self.checkout_a = execute_mock_checkout(
            ACP_UPSTREAM, obligation_id="obligation-a", artifact_digest=self.a_digest)

    def test_mock_order_is_schema_valid_and_reference_is_intent_bound(self):
        summary = validate_mock_checkout(self.checkout_a, ACP_UPSTREAM)
        self.assertEqual(summary["client_reference_id"], intent_reference(
            "obligation-a", self.a_digest))
        self.assertEqual(self.checkout_a["synthetic_capture_attempts"], 1)
        self.assertEqual(self.checkout_a["psp_capture"],
                         "NONE; synthetic merchant counter only")

    def test_cross_obligation_order_is_accepted_only_by_scripted_weak_adapter(self):
        weak = dispatch_invoice_verdict(
            checkout=self.checkout_a, target_obligation_id="obligation-b",
            target_artifact_digest=self.b_digest, oracle_status=None, strict=False)
        strong = dispatch_invoice_verdict(
            checkout=self.checkout_a, target_obligation_id="obligation-b",
            target_artifact_digest=self.b_digest, oracle_status="FAIL", strict=True)
        self.assertEqual((weak["verdict"], weak["order_bound"]), ("ACCEPT", False))
        self.assertEqual((strong["verdict"], strong["reason"]),
                         ("REJECT", "WRONG_OBLIGATION_OR_ARTIFACT"))

    def test_bound_purchase_still_needs_independent_quality_oracle(self):
        failed = dispatch_invoice_verdict(
            checkout=self.checkout_a, target_obligation_id="obligation-a",
            target_artifact_digest=self.a_digest, oracle_status="FAIL", strict=True)
        passed = dispatch_invoice_verdict(
            checkout=self.checkout_a, target_obligation_id="obligation-a",
            target_artifact_digest=self.a_digest, oracle_status="PASS", strict=True)
        self.assertEqual((failed["verdict"], failed["reason"]),
                         ("REJECT", "ORACLE_FAIL"))
        self.assertEqual((passed["verdict"], passed["reason"]),
                         ("ACCEPT", "ORACLE_PASS"))
        with self.assertRaisesRegex(ValueError, "needs an independent oracle"):
            dispatch_invoice_verdict(
                checkout=self.checkout_a, target_obligation_id="obligation-a",
                target_artifact_digest=self.a_digest, oracle_status=None, strict=True)

    def test_changed_reference_and_malformed_order_fail_saved_checkout_verification(self):
        changed = deepcopy(self.checkout_a)
        changed["complete_response"]["order"]["client_reference_id"] = (
            intent_reference("obligation-b", self.b_digest))
        with self.assertRaisesRegex(ValueError, "not bound"):
            validate_mock_checkout(changed, ACP_UPSTREAM)
        malformed = deepcopy(self.checkout_a)
        malformed["complete_response"].pop("order")
        with self.assertRaises(ValidationError):
            validate_mock_checkout(malformed, ACP_UPSTREAM)

    def test_mismatched_artifact_or_incomplete_order_cannot_pass_strict_guard(self):
        mismatch = dispatch_invoice_verdict(
            checkout=self.checkout_a, target_obligation_id="obligation-a",
            target_artifact_digest=self.b_digest, oracle_status="PASS", strict=True)
        self.assertEqual(mismatch["verdict"], "REJECT")
        incomplete = deepcopy(self.checkout_a)
        incomplete["complete_response"]["status"] = "ready_for_payment"
        result = dispatch_invoice_verdict(
            checkout=incomplete, target_obligation_id="obligation-a",
            target_artifact_digest=self.a_digest, oracle_status=None, strict=False)
        self.assertEqual((result["verdict"], result["reason"]),
                         ("REJECT", "CHECKOUT_NOT_COMPLETED"))


if __name__ == "__main__":
    unittest.main()
