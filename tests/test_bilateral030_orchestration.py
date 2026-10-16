"""No-call block and row preflight controls for a prospective 30-pair study."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from agent_economic_trust.bilateral030_orchestration import (
    SOURCE_PATHS, pre_view_row_hold, preflight_proposal, source_inventory,
    validate_preflight_report, write_preflight_report,
)
from agent_economic_trust.bilateral030_plan import CANONICAL_LEDGER
from agent_economic_trust.remote_budget import BudgetLedger


IDENTITY = "4a" * 32
ASSIGNMENT = "b7" * 32
OTHER_ASSIGNMENT = "c8" * 32


class Bilateral030OrchestrationTests(unittest.TestCase):
    def test_real_shared_ledger_is_read_only_and_all_thirty_rows_hold(self):
        original = CANONICAL_LEDGER.read_bytes()
        anchor = CANONICAL_LEDGER.with_name(CANONICAL_LEDGER.name + ".anchor")
        original_anchor = anchor.read_bytes()
        with patch.object(BudgetLedger, "reserve",
                          side_effect=AssertionError("source preflight reserved money")):
            report = preflight_proposal(IDENTITY, ASSIGNMENT)
            row = pre_view_row_hold(report, 0)
        self.assertEqual(CANONICAL_LEDGER.read_bytes(), original)
        self.assertEqual(anchor.read_bytes(), original_anchor)
        self.assertEqual(report["planned_rows"], 30)
        self.assertEqual(len(report["row_status"]), 30)
        self.assertTrue(all(item["status"] == "PENDING" and
                            item["scientific_outcome"] is None
                            for item in report["row_status"]))
        self.assertEqual(report["status"], "HOLD_SOURCE_ONLY_UNFROZEN")
        self.assertIn("SHARED_LEDGER_BLOCKED_OR_UNKNOWN", report["hold_reasons"])
        self.assertIn("FULL_BLOCK_EXCEEDS_AVAILABLE_HEADROOM", report["hold_reasons"])
        self.assertFalse(row["permission_to_call_model"])
        self.assertIsNone(row["scientific_outcome"])

    def test_distinct_assignment_seeds_change_seal_without_exposing_secrets(self):
        first = preflight_proposal(IDENTITY, ASSIGNMENT)
        second = preflight_proposal(IDENTITY, OTHER_ASSIGNMENT)
        self.assertNotEqual(first["proposal_sha256"], second["proposal_sha256"])
        self.assertEqual(first["proposal_seal"]["source_snapshot_sha256"],
                         second["proposal_seal"]["source_snapshot_sha256"])
        self.assertEqual(first["public_assignment_preview"]["execution_order"],
                         second["public_assignment_preview"]["execution_order"])
        serialized = json.dumps(first)
        self.assertNotIn(IDENTITY, serialized)
        self.assertNotIn(ASSIGNMENT, serialized)
        self.assertNotIn('"truth"', serialized)
        self.assertNotIn('"group"', serialized)
        with self.assertRaisesRegex(ValueError, "must differ"):
            preflight_proposal(IDENTITY, IDENTITY)

    def test_self_asserted_funding_cannot_open_a_row_or_shift_assignment(self):
        report = preflight_proposal(IDENTITY, ASSIGNMENT)
        first = report["public_assignment_preview"]["public_rows"][0]
        fake = {"status": "FUNDING_LIVE_CONFIRMED",
                "episode_id": first["episode_id"],
                "obligation_id": first["obligation_id"],
                "independent_funding_replay": True}
        hold = pre_view_row_hold(report, 0, fake)
        self.assertFalse(hold["permission_to_call_model"])
        self.assertTrue(hold["funding_claim_supplied_but_not_independently_replayed"])
        later = pre_view_row_hold(report, 1)
        self.assertIn("PRIOR_ROW_INDEPENDENT_TRACE_NATIVE_OR_STOP_REVIEW_MISSING",
                      later["hold_reasons"])
        self.assertIn("PRIOR_ROW_ATTRIBUTABLE_CHARGE_OR_WORST_CASE_HOLD_UNVERIFIED",
                      later["hold_reasons"])
        with self.assertRaisesRegex(ValueError, "another row"):
            pre_view_row_hold(report, 1, fake)
        with self.assertRaisesRegex(ValueError, "outside assigned"):
            pre_view_row_hold(report, 30)
        malformed = {**report, "status": "FROZEN_READY"}
        with self.assertRaisesRegex(ValueError, "claims execution"):
            validate_preflight_report(malformed)
        altered = json.loads(json.dumps(report))
        altered["public_assignment_preview"]["public_rows"][0]["obligation_id"] = "invoice-forged"
        with self.assertRaisesRegex(ValueError, "public assignment"):
            validate_preflight_report(altered)

    def test_source_snapshot_records_missing_untracked_and_changed_bytes(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / SOURCE_PATHS[0]
            source.parent.mkdir(parents=True)
            source.write_bytes(b"version-one")
            first = source_inventory(root)
            source.write_bytes(b"version-two")
            second = source_inventory(root)
            self.assertNotEqual(first["source_snapshot_sha256"],
                                second["source_snapshot_sha256"])
            self.assertIn(SOURCE_PATHS[0], second["untracked_required_sources"])
            self.assertIn(SOURCE_PATHS[1], second["missing_required_sources"])
            self.assertFalse(second["local_source_inventory_clean"])
            source.unlink()
            source.symlink_to(root / "absent")
            third = source_inventory(root)
            self.assertIn(SOURCE_PATHS[0], third["missing_required_sources"])

    def test_public_report_is_create_once_and_cannot_claim_frozen(self):
        report = preflight_proposal(IDENTITY, ASSIGNMENT)
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "preflight.json"
            write_preflight_report(report, path)
            self.assertEqual(json.loads(path.read_bytes()), report)
            with self.assertRaises(FileExistsError):
                write_preflight_report(report, path)
            forged = {**report, "permission_to_freeze_reserve_or_call": True}
            with self.assertRaisesRegex(ValueError, "claims execution"):
                write_preflight_report(forged, Path(temporary) / "forged.json")


if __name__ == "__main__":
    unittest.main()
