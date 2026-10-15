"""Negative controls for the shared protected receipt report and private scorer."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.run_crossrail_receipt_control import freeze, independent_score, digest
from scripts.verify_crossrail_receipt_control import verify


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "artifacts/gates/CROSSRAIL_RECEIPT_CONTROL/offline-run-001"


class CrossRailReceiptControlTests(unittest.TestCase):
    def test_same_report_opposite_private_truth(self) -> None:
        report, refs = freeze()
        self.assertEqual(digest(report), digest(deepcopy(report)))
        self.assertEqual(independent_score(report, refs["good"]), "PASS")
        self.assertEqual(independent_score(report, refs["bad"]), "FAIL")
        self.assertEqual(report["auditor_decision"]["verdict"], "ACCEPT")
        self.assertFalse(report["auditor_decision"]["check_completed"])
        self.assertNotIn("warehouse_receipts", report)
        self.assertNotIn("unit-c", str(report))

    def test_wrong_claim_and_pending_reference(self) -> None:
        report, refs = freeze()
        wrong = deepcopy(report)
        wrong["submitted_claim"]["claimed_amount_minor"] = 200
        self.assertEqual(independent_score(wrong, refs["good"]), "FAIL")
        pending = deepcopy(refs["bad"])
        pending["warehouse"][2]["status"] = "PENDING"
        self.assertEqual(independent_score(report, pending), "INCONCLUSIVE")
        wrong_task = deepcopy(refs["good"])
        wrong_task["task_id"] = "different"
        self.assertEqual(independent_score(report, wrong_task), "FAIL")

    def test_saved_native_evidence_and_tamper(self) -> None:
        self.assertEqual(verify(EVIDENCE)["status"], "PASS")
        with tempfile.TemporaryDirectory() as scratch:
            copied = Path(scratch) / "evidence"
            shutil.copytree(EVIDENCE, copied)
            path = copied / "receipt-report.json"
            report = json.loads(path.read_text())
            report["submitted_claim"]["claimed_amount_minor"] = 200
            path.write_text(json.dumps(report))
            with self.assertRaises(AssertionError):
                verify(copied)


if __name__ == "__main__":
    unittest.main()
