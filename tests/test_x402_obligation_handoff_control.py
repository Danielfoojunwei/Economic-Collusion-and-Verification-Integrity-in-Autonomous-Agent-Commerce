"""Saved native replay and tamper controls for x402 invoice handoff."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from agent_economic_trust.x402_invoice_adapter import PUBLIC_TASK_ID, canonical_sha256
from agent_economic_trust.x402_invoice_verifier import EvidenceError
from agent_economic_trust.x402_obligation_handoff import STRICT, assess_paid_report
from scripts.verify_x402_obligation_handoff_control import verify


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "artifacts/gates/OPEN005/offline-invoice/native/BAD_REJECT/x402"
SAVED = ROOT / "artifacts/prospective/X402_OBLIGATION_HANDOFF/offline-native-002"


class X402ObligationHandoffControlTest(unittest.TestCase):
    def test_saved_archived_payment_and_six_new_terminals_replay(self) -> None:
        result = verify(SAVED)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["archived_x402_native_receipts_replayed"], 2)
        self.assertEqual(result["new_erc8183_local_terminals_replayed"], 6)
        by_key = {(f["scenario"], f["policy"]): f for f in result["findings"]}
        self.assertTrue(by_key[("bad-cross-obligation", "PERMISSIVE_PAID_BODY")]
                        ["provider_paid"])
        self.assertTrue(by_key[("bad-cross-obligation", STRICT)]["client_refunded"])
        self.assertTrue(by_key[("bad-same-obligation", STRICT)]["provider_paid"])

    def test_altered_archived_body_cannot_be_reused_as_paid_proof(self) -> None:
        with tempfile.TemporaryDirectory(prefix="x402-handoff-tamper-") as directory:
            copied = Path(directory) / "x402"
            shutil.copytree(ARCHIVE, copied)
            body_path = copied / "resource-body.json"
            body = json.loads(body_path.read_text())
            body["application_binding"]["obligation_id"] = "invoice-forged-target"
            body_path.write_text(json.dumps(body))
            digest = canonical_sha256({
                "task_id": PUBLIC_TASK_ID, "submitted_amount_cents": 350})
            with self.assertRaises(EvidenceError):
                assess_paid_report(
                    purchase_dir=copied, target_obligation_id="invoice-forged-target",
                    target_report_digest=digest, requested_verdict="ACCEPT", policy=STRICT)

    def test_altered_native_result_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="x402-handoff-report-") as directory:
            copied = Path(directory) / "saved"
            shutil.copytree(SAVED, copied)
            report_path = copied / "report.json"
            report = json.loads(report_path.read_text())
            report["rows"][0]["native_evidence_sha256"] = "0" * 64
            report_path.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "native evidence path/hash differs"):
                verify(copied)


if __name__ == "__main__":
    unittest.main()
