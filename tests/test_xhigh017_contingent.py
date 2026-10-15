"""Fail-closed checks for the XHIGH017 first-stop provisional billing hold."""

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import shutil
import unittest
from unittest.mock import patch

from agent_economic_trust.remote_budget import BudgetLedger, BudgetStateError, read_ledger
from scripts import assess_xhigh017_contingent as billing


class Xhigh017ContingentTests(unittest.TestCase):
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
            "schema": "xhigh017-provisional-billing-independent-review-v1",
            "reviewer_id": "/root/independent_unit_test",
            "decision": "GO_FOR_ONE_CANONICAL_UNKNOWN_TO_CONTINGENT_TRANSITION",
            "reviewed_artifacts_sha256": {
                "scripts/assess_xhigh017_contingent.py": billing.digest(Path(billing.__file__)),
                "artifacts/budget/xhigh017-first-stop-contingent-001/evidence.json":
                    billing.EVIDENCE_SHA256,
                "artifacts/budget/xhigh017-first-stop-contingent-001/openrouter-ledger.prestate.jsonl":
                    billing.EXPECTED["ledger"],
                "artifacts/budget/xhigh017-first-stop-contingent-001/openrouter-ledger.prestate.jsonl.anchor":
                    billing.EXPECTED["anchor"],
            },
            "canonical_ledger_prestate": {
                "seq": 216, "last_hash": billing.LAST_HASH,
                "cap_usd": "50", "unknown_run_ids": [billing.RUN_ID],
            },
            "retained_reservation_usd": "4.718592",
            "attributable_final_provider_bill_usd": None,
            "no_paid_calls_or_ledger_mutations": True,
        }
        value.update(changes)
        path.write_text(json.dumps(value, sort_keys=True))
        return path, billing.digest(path)

    def test_replay_has_one_failed_wrapper_event_and_preserves_stop(self):
        hashes = [billing.digest(p) for p in (billing.PRESTATE,
            billing.EPISODE / "STOPPED.json", billing.EVIDENCE)]
        result = billing.validate_saved_evidence()
        self.assertEqual(result["result"],
                         "PROVISIONAL_HOLD_RETAINED_FINAL_CHARGE_UNKNOWN")
        self.assertEqual(result["guarded_provider_api_invocations"], 1)
        self.assertEqual(result["completed_model_returns"], 0)
        self.assertEqual(result["auditor_api_invocations"], 0)
        self.assertEqual(result["retained_run_reservation_usd"], "4.718592")
        self.assertEqual(result["frozen_row_disposition"],
                         "ZERO_COMPLETE_ONE_STOPPED_ONE_PENDING_NO_RETRY")
        self.assertIsNone(result["attributable_final_provider_bill_usd"])
        self.assertFalse(result["whole_account_delta_is_per_call_bill"])
        self.assertEqual(hashes, [billing.digest(p) for p in (billing.PRESTATE,
            billing.EPISODE / "STOPPED.json", billing.EVIDENCE)])

    def test_transition_is_review_gated_one_time_and_keeps_full_cap_hold(self):
        with TemporaryDirectory() as directory:
            ledger = self.temporary_ledger(directory)
            before = read_ledger(ledger)
            missing = Path(directory) / "missing-review.json"
            with self.assertRaises(FileNotFoundError):
                billing.transition(ledger, missing, "0" * 64)
            self.assertEqual(read_ledger(ledger)["seq"], 216)
            review, review_sha = self.temporary_review(directory)
            outcome = billing.transition(ledger, review, review_sha)
            after = read_ledger(ledger)
            self.assertEqual(outcome["new_ledger_seq"], 217)
            self.assertEqual(outcome["retained_reservation_usd"], "4.718592")
            self.assertIsNone(outcome["actual_final_charge_usd"])
            self.assertFalse(after["blocked"])
            self.assertEqual(after["unknown_run_ids"], [])
            for key in ("cap_usd", "settled_spent_usd", "reserved_usd", "available_usd"):
                self.assertEqual(after[key], before[key])
            run = after["runs"][billing.RUN_ID]
            self.assertEqual(run["status"], "CONTINGENT")
            self.assertEqual(run["reserved_usd"], "4.718592")
            self.assertNotIn("actual_usd", run)
            self.assertEqual(run["contingent_evidence_ref"],
                             "sha256:" + billing.EVIDENCE_SHA256)
            with self.assertRaises(ValueError):
                billing.transition(ledger, review, review_sha)
            with self.assertRaises(BudgetStateError):
                BudgetLedger(ledger).settle(
                    billing.RUN_ID, "0", "sha256:" + billing.EVIDENCE_SHA256)
            self.assertEqual(read_ledger(ledger)["seq"], 217)

    def test_extra_invocation_or_tampered_evidence_fails_closed(self):
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
            self.assertEqual(read_ledger(ledger)["seq"], 216)

    def test_changed_cap_review_or_ledger_fails_before_append(self):
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
