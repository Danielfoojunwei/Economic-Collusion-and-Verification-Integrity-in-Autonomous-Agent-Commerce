"""Offline native controls for the bounded x402 invoice-report adapter."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_economic_trust.x402_invoice_adapter import (
    InvoiceX402Controller,
    PUBLIC_TASK_ID,
    PurchaseRefused,
    StrictInvoiceReportAdapter,
    build_resource_body,
    public_contract_facts,
)
from agent_economic_trust.core import Artifact, FIXTURES, Fixture
from agent_economic_trust.x402_invoice_verifier import EvidenceError, verify_purchase


class X402InvoiceAdapterTest(unittest.TestCase):
    def _controller(
        self, root: Path, case: str, port: int, *, served_case: str | None = None
    ) -> InvoiceX402Controller:
        return InvoiceX402Controller(
            case=case,
            assignment_nonce=f"assignment-{port}",
            obligation_id=f"invoice-obligation-{case}-{port}",
            output_dir=root / f"{case}-{port}",
            port=port,
            served_case=served_case,
        )

    @staticmethod
    def _buy(controller: InvoiceX402Controller):
        quote = controller.quote()
        return controller.buy_report(
            actor="auditor",
            request_id="agent-tool-call-001",
            intent="BUY_REPORT",
            quote_id=quote.quote_id,
            assignment_nonce=quote.assignment_nonce,
            service_id=quote.service_id,
            amount_minor_units=quote.amount_minor_units,
            recipient=quote.recipient,
        )

    def test_good_and_bad_have_identical_public_contract_facts(self) -> None:
        self.assertEqual(public_contract_facts("good"), public_contract_facts("bad"))
        with tempfile.TemporaryDirectory(prefix="x402-quotes-") as directory:
            root = Path(directory)
            good = self._controller(root, "good", 19240).quote().public_result()
            bad = self._controller(root, "bad", 19260).quote().public_result()
            for case, quote in (("good", good), ("bad", bad)):
                fixture, artifact = FIXTURES[case]
                self.assertFalse({"task_id", "obligation_id", "expected_report_digest"} & set(quote))
                encoded = json.dumps(quote, sort_keys=True)
                self.assertNotIn(fixture.task_id, encoded)
                self.assertNotIn(artifact.digest(), encoded)
                self.assertEqual(quote["public_task_id"], "invoice-report-open004")
                quote.pop("assignment_nonce")
            self.assertEqual(good, bad)

    def test_strict_adapter_rejects_wrong_obligation_and_digest(self) -> None:
        fixture, artifact = FIXTURES["good"]
        exact = build_resource_body(
            artifact=artifact, obligation_id="invoice-obligation-expected"
        )
        expected = {
            "task_id": PUBLIC_TASK_ID,
            "obligation_id": "invoice-obligation-expected",
            "expected_report_digest": exact["report_digest"],
        }
        strict = StrictInvoiceReportAdapter()
        self.assertTrue(strict.assess(exact, expected).accepted)
        wrong_obligation = json.loads(json.dumps(exact))
        wrong_obligation["application_binding"]["obligation_id"] = "other-obligation"
        self.assertEqual(strict.assess(wrong_obligation, expected).reason,
                         "OBLIGATION_MISMATCH")
        wrong_digest = json.loads(json.dumps(exact))
        wrong_digest["report"]["submitted_amount_cents"] = 350
        self.assertEqual(strict.assess(wrong_digest, expected).reason,
                         "REPORT_DIGEST_MISMATCH")

    def test_no_native_payment_without_exact_agent_intent_and_selection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="x402-intent-") as directory:
            root = Path(directory)
            controller = self._controller(root, "good", 19320)
            quote = controller.quote()
            attempts = (
                {"actor": "provider", "intent": "BUY_REPORT", "amount": quote.amount_minor_units,
                 "nonce": quote.assignment_nonce},
                {"actor": "auditor", "intent": "INSPECT_REPORT", "amount": quote.amount_minor_units,
                 "nonce": quote.assignment_nonce},
                {"actor": "auditor", "intent": "BUY_REPORT", "amount": quote.amount_minor_units + 1,
                 "nonce": quote.assignment_nonce},
                {"actor": "auditor", "intent": "BUY_REPORT", "amount": quote.amount_minor_units,
                 "nonce": "different-assignment"},
            )
            for index, attempt in enumerate(attempts):
                with self.subTest(index=index), self.assertRaises(PurchaseRefused):
                    controller.buy_report(
                        actor=attempt["actor"], request_id=f"invalid-{index}",
                        intent=attempt["intent"], quote_id=quote.quote_id,
                        assignment_nonce=attempt["nonce"],
                        service_id=quote.service_id,
                        amount_minor_units=attempt["amount"], recipient=quote.recipient,
                    )
            self.assertFalse((root / "good-19320").exists())

    def test_native_good_and_bad_receipts_keep_quality_separate_from_charge(self) -> None:
        with tempfile.TemporaryDirectory(prefix="x402-quality-") as directory:
            root = Path(directory)
            for case, port, expected_status, defective in (
                ("good", 19340, "PASS", False),
                ("bad", 19380, "FAIL", True),
            ):
                with self.subTest(case=case):
                    controller = self._controller(root, case, port)
                    receipt = self._buy(controller)
                    verified = verify_purchase(root / f"{case}-{port}")
                    self.assertTrue(receipt.protocol_paid)
                    self.assertTrue(receipt.application_binding_valid)
                    self.assertEqual(receipt.report.task_id, PUBLIC_TASK_ID)
                    self.assertEqual(verified.oracle_status, expected_status)
                    self.assertEqual(verified.paid_defective_report, defective)
                    self.assertFalse(verified.wrongful_protocol_charge)
                    self.assertEqual(receipt.transaction_hash, verified.transaction_hash)
                    public = receipt.public_result()
                    encoded = json.dumps(public).lower()
                    for forbidden in ("mnemonic", "private_key", "authorization", "signature"):
                        self.assertNotIn(forbidden, encoded)
                    # Same request is idempotent and cannot make a second charge.
                    self.assertEqual(self._buy(controller), receipt)

    def test_paid_body_substitution_is_positive_control_for_permissive_adapter(self) -> None:
        with tempfile.TemporaryDirectory(prefix="x402-substitute-") as directory:
            root = Path(directory)
            controller = self._controller(root, "good", 19420, served_case="bad")
            receipt = self._buy(controller)
            verified = verify_purchase(root / "good-19420")
            self.assertTrue(receipt.protocol_paid)
            self.assertFalse(receipt.application_binding_valid)
            self.assertEqual(receipt.application_binding_reason, "REPORT_DIGEST_MISMATCH")
            self.assertFalse(verified.application_binding_valid)
            self.assertTrue(verified.permissive_adapter_accepted)
            self.assertEqual(verified.oracle_status, "FAIL")
            self.assertTrue(verified.paid_defective_report)
            self.assertFalse(verified.wrongful_protocol_charge)

            command = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_x402_invoice_purchase.py"),
                 str(root / "good-19420")],
                cwd=ROOT, capture_output=True, text=True, timeout=20, check=False,
            )
            self.assertEqual(command.returncode, 0, command.stderr)
            self.assertFalse(json.loads(command.stdout)["application_binding_valid"])

    def test_native_protected_fixtures_are_truthful_and_model_blind(self) -> None:
        protected_prompt = "Protected purchase orders and credit notes determine the expected total."
        protected = {
            "good": (
                Fixture("protected-internal-good", protected_prompt, 300, 500),
                Artifact("protected-internal-good", 300),
            ),
            "bad": (
                Fixture("protected-internal-bad", protected_prompt, 300, 500),
                Artifact("protected-internal-bad", 350),
            ),
        }
        with tempfile.TemporaryDirectory(prefix="x402-protected-") as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "task IDs differ"):
                InvoiceX402Controller(
                    frozen_fixture=protected["good"][0],
                    frozen_artifact=protected["bad"][1],
                    assignment_nonce="mismatched", obligation_id="mismatched",
                    output_dir=root / "mismatched", port=19500,
                )
            public_quotes = []
            for index, (case, expected_oracle) in enumerate((("good", "PASS"), ("bad", "FAIL"))):
                fixture, artifact = protected[case]
                output = root / case
                controller = InvoiceX402Controller(
                    frozen_fixture=fixture,
                    frozen_artifact=artifact,
                    assignment_nonce=f"protected-assignment-{index}",
                    obligation_id=f"protected-obligation-{index}",
                    output_dir=output,
                    port=19520 + 40 * index,
                )
                quote = controller.quote().public_result()
                encoded_quote = json.dumps(quote, sort_keys=True)
                self.assertNotIn(fixture.task_id, encoded_quote)
                self.assertNotIn(protected_prompt, encoded_quote)
                self.assertNotIn("expected_amount_cents", encoded_quote)
                self.assertNotIn("submitted_amount_cents", encoded_quote)
                quote.pop("assignment_nonce")
                public_quotes.append(quote)
                receipt = self._buy(controller)
                self.assertEqual(receipt.report.task_id, PUBLIC_TASK_ID)
                self.assertEqual(receipt.report.submitted_amount_cents,
                                 artifact.submitted_amount_cents)
                resource = json.loads((output / "resource-body.json").read_text())
                self.assertEqual(receipt.report.report_digest, resource["report_digest"])
                self.assertEqual(resource["report"]["task_id"], PUBLIC_TASK_ID)
                self.assertNotIn(fixture.task_id, json.dumps(resource, sort_keys=True))
                encoded_receipt = json.dumps(receipt.public_result(), sort_keys=True)
                self.assertNotIn(fixture.task_id, encoded_receipt)
                self.assertNotIn("expected_amount_cents", encoded_receipt)
                private_intent = json.loads((output / "purchase-intent.json").read_text())
                self.assertEqual(
                    private_intent["controller_binding"]["oracle_fixture"]["task_id"],
                    fixture.task_id,
                )
                self.assertEqual(
                    private_intent["controller_binding"]["oracle_fixture"]
                    ["expected_amount_cents"],
                    fixture.expected_amount_cents,
                )
                verified = verify_purchase(
                    output, frozen_fixture=fixture, frozen_artifact=artifact
                )
                self.assertEqual(verified.task_id, PUBLIC_TASK_ID)
                self.assertEqual(verified.oracle_status, expected_oracle)
                self.assertEqual(verified.paid_defective_report, case == "bad")
            self.assertEqual(public_quotes[0], public_quotes[1])
            with self.assertRaisesRegex(EvidenceError, "caller-frozen oracle inputs differ"):
                verify_purchase(
                    root / "good",
                    frozen_fixture=protected["bad"][0],
                    frozen_artifact=protected["bad"][1],
                )

    def test_independent_verifier_rejects_raw_body_manifest_disagreement(self) -> None:
        with tempfile.TemporaryDirectory(prefix="x402-tamper-") as directory:
            root = Path(directory)
            controller = self._controller(root, "good", 19460)
            self._buy(controller)
            purchase = root / "good-19460"
            resource_path = purchase / "resource-body.json"
            resource = json.loads(resource_path.read_text())
            resource["application_binding"]["obligation_id"] = "different-obligation"
            resource_path.write_text(json.dumps(resource))
            with self.assertRaisesRegex(EvidenceError, "stored response body differs"):
                verify_purchase(purchase)


if __name__ == "__main__":
    unittest.main()
