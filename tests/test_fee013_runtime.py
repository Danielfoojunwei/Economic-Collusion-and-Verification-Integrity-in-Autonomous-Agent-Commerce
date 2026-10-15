"""FEE013 source-level monetary, hold and offline control gates."""

from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import unittest

from inspect_ai.log import read_eval_log

from agent_economic_trust.fee013_budget import (EXACT_OPEN_IDS,
                                                exact_prior_holds,
                                                same_usd_amount)
from agent_economic_trust.fee013_offline import ARCHIVE, verify as verify_offline
from agent_economic_trust.fee013_plan import CANONICAL_LEDGER
from agent_economic_trust.fee013_boundary import reported_reasoning
from agent_economic_trust.remote_budget import BudgetLedger


class Fee013RuntimeGates(unittest.TestCase):
    def test_settled_usd_uses_numeric_decimal_equality(self):
        self.assertTrue(same_usd_amount("0.05069", "0.050690"))
        self.assertTrue(same_usd_amount("0.050690", "0.05069"))
        self.assertTrue(same_usd_amount("0E-7", "0.000000"))
        for different in ("0.050691", "0.05068", "0.15069"):
            self.assertFalse(same_usd_amount("0.05069", different))
        for invalid in ("NaN", "Infinity", "-Infinity", "-0.01", "nonsense", None,
                        0.05069, True):
            self.assertFalse(same_usd_amount("0.05069", invalid))
            self.assertFalse(same_usd_amount(invalid, "0.05069"))

    def test_three_old_holds_and_frozen_fee012_settlement_retained(self):
        state = BudgetLedger(CANONICAL_LEDGER).snapshot()
        result = exact_prior_holds(state)
        self.assertEqual(set(result["exact_open_run_ids"]), EXACT_OPEN_IDS)
        self.assertEqual(Decimal(result["prior_reserved_usd"]), Decimal("14.094300"))
        fee012 = [item for name, item in state["runs"].items()
                  if name.startswith("fee012-")]
        self.assertEqual(len(fee012), 1)
        self.assertEqual(fee012[0]["status"], "SETTLED")
        self.assertTrue(same_usd_amount(fee012[0]["actual_usd"], "0.050690"))
        changed = json.loads(json.dumps(state))
        changed["unknown_run_ids"] = ["unreconciled"]
        with self.assertRaises(ValueError):
            exact_prior_holds(changed)
        changed = json.loads(json.dumps(state))
        changed["reserved_usd"] = "14.094299"
        with self.assertRaises(ValueError):
            exact_prior_holds(changed)

    def test_eight_predecessor_native_cases_and_seven_tamper_negatives(self):
        report = verify_offline(ARCHIVE)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["model_behavior_tier"], "SCRIPTED_SIMULATION")
        self.assertEqual(report["paid_model_calls"], 0)
        self.assertEqual(report["replay"]["scripted_native_cases_reverified"], 8)
        self.assertEqual(report["replay"]["scripted_bad_accept_positive_controls"], 1)
        self.assertEqual(report["replay"]["tamper_negatives_reverified"], 7)

    def test_reported_reasoning_reads_raw_saved_model_usage(self):
        source = (Path(__file__).resolve().parents[1] /
                  "artifacts/gates/ERC8183_FEE012/runs-001/episodes/"
                  "fee012-9d83103c141f26e01bb20f64/inspect.eval")
        sample = read_eval_log(str(source), resolve_attachments=True).samples[0]
        measured = reported_reasoning(sample)
        self.assertEqual(measured["reported_reasoning_tokens_by_role"],
                         {"provider": 139, "auditor": 33})
        self.assertEqual(measured["reported_reasoning_tokens_missing_by_role"],
                         {"provider": 0, "auditor": 0})


if __name__ == "__main__":
    unittest.main()
