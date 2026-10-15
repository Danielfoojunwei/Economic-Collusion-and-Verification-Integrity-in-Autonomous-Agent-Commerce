"""Synthetic known-effect and failure-path checks; no research data used."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import unittest

from agent_economic_trust.w19_analysis import (
    CELLS, PairOutcome, blocked_randomization_pvalue, contrast, holm_two,
    pair_bootstrap_interval,
)
from agent_economic_trust.w19_power import PilotCalibration, simulate_power


def known_effect_rows() -> list[PairOutcome]:
    rows = []
    for truth in (0, 1):
        for cell in CELLS:
            for number in range(4):
                rows.append(PairOutcome(
                    pair_id=f"pair-{truth}-{cell}-{number}",
                    block=f"model-a|family-a|truth-{truth}", truth=truth,
                    cell=cell, scheduled=2,
                    wrong_paid=2 if truth == 0 and cell[0] == "1" else 0,
                    wrong_paid_unknown=0,
                    checked=0 if cell[1] == "1" else 2,
                    checked_unknown=0,
                ))
    return rows


def synthetic_pilot() -> dict:
    return {
        "schema": "w19-real-g4-pilot-v1", "source_gate": "G4",
        "randomized": True, "model_tier": "REAL_LLM_REMOTE_APPROVED",
        "payment_tier": "NATIVE_LOCAL_PROTOCOL",
        "source_run_sha256": "a" * 64,
        "max_observed_task_cost_usd": "0.05",
        "cells": {cell: {
            "bad_assigned": 2, "bad_wrong_paid": 0,
            "bad_unresolved": 0, "all_assigned": 4,
            "checked": 3, "check_unresolved": 0,
        } for cell in CELLS},
    }


class W19AnalysisTest(unittest.TestCase):
    def test_known_pair_level_effect_and_randomization_uncertainty(self):
        rows = known_effect_rows()
        wrong_pay = contrast(rows, "wrong_paid", "R")
        check = contrast(rows, "checked", "S")
        self.assertEqual(wrong_pay["assigned_pairs"], 32)
        self.assertEqual(wrong_pay["assigned_tasks"], 64)
        self.assertAlmostEqual(wrong_pay["estimate"], 1.0)
        self.assertAlmostEqual(check["estimate"], -1.0)
        self.assertLess(blocked_randomization_pvalue(
            rows, "wrong_paid", "R", permutations=999, seed=8), 0.05)
        self.assertLess(blocked_randomization_pvalue(
            rows, "checked", "S", permutations=999, seed=8), 0.05)
        self.assertEqual(pair_bootstrap_interval(
            rows, "wrong_paid", "R", replicates=99), (1.0, 1.0))

    def test_missing_remains_in_itt_and_blocks_point_test(self):
        rows = known_effect_rows()
        index = next(i for i, row in enumerate(rows)
                     if row.truth == 0 and row.cell[0] == "1")
        rows[index] = replace(rows[index], wrong_paid=1, wrong_paid_unknown=1)
        result = contrast(rows, "wrong_paid", "R")
        self.assertEqual(result["assigned_pairs"], 32)
        self.assertEqual(result["unresolved_tasks"], 1)
        self.assertIsNone(result["estimate"])
        self.assertLess(result["itt_risk_difference_bounds"][0], 1)
        self.assertEqual(result["itt_risk_difference_bounds"][1], 1)
        with self.assertRaisesRegex(ValueError, "unresolved"):
            blocked_randomization_pvalue(rows, "wrong_paid", "R", permutations=9)
        with self.assertRaisesRegex(ValueError, "unresolved"):
            pair_bootstrap_interval(rows, "wrong_paid", "R", replicates=9)

    def test_pair_is_one_cluster_and_arm_balance_is_required(self):
        rows = known_effect_rows()
        with self.assertRaisesRegex(ValueError, "pair appears more than once"):
            contrast(rows + [rows[0]], "checked", "S")
        with self.assertRaisesRegex(ValueError, "balanced"):
            contrast(rows[1:], "checked", "S")
        with self.assertRaisesRegex(ValueError, "outcomes exceed"):
            replace(rows[0], checked=3)

    def test_holm_familywise_thresholds(self):
        self.assertEqual(holm_two(0.024, 0.049),
                         {"R_wrong_paid": True, "S_check": True})
        self.assertEqual(holm_two(0.026, 0.001),
                         {"R_wrong_paid": True, "S_check": True})
        self.assertEqual(holm_two(0.026, 0.04),
                         {"R_wrong_paid": False, "S_check": False})

    def test_pilot_provenance_and_full_arms_required(self):
        pilot = synthetic_pilot()
        self.assertEqual(PilotCalibration.parse(pilot).source_run_sha256, "a" * 64)
        pilot["model_tier"] = "SCRIPTED_SIMULATION"
        with self.assertRaisesRegex(ValueError, "real G4 pilot"):
            PilotCalibration.parse(pilot)
        pilot["model_tier"] = "REAL_LLM_REMOTE_APPROVED"
        pilot["cells"].pop("111")
        with self.assertRaisesRegex(ValueError, "all eight"):
            PilotCalibration.parse(pilot)

    def test_power_scenarios_are_deterministic_and_budgeted(self):
        pilot = PilotCalibration.parse(synthetic_pilot())
        options = dict(
            pairs_per_cell_truth_block=2, tasks_per_pair=2,
            task_families=2, model_versions=2, rho=0.2,
            repetitions=8, seed=13,
            remaining_authorized_usd=Decimal("20"),
        )
        first = simulate_power(pilot, **options)
        self.assertEqual(first, simulate_power(pilot, **options))
        self.assertEqual(first["pairs"], 128)
        self.assertEqual(first["tasks"], 256)
        self.assertEqual(first["projected_model_spend_usd"], "16.0000")
        self.assertTrue(first["within_current_authorized_spend"])
        self.assertIn("unresolved_as_event", first["scenarios"])
        options["remaining_authorized_usd"] = Decimal("1")
        self.assertFalse(simulate_power(pilot, **options)["within_current_authorized_spend"])


if __name__ == "__main__":
    unittest.main()
