"""Read-only FEE012 predecessor, reserve and archived native-prefix gates."""

from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import unittest

from agent_economic_trust.fee012_budget import EXACT_OPEN_IDS, exact_prior_holds
from agent_economic_trust.fee012_offline import ARCHIVE, cases, replay_scripted_receipt
from agent_economic_trust.fee012_plan import ROWS, required_headroom
from agent_economic_trust.remote_budget import BudgetLedger
from scripts.fee012_collect import _native_prefix
from scripts.fee012_freeze import (X402_FINAL, _budget, clearance_preview,
                                    source_inventory)
from agent_economic_trust.mpp008_pricing import pricing_snapshots
from agent_economic_trust.fee012_plan import CANONICAL_LEDGER


class Fee012RuntimeGates(unittest.TestCase):
    def test_exact_three_prior_holds_and_full_block_headroom(self):
        state = BudgetLedger(CANONICAL_LEDGER).snapshot()
        hold = exact_prior_holds(state)
        self.assertEqual(set(hold["exact_open_run_ids"]), EXACT_OPEN_IDS)
        self.assertEqual(hold["prior_reserved_usd"], "14.094300")
        prices = pricing_snapshots()
        budget = _budget(state, prices)
        self.assertEqual(Decimal(budget["full_block_plus_contingency_residual_usd"]),
                         required_headroom(prices, ROWS))
        self.assertLess(Decimal(budget["full_block_plus_contingency_residual_usd"]),
                        Decimal(state["available_usd"]))
        changed = dict(state)
        changed["reserved_usd"] = "14.094299"
        with self.assertRaises(ValueError):
            exact_prior_holds(changed)
        changed = dict(state)
        changed["unknown_run_ids"] = ["unreconciled"]
        with self.assertRaises(ValueError):
            exact_prior_holds(changed)

    def test_predecessor_collection_reopens_and_source_closure_exists(self):
        state = BudgetLedger(CANONICAL_LEDGER).snapshot()
        preview = clearance_preview(state)
        self.assertEqual(preview["status"],
                         "GO_AFTER_X402012_COMPLETE_COLLECTION")
        self.assertEqual(preview["x402012_final_collection_sha256"],
                         __import__("hashlib").sha256(X402_FINAL.read_bytes()).hexdigest())
        names = source_inventory()
        self.assertIn("scripts/fee012_collect.py", names)
        self.assertIn("src/agent_economic_trust/fee012_remote.py", names)

    def test_model_visible_prefix_reconstructed_from_scripted_native_receipt(self):
        name, row, verdict = cases()[0]
        self.assertIsNotNone(verdict)
        path = ARCHIVE / name / "native-evidence.json"
        self.assertEqual(replay_scripted_receipt(path, row)["status"],
                         "COMPLETE_VERIFIED")
        saved = json.loads(path.read_text())
        prefix = _native_prefix(row, saved)
        self.assertEqual(prefix["obligation_id"], row.obligation_id)
        self.assertEqual(prefix["prior_settled_amount_minor"], 0)
        altered = json.loads(path.read_text())
        altered["terms"]["evaluator_fee_bp"] = 999
        with self.assertRaises(ValueError):
            _native_prefix(row, altered)


if __name__ == "__main__":
    unittest.main()
