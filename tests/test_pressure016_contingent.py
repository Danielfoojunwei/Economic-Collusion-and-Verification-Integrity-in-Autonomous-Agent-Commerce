"""Fail-closed checks for the PRESSURE016 third-stop provisional billing hold."""

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import shutil
import unittest
from unittest.mock import patch

from agent_economic_trust.remote_budget import BudgetLedger, BudgetStateError, read_ledger
from scripts import assess_pressure016_contingent as billing


class Pressure016ContingentTests(unittest.TestCase):
    def temporary_ledger(self, directory: str) -> Path:
        path = Path(directory) / "ledger.jsonl"
        shutil.copyfile(billing.PRESTATE, path)
        shutil.copyfile(
            billing.PRESTATE.with_name(billing.PRESTATE.name + ".anchor"),
            path.with_name(path.name + ".anchor"),
        )
        return path

    def temporary_review(self, directory: str, **changes) -> tuple[Path, str]:
        path = Path(directory) / "independent-review.json"
        value = {
            "schema": "pressure016-provisional-billing-independent-review-v1",
            "reviewer_id": "/root/independent_unit_test",
            "decision": "GO_FOR_ONE_CANONICAL_UNKNOWN_TO_CONTINGENT_TRANSITION",
            "reviewed_artifacts_sha256": {
                "scripts/assess_pressure016_contingent.py":
                    billing.digest(Path(billing.__file__)),
                "artifacts/budget/pressure016-third-stop-contingent-001/evidence.json":
                    billing.EVIDENCE_SHA256,
                "artifacts/budget/pressure016-third-stop-contingent-001/openrouter-ledger.prestate.jsonl":
                    billing.EXPECTED["ledger"],
                "artifacts/budget/pressure016-third-stop-contingent-001/openrouter-ledger.prestate.jsonl.anchor":
                    billing.EXPECTED["anchor"],
            },
            "canonical_ledger_prestate": {
                "seq": 223, "last_hash": billing.LAST_HASH,
                "cap_usd": "50", "unknown_run_ids": [billing.RUN_ID],
            },
            "retained_reservation_usd": "3.981312",
            "attributable_final_provider_bill_usd": None,
            "no_paid_calls_or_ledger_mutations": True,
        }
        value.update(changes)
        path.write_text(json.dumps(value, sort_keys=True))
        return path, billing.digest(path)

    def test_replay_separates_seven_returns_from_local_eighth_error(self):
        paths = (billing.PRESTATE, billing.EPISODE / "STOPPED.json",
                 billing.EVIDENCE)
        before_hashes = [billing.digest(p) for p in paths]
        result = billing.validate_saved_evidence()
        self.assertEqual(result["result"],
                         "PROVISIONAL_HOLD_RETAINED_FINAL_CHARGE_UNKNOWN")
        self.assertEqual(result["completed_guarded_provider_api_invocations"], 7)
        self.assertFalse(result["eighth_provider_api_invocation"])
        self.assertEqual(result["failed_synthetic_model_event_index"], 125)
        self.assertEqual(result["failed_local_tool_event_index"], 113)
        self.assertEqual(result["successful_usage_estimate_usd"], "0.080814")
        self.assertFalse(result["successful_usage_estimate_is_provider_invoice"])
        self.assertEqual(result["retained_run_reservation_usd"], "3.981312")
        self.assertEqual(result["frozen_row_disposition"],
                         "TWO_COMPLETE_ONE_STOPPED_ONE_PENDING_NO_RETRY")
        self.assertIsNone(result["attributable_final_provider_bill_usd"])
        self.assertFalse(result["whole_account_delta_is_per_call_bill"])
        self.assertEqual(before_hashes, [billing.digest(p) for p in paths])

    def test_transition_is_review_gated_one_time_and_keeps_full_hold(self):
        with TemporaryDirectory() as directory:
            ledger = self.temporary_ledger(directory)
            before = read_ledger(ledger)
            with self.assertRaises(FileNotFoundError):
                billing.transition(ledger, Path(directory) / "missing.json", "0" * 64)
            self.assertEqual(read_ledger(ledger)["seq"], 223)
            review, review_sha = self.temporary_review(directory)
            outcome = billing.transition(ledger, review, review_sha)
            after = read_ledger(ledger)
            self.assertEqual(outcome["new_ledger_seq"], 224)
            self.assertEqual(outcome["retained_reservation_usd"], "3.981312")
            self.assertIsNone(outcome["actual_final_charge_usd"])
            self.assertFalse(after["blocked"])
            self.assertEqual(after["unknown_run_ids"], [])
            for key in ("cap_usd", "settled_spent_usd", "reserved_usd", "available_usd"):
                self.assertEqual(after[key], before[key])
            run = after["runs"][billing.RUN_ID]
            self.assertEqual(run["status"], "CONTINGENT")
            self.assertEqual(run["reserved_usd"], "3.981312")
            self.assertNotIn("actual_usd", run)
            self.assertEqual(run["contingent_evidence_ref"],
                             "sha256:" + billing.EVIDENCE_SHA256)
            with self.assertRaises(ValueError):
                billing.transition(ledger, review, review_sha)
            with self.assertRaises(BudgetStateError):
                BudgetLedger(ledger).settle(
                    billing.RUN_ID, "0", "sha256:" + billing.EVIDENCE_SHA256)
            self.assertEqual(read_ledger(ledger)["seq"], 224)

    def test_tampered_stop_or_evidence_cannot_change_ledger(self):
        with TemporaryDirectory() as directory:
            ledger = self.temporary_ledger(directory)
            review, review_sha = self.temporary_review(directory)
            stop = json.loads((billing.EPISODE / "STOPPED.json").read_text())
            stop["model_request_boundary"].append(dict(stop["model_request_boundary"][0]))
            mutated = Path(directory) / "STOPPED.json"
            mutated.write_text(json.dumps(stop))
            with patch.dict(billing.ARTIFACTS, {"stopped": mutated}):
                with self.assertRaises(ValueError):
                    billing.transition(ledger, review, review_sha)
            with patch.object(billing, "EVIDENCE_SHA256", "0" * 64):
                with self.assertRaises(ValueError):
                    billing.transition(ledger, review, review_sha)
            self.assertEqual(read_ledger(ledger)["seq"], 223)

    def test_changed_review_or_ledger_fails_before_append(self):
        with TemporaryDirectory() as directory:
            ledger = self.temporary_ledger(directory)
            review, review_sha = self.temporary_review(directory)
            altered = json.loads(review.read_text())
            altered["canonical_ledger_prestate"]["cap_usd"] = "51"
            review.write_text(json.dumps(altered))
            with self.assertRaises(ValueError):
                billing.transition(ledger, review, billing.digest(review))
            review, review_sha = self.temporary_review(directory)
            ledger.write_bytes(ledger.read_bytes() + b" ")
            with self.assertRaises(ValueError):
                billing.transition(ledger, review, review_sha)


if __name__ == "__main__":
    unittest.main()
