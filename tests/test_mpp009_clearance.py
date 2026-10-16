"""Prospective AP2 v2 completion and canonical-checkout freeze gates; zero paid calls."""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import freeze_mpp009 as freezer


class Ap2V2FinalClearanceTests(unittest.TestCase):
    @contextmanager
    def final_case(self):
        with TemporaryDirectory() as temporary:
            gate = Path(temporary) / "ap2_v2"
            assignment = gate / "assignment-001/assignment_manifest.json"
            assignment.parent.mkdir(parents=True)
            episode_ids = ["ap2live2-" + digit * 24 for digit in "abcd"]
            study = "ap2-audit-purchase-invoice-release-live-002"
            frozen = {"schema": "ap2-live-prospective-assignment-v2",
                      "study_id": study, "planned_episodes": 4,
                      "public_rows": [{"episode_id": name} for name in episode_ids]}
            assignment.write_text(json.dumps(frozen))
            assignment_sha = freezer.sha(assignment)
            lock = gate / "first-freeze.lock.json"
            lock.write_text(json.dumps({"schema": "ap2-live-v2-first-freeze-v1",
                "assignment_manifest_sha256": assignment_sha, "paid_model_calls": 0}))
            rows = []
            runs = {}
            record_hashes = {}
            for name in episode_ids:
                directory = gate / "runs-001/episodes" / name
                (directory / "audit-purchase").mkdir(parents=True)
                (directory / "erc8183").mkdir()
                raw = directory / "inspect.eval"
                purchase = directory / "audit-purchase/native-audit-purchase.json"
                native = directory / "erc8183/native-evidence.json"
                raw.write_bytes(name.encode())
                purchase.write_text("{}")
                native.write_text("{}")
                ident = f"ap2live2-{assignment_sha[:12]}-{name}"
                record = {"schema": "ap2-live-paid-episode-v2", "status": "COMPLETE",
                    "episode_id": name, "assignment_manifest_sha256": assignment_sha,
                    "ledger_run_id": ident, "inspect_sha256": freezer.sha(raw),
                    "native_purchase_sha256": freezer.sha(purchase),
                    "native_erc8183_sha256": freezer.sha(native),
                    "model_cost_usd": "0.200840"}
                record_path = directory / "episode_record.json"
                record_path.write_text(json.dumps(record))
                record_hashes[name] = freezer.sha(record_path)
                runs[ident] = {"status": "SETTLED", "actual_usd": "0.20084",
                               "evidence_ref": "sha256:" + freezer.sha(raw)}
                rows.append({"episode_id": name, "status": "COMPLETE",
                             "model_cost_usd": "0.200840"})
            collection = gate / "collection-001-final.json"
            report = {"schema": "ap2-live-itt-collection-v2", "study_id": study,
                      "assignment_manifest_sha256": assignment_sha,
                      "planned_episodes": 4, "completed_episodes": 4,
                      "stopped_episodes": 0, "pending_episodes": 0,
                      "shared_ledger_seq": 145, "rows": rows}
            collection.write_text(json.dumps(report))
            state = {"seq": 145, "last_hash": "e" * 64, "runs": runs}
            with patch.multiple(freezer, AP2_V2_GATE=gate,
                    AP2_V2_ASSIGNMENT_SHA256=assignment_sha,
                    AP2_V2_LOCK_SHA256=freezer.sha(lock),
                    AP2_V2_FINAL_COLLECTION_SHA256=freezer.sha(collection),
                    AP2_V2_FINAL_LEDGER_SEQ=145,
                    AP2_V2_FINAL_LEDGER_HASH="e" * 64,
                    AP2_V2_FINAL_EPISODE_RECORD_SHA256=record_hashes):
                yield gate, state, report

    def test_final_four_rows_bind_raw_native_and_decimal_ledger(self):
        with self.final_case() as (_, state, _):
            proof = freezer.ap2_v2_final_evidence(state)
            self.assertEqual(proof["ap2_v2_disposition"], "COMPLETE_NO_PENDING")
            self.assertEqual(len(proof["ap2_v2_settled_runs"]), 4)
            self.assertEqual(proof["ap2_v2_settled_runs"][0]["settled_model_cost_usd"],
                             "0.20084")

    def test_final_rejects_pending_row_even_with_new_collection_hash(self):
        with self.final_case() as (gate, state, report):
            report["pending_episodes"] = 1
            report["completed_episodes"] = 3
            collection = gate / "collection-001-final.json"
            collection.write_text(json.dumps(report))
            with patch.object(freezer, "AP2_V2_FINAL_COLLECTION_SHA256",
                              freezer.sha(collection)):
                with self.assertRaisesRegex(ValueError, "four COMPLETE"):
                    freezer.ap2_v2_final_evidence(state)

    def test_final_rejects_wrong_ledger_cost_raw_archive_or_extra_run(self):
        with self.final_case() as (gate, state, _):
            ident = next(iter(state["runs"]))
            original = state["runs"][ident]["actual_usd"]
            state["runs"][ident]["actual_usd"] = "0.20085"
            with self.assertRaisesRegex(ValueError, "settled billing differs"):
                freezer.ap2_v2_final_evidence(state)
            state["runs"][ident]["actual_usd"] = original
            raw = next((gate / "runs-001/episodes").glob("*/inspect.eval"))
            raw.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "settled billing differs"):
                freezer.ap2_v2_final_evidence(state)
            raw.write_bytes(raw.parent.name.encode())
            state["runs"]["ap2live2-unassigned"] = {"status": "SETTLED"}
            with self.assertRaisesRegex(ValueError, "unassigned AP2 v2"):
                freezer.ap2_v2_final_evidence(state)

    def test_clearance_remains_absent_after_final_evidence(self):
        with TemporaryDirectory() as temporary, \
             patch.object(freezer, "CLEARANCE", Path(temporary) / "clearance.json"), \
             patch.object(freezer, "ap2_v2_final_evidence",
                          return_value={"ap2_v2_disposition": "COMPLETE_NO_PENDING"}):
            with self.assertRaisesRegex(ValueError, "cross-study sequencing record is absent"):
                freezer.cross_study_clearance({})
            self.assertFalse((Path(temporary) / "clearance.json").exists())


class CanonicalCheckoutTests(unittest.TestCase):
    def test_isolated_worktree_rejected_before_git_or_budget(self):
        with TemporaryDirectory() as temporary, \
             patch.object(freezer, "ROOT", Path(temporary) / "worktree"), \
             patch.object(freezer, "PROJECT_ROOT", Path(temporary) / "canonical"), \
             patch.object(freezer.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "not the canonical project checkout"):
                freezer.canonical_checkout_preflight()
            run.assert_not_called()

    def test_dirty_or_untracked_source_rejected(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            clean_top = SimpleNamespace(stdout=str(root), returncode=0)
            dirty = SimpleNamespace(stdout=" M scripts/freeze_mpp009.py", returncode=0)
            clean = SimpleNamespace(stdout="", returncode=0)
            untracked = SimpleNamespace(stdout="", returncode=1)
            with patch.object(freezer, "ROOT", root), \
                 patch.object(freezer, "PROJECT_ROOT", root), \
                 patch.object(freezer.subprocess, "run",
                              side_effect=[clean_top, dirty]):
                with self.assertRaisesRegex(ValueError, "tracked source must be committed"):
                    freezer.canonical_checkout_preflight()
            with patch.object(freezer, "ROOT", root), \
                 patch.object(freezer, "PROJECT_ROOT", root), \
                 patch.object(freezer, "source_inventory",
                              return_value={"new_source.py": "a" * 64}), \
                 patch.object(freezer.subprocess, "run",
                              side_effect=[clean_top, clean, untracked]):
                with self.assertRaisesRegex(ValueError, "untracked path"):
                    freezer.canonical_checkout_preflight()


if __name__ == "__main__":
    unittest.main()
