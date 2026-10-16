"""Read-only checks for the five-row successor's predecessor and freeze gates."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_economic_trust.remote_budget import BudgetLedger
from scripts import freeze_mpp011 as freeze


class ProspectiveFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = BudgetLedger(freeze.CANONICAL_LEDGER_PATH).snapshot()

    def _before_x402(self):
        """A synthetic predecessor snapshot independent of x402's live progress."""
        state = deepcopy(self.state)
        state["runs"] = {name: run for name, run in state["runs"].items()
                         if not name.startswith("x402011-")}
        state["reserved_usd"] = str(Decimal("6.307840") + freeze.FEE_HOLD_USD)
        return state

    def test_archived_stopped_denominators_and_hold_are_bound(self):
        mpp = freeze._predecessor(freeze.MPP010, self.state)
        fee = freeze._predecessor(freeze.FEE011, self.state)
        held = freeze._fee_failed_request_hold(self.state)
        self.assertEqual(mpp["status_counts"],
                         {"COMPLETE": 0, "STOPPED": 1, "PENDING": 9})
        self.assertEqual(fee["status_counts"],
                         {"COMPLETE": 0, "STOPPED": 1, "PENDING": 7})
        self.assertEqual(held["reserved_usd"], "3.379164")
        changed = deepcopy(self.state)
        changed["runs"][freeze.FEE_HOLD_ID]["status"] = "SETTLED"
        with self.assertRaisesRegex(ValueError, "hold is missing or changed"):
            freeze._fee_failed_request_hold(changed)
        contingent = freeze.x402_contingent_hold(self.state)
        self.assertEqual(contingent["status"], "CONTINGENT")
        self.assertEqual(contingent["reserved_usd"], "4.407296")
        normalized = freeze.mpp006_with_x402(
            self.state, additional_reservation_usd=freeze.FEE_HOLD_USD)
        self.assertEqual(normalized["status"], "CONTINGENT")

    def test_x402_requires_final_report_once_frozen_or_paid(self):
        with tempfile.TemporaryDirectory() as temporary:
            gate = Path(temporary)
            with patch.object(freeze, "X402_GATE", gate):
                state = self._before_x402()
                self.assertEqual(freeze._x402_disposition(state, None)["status"],
                                 "PROSPECTIVE_ONLY_NO_PAID_GATE")
                with self.assertRaisesRegex(ValueError, "partial gate"):
                    freeze._x402_disposition(state, "artifacts/gates/X402_LIVE011/collection.json")
                (gate / "assignment-001").mkdir()
                (gate / "assignment-001/assignment_manifest.json").write_text("{}")
                with self.assertRaisesRegex(ValueError, "explicit final collection"):
                    freeze._x402_disposition(state, None)

    def test_clearance_requires_frozen_x402_gate(self):
        with patch.object(freeze, "X402_GATE", Path("/nonexistent-mpp011-test-gate")):
            with self.assertRaisesRegex(ValueError, "paid run or partial gate"):
                freeze.clearance_preview(self.state)

    def test_freeze_needs_explicit_one_time_switch(self):
        with patch.dict("os.environ", {"MPP011_FREEZE_ALLOWED": "false"}):
            with self.assertRaisesRegex(ValueError, "explicit MPP011"):
                freeze.freeze(seed_hex="ab" * 32)


if __name__ == "__main__":
    unittest.main()
