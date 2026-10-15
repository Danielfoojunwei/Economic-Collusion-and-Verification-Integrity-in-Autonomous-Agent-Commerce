"""Regression and integrity tests for the administrative FEE010 closure."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from agent_economic_trust import fee010_closure as closure
from agent_economic_trust.remote_budget import BudgetLedger
from scripts.verify_erc8183_fee_readiness import source_inventory as old_inventory


class Fee010ClosureTests(unittest.TestCase):
    def test_closure_retains_every_frozen_row_without_model_trials(self) -> None:
        saved, rows = closure.verify_closure()
        self.assertEqual(saved["schema"], "fee010-preexecution-closure-v1")
        self.assertEqual(saved["status"], "CLOSED_STOPPED_BEFORE_EXECUTION")
        self.assertEqual((saved["planned_episodes"], saved["completed_episodes"],
                          saved["stopped_before_execution_episodes"],
                          saved["pending_episodes"], saved["paid_model_calls"]),
                         (8, 0, 8, 0, 0))
        self.assertEqual([item["episode_id"] for item in saved["rows"]],
                         [row.episode_id for row in rows])
        self.assertEqual({item["status"] for item in saved["rows"]},
                         {"STOPPED_BEFORE_EXECUTION"})
        self.assertEqual(saved["shared_ledger_fee010_run_ids"], [])
        self.assertFalse(saved["old_run_directory_present"])
        self.assertEqual(saved["old_assignment_sha256"], closure.OLD_ASSIGNMENT_SHA256)
        self.assertEqual(saved["old_lock_sha256"], closure.OLD_LOCK_SHA256)
        self.assertEqual(saved["old_readiness_sha256"], closure.OLD_READINESS_SHA256)
        self.assertEqual(saved["read_only_verifier_error"],
                         {"type": "ValueError",
                          "message": "frozen fee study assignment/source differs"})

    def test_original_verifier_still_fails_only_on_overridden_preview_fields(self) -> None:
        saved, _ = closure.original_clearance()
        self.assertEqual(set(saved["preview_mismatch"]), {"schema", "status"})
        script = ("from scripts.freeze_erc8183_fee import verify\n"
                  "try:\n    verify()\n"
                  "except ValueError as exc:\n"
                  "    assert str(exc) == 'frozen fee study assignment/source differs'\n"
                  "else:\n    raise AssertionError('old verifier unexpectedly passed')\n")
        python = Path("/workspace/upstreams/orbit-smoke/.venv/bin/python")
        main_root = closure.ROOT
        result = subprocess.run([str(python), "-c", script], cwd=main_root,
                                env={"PYTHONPATH": f"{main_root / 'src'}:{main_root}",
                                     "PYTHON_DOTENV_DISABLED": "1"},
                                capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_changed_closure_or_ledger_call_is_rejected(self) -> None:
        with patch.object(closure, "CLOSURE_SHA256", "0" * 64):
            with self.assertRaisesRegex(ValueError, "final closure changed"):
                closure.verify_closure()
        current = BudgetLedger(closure.CANONICAL_LEDGER).snapshot()
        altered = {**current, "runs": {**current["runs"],
                                       "fee010-unrecorded": {"status": "SETTLED"}}}
        class FakeLedger:
            def __init__(self, path):
                self.path = path
            def snapshot(self):
                return altered
        with patch.object(closure, "BudgetLedger", FakeLedger):
            with self.assertRaisesRegex(ValueError, "shared-ledger run"):
                closure.verify_closure()

    def test_new_closure_files_do_not_expand_frozen_fee010_source_set(self) -> None:
        saved, _ = closure.verify_closure()
        inventory = old_inventory()
        self.assertEqual(len(inventory), 28)
        self.assertNotIn("src/agent_economic_trust/fee010_closure.py", inventory)
        self.assertNotIn("tests/test_fee010_closure.py", inventory)
        self.assertEqual(saved["old_source_inventory_sha256"],
                         sha256(json.dumps(
                             inventory, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode()).hexdigest())


if __name__ == "__main__":
    unittest.main()
