"""Prospective MPP010 sequencing evidence; these tests never freeze or pay."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_economic_trust.mpp010_plan import CANONICAL_LEDGER_PATH, digest
from agent_economic_trust.remote_budget import BudgetLedger
from scripts import freeze_mpp010 as gate


class ClearanceTests(unittest.TestCase):
    def test_archived_mpp009_first_stop_and_no_implicit_clearance(self):
        state = BudgetLedger(CANONICAL_LEDGER_PATH).snapshot()
        evidence = gate.mpp009_stopped_evidence(state)
        self.assertEqual(evidence["mpp009_disposition"],
                         "FIRST_STOPPED_NO_RETRY_NINE_PENDING")
        self.assertEqual(evidence["mpp009_first_raw_sha256"],
                         gate.MPP009_FIRST_RAW_SHA256)
        self.assertEqual(evidence["mpp009_final_ledger_seq"], 147)
        with TemporaryDirectory() as temporary, \
             patch.object(gate, "CLEARANCE", Path(temporary) / "absent.json"):
            with self.assertRaisesRegex(ValueError, "sequencing record is absent"):
                gate.cross_study_clearance(state)
            self.assertFalse((Path(temporary) / "absent.json").exists())

    def test_mpp009_settled_billing_and_raw_archive_are_bound(self):
        state = BudgetLedger(CANONICAL_LEDGER_PATH).snapshot()
        wrong = deepcopy(state)
        wrong["runs"][gate.MPP009_FIRST_RUN_ID]["actual_usd"] = "0.123487"
        with self.assertRaisesRegex(ValueError, "billing or run denominator"):
            gate.mpp009_stopped_evidence(wrong)
        with patch.object(gate, "MPP009_FIRST_RAW_SHA256", "0" * 64):
            with self.assertRaisesRegex(ValueError, "raw model archive changed"):
                gate.mpp009_stopped_evidence(state)

    def test_post_stop_unknown_or_reserved_run_blocks_priority(self):
        state = BudgetLedger(CANONICAL_LEDGER_PATH).snapshot()
        records = gate._ledger_records_through(state)[:gate.MPP009_FINAL_LEDGER_SEQ + 1]
        later = {"payload": {"run_id": "competing-1"}}
        for status in ("RESERVED", "UNKNOWN", "CONTINGENT"):
            changed = deepcopy(state)
            changed["runs"]["competing-1"] = {"status": status}
            with patch.object(gate, "_ledger_records_through",
                              return_value=[*records, later]):
                with self.assertRaisesRegex(ValueError, "nonterminal or UNKNOWN"):
                    gate.intervening_ledger_evidence(changed)
        settled = deepcopy(state)
        settled["runs"]["competing-1"] = {"status": "SETTLED",
                                           "actual_usd": "0.1", "evidence_ref": "sha256:" + "a" * 64}
        with patch.object(gate, "_ledger_records_through", return_value=[*records, later]):
            self.assertEqual(gate.intervening_ledger_evidence(settled)[
                "post_mpp009_ledger_run_ids"], ["competing-1"])

    def test_zero_call_competing_gate_is_in_inventory(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = root / "artifacts/gates/OTHER/first-freeze.lock.json"
            assignment = root / "artifacts/gates/OTHER/assignment-001/assignment_manifest.json"
            assignment.parent.mkdir(parents=True)
            assignment.write_text("{}")
            lock.write_text("{}")
            with patch.object(gate, "PROJECT_ROOT", root):
                found = gate.competing_gate_inventory()
            self.assertEqual(set(found), {
                "artifacts/gates/OTHER/first-freeze.lock.json",
                "artifacts/gates/OTHER/assignment-001/assignment_manifest.json"})

    def test_new_zero_call_gate_requires_final_collection_review(self):
        with self.assertRaisesRegex(ValueError, "does not cover"):
            gate._intervening_review({"intervening_studies": []}, [], ["NEW"])
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            final = root / "artifacts/gates/NEW/collection-final.json"
            final.parent.mkdir(parents=True)
            final.write_text(json.dumps({"study_id": "new-study", "planned_episodes": 1,
                                         "completed_episodes": 1, "rows": [
                                             {"status": "COMPLETE"}]}))
            entry = {"gate_id": "NEW", "study_id": "new-study",
                     "disposition": "FINALIZED_NO_ACTIVE_PRIORITY",
                     "final_collection_path": "artifacts/gates/NEW/collection-final.json",
                     "final_collection_sha256": gate.sha(final), "ledger_run_ids": []}
            with patch.object(gate, "PROJECT_ROOT", root):
                self.assertEqual(gate._intervening_review({
                    "intervening_studies": [entry]}, [], ["NEW"]), [entry])
                final.write_text(json.dumps({"study_id": "new-study", "planned_episodes": 1,
                                             "completed_episodes": 0,
                                             "pending_episodes": 1}))
                with self.assertRaisesRegex(ValueError, "not finally disposed"):
                    gate._intervening_review({"intervening_studies": [entry]}, [], ["NEW"])

    def test_clearance_exactly_binds_gate_inventory_and_budget_head(self):
        state = BudgetLedger(CANONICAL_LEDGER_PATH).snapshot()
        stopped = gate.mpp009_stopped_evidence(state)
        later = {"post_mpp009_ledger_events_sha256": digest([]),
                 "post_mpp009_ledger_run_ids": [], "post_mpp009_terminal_runs": {}}
        # Isolate this exact-record unit from studies frozen concurrently in
        # the canonical checkout. A separate test requires review of each
        # newly frozen zero-call gate.
        inventory = {name: value for name, value in gate.competing_gate_inventory().items()
                     if name in gate.BASELINE_GATE_PATHS}
        with TemporaryDirectory() as temporary:
            clearance = Path(temporary) / "clearance.json"
            record = {"schema": "mpp010-cross-study-clearance-v1",
                      "study_id": gate.STUDY_ID,
                      "decision": "MPP010_PRIORITY_AFTER_MPP009_FIRST_STOP",
                      "ledger_seq": state["seq"], "ledger_last_hash": state["last_hash"],
                      "ledger_available_usd": state["available_usd"],
                      "competing_gate_inventory": inventory,
                      "competing_gate_dispositions": gate._competing_gate_dispositions(inventory),
                      "new_competing_gates": [],
                      "intervening_studies": [], **later, **stopped}
            clearance.write_text(json.dumps(record))
            with patch.object(gate, "CLEARANCE", clearance), \
                 patch.object(gate, "competing_gate_inventory", return_value=inventory), \
                 patch.object(gate, "intervening_ledger_evidence", return_value=later):
                self.assertEqual(gate.cross_study_clearance(state)["decision"],
                                 record["decision"])
                clearance.write_text(json.dumps({**record,
                    "competing_gate_inventory": {}}))
                with self.assertRaisesRegex(ValueError, "clearance differs"):
                    gate.cross_study_clearance(state)


if __name__ == "__main__":
    unittest.main()
