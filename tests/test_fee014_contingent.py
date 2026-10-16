"""Meaningful safety checks for FEE014's provisional full-hold transition."""

from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import unittest
from unittest.mock import patch

from scripts import assess_fee014_contingent as billing
from agent_economic_trust.remote_budget import read_ledger


class Fee014ContingentTests(unittest.TestCase):
    def temporary_ledger(self, directory: str) -> Path:
        path = Path(directory) / "ledger.jsonl"
        shutil.copyfile(billing.PRESTATE, path)
        shutil.copyfile(
            billing.PRESTATE.with_name(billing.PRESTATE.name + ".anchor"),
            path.with_name(path.name + ".anchor"),
        )
        return path

    def test_assessment_is_read_only_and_keeps_frozen_stop(self):
        ledger_sha = billing.digest(billing.PRESTATE)
        stop_sha = billing.digest(billing.EPISODE / "STOPPED.json")
        collection_sha = billing.digest(GATE := billing.GATE /
            "collection-002-after-first-stop.json")
        result = billing.validate_saved_evidence()
        self.assertEqual(result["result"],
                         "PROVISIONAL_HOLD_RETAINED_FINAL_CHARGE_UNKNOWN")
        self.assertEqual(result["successful_model_completions"], 4)
        self.assertEqual(result["failed_http_400_requests"], 1)
        self.assertEqual(result["successful_usage_estimate_usd"], "0.036636")
        self.assertIsNone(result["attributable_final_provider_bill_usd"])
        self.assertEqual(result["frozen_row_disposition"],
                         "STOPPED_NO_RETRY_THREE_PENDING")
        self.assertEqual(result["owner_csv_latest_hour_utc"],
                         "2026-10-15 13:00:00")
        self.assertEqual(billing.digest(billing.PRESTATE), ledger_sha)
        self.assertEqual(billing.digest(billing.EPISODE / "STOPPED.json"), stop_sha)
        self.assertEqual(billing.digest(GATE), collection_sha)

    def test_transition_retains_full_hold_and_is_one_time(self):
        with TemporaryDirectory() as directory:
            ledger = self.temporary_ledger(directory)
            before = read_ledger(ledger)
            result = billing.transition(ledger)
            after = read_ledger(ledger)
            self.assertEqual(result["new_ledger_seq"], 194)
            self.assertEqual(result["retained_reservation_usd"], "4.292608")
            self.assertEqual(result["frozen_row_disposition"],
                             "STOPPED_NO_RETRY_THREE_PENDING")
            self.assertEqual(after["settled_spent_usd"], before["settled_spent_usd"])
            self.assertEqual(after["reserved_usd"], before["reserved_usd"])
            self.assertEqual(after["available_usd"], before["available_usd"])
            self.assertFalse(after["blocked"])
            self.assertEqual(after["unknown_run_ids"], [])
            run = after["runs"][billing.RUN_ID]
            self.assertEqual(run["status"], "CONTINGENT")
            self.assertEqual(run["reserved_usd"], "4.292608")
            self.assertNotIn("actual_usd", run)
            self.assertEqual(run["contingent_evidence_ref"],
                             "sha256:" + billing.EVIDENCE_SHA256)
            with self.assertRaises(ValueError):
                billing.transition(ledger)
            self.assertEqual(read_ledger(ledger)["seq"], 194)

    def test_changed_evidence_or_prestate_fails_before_transition(self):
        with TemporaryDirectory() as directory:
            ledger = self.temporary_ledger(directory)
            evidence = Path(directory) / "evidence.json"
            evidence.write_bytes(billing.EVIDENCE.read_bytes() + b" ")
            with patch.object(billing, "EVIDENCE", evidence):
                with self.assertRaises(ValueError):
                    billing.transition(ledger)
            self.assertEqual(read_ledger(ledger)["seq"], 193)
            ledger.write_bytes(ledger.read_bytes() + b" ")
            with self.assertRaises(ValueError):
                billing.transition(ledger)


if __name__ == "__main__":
    unittest.main()
