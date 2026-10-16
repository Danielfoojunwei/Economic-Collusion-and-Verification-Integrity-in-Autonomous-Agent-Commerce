"""Local conformance slice for released OpenAI/Stripe ACP checkout schemas."""

from copy import deepcopy
import os
from pathlib import Path
import unittest

from jsonschema import ValidationError

from protocols.acp_retail.local_checkout import LocalCheckoutMerchant


UPSTREAM = Path(os.environ.get("ACP_RETAIL_UPSTREAM", "/workspace/upstreams/w17-acp-retail"))


@unittest.skipUnless((UPSTREAM / "spec/2026-04-17/json-schema/schema.agentic_checkout.json").is_file(), "pinned ACP retail schema not installed")
class AcpRetailLocalTests(unittest.TestCase):
    def setUp(self):
        self.merchant = LocalCheckoutMerchant(UPSTREAM)
        self.create_body = self.merchant.examples["create_checkout_session_request"]
        self.complete_body = self.merchant.examples["complete_checkout_session_request"]

    def test_complete_creates_order_once_and_replay_preserves_response(self):
        created = self.merchant.create("create-1", self.create_body)
        self.assertEqual(created.status, 200)
        self.assertEqual(created.body["status"], "ready_for_payment")
        first = self.merchant.complete("complete-1", self.complete_body)
        again = self.merchant.complete("complete-1", self.complete_body)
        self.assertEqual(first.status, 200)
        self.assertEqual(first.body["status"], "completed")
        self.assertEqual(first.body["order"]["checkout_session_id"], first.body["id"])
        self.assertTrue(again.replayed)
        self.assertEqual(again, type(first)(first.status, first.body, True))
        self.assertEqual(self.merchant.capture_attempts, 1)

    def test_missing_key_and_changed_body_are_rejected(self):
        self.assertEqual(self.merchant.create(None, self.create_body).status, 400)
        self.merchant.create("create-2", self.create_body)
        changed = deepcopy(self.create_body)
        changed["currency"] = "eur"
        conflict = self.merchant.create("create-2", changed)
        self.assertEqual((conflict.status, conflict.body["code"]), (422, "idempotency_conflict"))

    def test_cancel_prevents_complete_and_completed_prevents_cancel(self):
        self.merchant.create("create-3", self.create_body)
        canceled = self.merchant.cancel("cancel-3")
        self.assertEqual((canceled.status, canceled.body["status"]), (200, "canceled"))
        self.assertEqual(self.merchant.complete("complete-3", self.complete_body).status, 405)
        self.assertEqual(self.merchant.capture_attempts, 0)
        other = LocalCheckoutMerchant(UPSTREAM)
        other.create("create-4", self.create_body)
        other.complete("complete-4", self.complete_body)
        self.assertEqual(other.cancel("cancel-4").status, 405)

    def test_official_schema_rejects_malformed_checkout_and_order(self):
        wrong = deepcopy(self.create_body)
        wrong["currency"] = 7
        with self.assertRaises(ValidationError):
            self.merchant.validate("CheckoutSessionCreateRequest", wrong)
        completed = deepcopy(self.merchant.examples["complete_checkout_session_response"])
        completed.pop("order")
        with self.assertRaises(ValidationError):
            self.merchant.validate("CheckoutSessionWithOrder", completed)


if __name__ == "__main__":
    unittest.main()
