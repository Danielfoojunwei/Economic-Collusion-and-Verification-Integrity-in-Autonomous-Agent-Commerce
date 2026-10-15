"""Offline positive and tamper checks for the MPP006 billing sidecar."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import verify_mpp006_conditional_zero as reconciliation


class ConditionalZeroReconciliationTests(unittest.TestCase):
    def test_saved_result_reproduces_without_ledger_write(self) -> None:
        before = reconciliation.sha(reconciliation.EVIDENCE / "prestate-openrouter-ledger.jsonl")
        result = reconciliation.verify()
        saved = json.loads((reconciliation.EVIDENCE / "evidence.json").read_text())
        self.assertEqual(result, saved)
        self.assertEqual(result["conditional_model_inference_charge_usd"], "0")
        self.assertIsNone(result["actual_final_total_failed_request_usd"])
        self.assertEqual(result["contingent_budget_exposure_usd"], "6.30784")
        self.assertEqual(before, reconciliation.sha(reconciliation.EVIDENCE / "prestate-openrouter-ledger.jsonl"))

    def test_archived_official_source_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory)
            for path in reconciliation.EVIDENCE.glob("*.html.gz"):
                shutil.copy2(path, copy / path.name)
            shutil.copy2(reconciliation.EVIDENCE / "official-docs.json", copy / "official-docs.json")
            target = copy / "zero-completion-insurance.html.gz"
            target.write_bytes(target.read_bytes() + b"tampered")
            with patch.object(reconciliation, "EVIDENCE", copy):
                with self.assertRaisesRegex(ValueError, "archived source gzip differs"):
                    reconciliation.official_docs()

    def test_non_schema_error_does_not_match(self) -> None:
        with self.assertRaises(ValueError):
            reconciliation.serialized_request("ModelGenerateError('success')")


if __name__ == "__main__":
    unittest.main()
