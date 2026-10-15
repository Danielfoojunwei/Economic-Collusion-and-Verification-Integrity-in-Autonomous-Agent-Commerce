"""Exercise the guarded operator only on a temporary cloned ledger."""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

# Import the budget package before the operator; this also lets an isolated
# checkout test against the separately developed, prospective ledger API.
from agent_economic_trust import remote_budget
import mark_mpp006_contingent as operator


class MPP006ContingentOperatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_ledger_sha = operator._sha(operator.CANONICAL_LEDGER)
        self.original_anchor_sha = operator._sha(operator._anchor(operator.CANONICAL_LEDGER))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = Path(self.temp.name) / "ledger.jsonl"
        archived = operator.EVIDENCE.parent / "prestate-openrouter-ledger.jsonl"
        shutil.copy2(archived, self.ledger)
        shutil.copy2(operator._anchor(archived), operator._anchor(self.ledger))

    def tearDown(self) -> None:
        self.assertEqual(operator._sha(operator.CANONICAL_LEDGER), self.original_ledger_sha)
        self.assertEqual(operator._sha(operator._anchor(operator.CANONICAL_LEDGER)),
                         self.original_anchor_sha)

    def test_dry_run_is_read_only_and_temp_clone_keeps_full_hold(self) -> None:
        before_sha = operator._sha(self.ledger)
        dry = operator.run(ledger_path=self.ledger)
        self.assertFalse(dry["applied"])
        self.assertEqual(operator._sha(self.ledger), before_sha)
        self.assertTrue(hasattr(remote_budget.BudgetLedger, "mark_contingent"))

        applied = operator.run(ledger_path=self.ledger, apply=True)
        self.assertTrue(applied["applied"])
        self.assertEqual(applied["new_ledger_seq"], 133)
        after = remote_budget.read_ledger(self.ledger)
        self.assertEqual(after["runs"][operator.RUN_ID]["status"], "CONTINGENT")
        self.assertEqual(after["reserved_usd"], operator.EXPECTED_RESERVE)
        self.assertEqual(after["settled_spent_usd"], "5.31322")
        self.assertEqual(after["contingent_run_ids"], [operator.RUN_ID])
        self.assertEqual(after["unknown_run_ids"], [])
        self.assertFalse(after["blocked"])
        with self.assertRaises(ValueError):
            operator.run(ledger_path=self.ledger, apply=True)

    def test_anchor_tamper_fails_before_any_transition(self) -> None:
        original = operator._sha(self.ledger)
        operator._anchor(self.ledger).write_bytes(
            operator._anchor(self.ledger).read_bytes() + b"tampered")
        with self.assertRaisesRegex(ValueError, "ledger is not the original UNKNOWN prestate"):
            operator.run(ledger_path=self.ledger, apply=True)
        self.assertEqual(operator._sha(self.ledger), original)

    def test_evidence_hash_tamper_fails_before_any_transition(self) -> None:
        original = operator._sha(self.ledger)
        with patch.object(operator, "EVIDENCE_SHA256", "0" * 64):
            with self.assertRaisesRegex(ValueError, "saved conditional evidence SHA-256 differs"):
                operator.run(ledger_path=self.ledger, apply=True)
        self.assertEqual(operator._sha(self.ledger), original)


if __name__ == "__main__":
    unittest.main()
