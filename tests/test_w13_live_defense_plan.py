"""Offline W13 planning checks; no paid model call or chain mutation."""

from __future__ import annotations

from hashlib import sha256
import unittest

from agent_economic_trust.w10_factorial import frozen_fixtures, make_assignments
from agent_economic_trust.w13_live_defense_plan import (
    DEFENSE_ARMS, VisibleDecision, dispatch_guard, prospective_manifest,
    prospective_schedule, replay_verified_g4, retrospective_spot_cells,
)


PAIR_SEED = "0" * 63 + "1"
DEFENSE_SEED = "0" * 63 + "2"
SPOT_SEED = "0" * 63 + "3"


def verified_records(trials):
    truth = {fixture.fixture_id: fixture.truth for fixture in frozen_fixtures()}
    records = []
    for trial in trials:
        # A recorded live ACCEPT is a source verdict, not a simulated model
        # call in these tests. The model tier label exercises only validation.
        records.append({
            "trial_id": trial.trial_id, "pair_id": trial.pair_id,
            "status": "COMPLETE", "evidence_validation": "PASS",
            "oracle_truth": truth[trial.fixture_id], "verdict": "ACCEPT",
            "payment_status": "PAID", "model_tier": "REAL_LLM",
            "payment_tier": "NATIVE_LOCAL", "channel_isolation_audit": "PASS",
            "treatment_audit": "PASS", "check_spent_units": 0,
            "native_inspect_sha256": sha256(trial.trial_id.encode()).hexdigest(),
            "native_payment_sha256": sha256(trial.pair_id.encode()).hexdigest(),
            "model_cost_usd_estimate": "0.01",
        })
    return records


class ProspectiveDefenseAssignmentTests(unittest.TestCase):
    def test_balanced_fresh_pair_schedule_and_deterministic_manifest(self):
        first = prospective_schedule(PAIR_SEED, DEFENSE_SEED)
        self.assertEqual(first, prospective_schedule(PAIR_SEED, DEFENSE_SEED))
        self.assertEqual(len(first), 32)
        self.assertEqual(len({row.pair_id for row in first}), 32)
        self.assertEqual(len({row.independent_reviewer_id for row in first}), 32)
        truth = {fixture.fixture_id: fixture.truth for fixture in frozen_fixtures()}
        for arm in DEFENSE_ARMS:
            rows = [row for row in first if row.defense_arm == arm]
            self.assertEqual(len(rows), 8)
            self.assertEqual(len({row.economic_cell for row in rows}), 8)
            self.assertEqual(sum(truth[row.fixture_id] for row in rows), 4)
            self.assertEqual(sum(row.spot_selected for row in rows),
                             4 if arm in {"digest_spot_check", "principal_check_budget"} else 0)
        self.assertEqual(len(prospective_manifest(PAIR_SEED, DEFENSE_SEED)["rows"]), 32)
        self.assertEqual(prospective_manifest(PAIR_SEED, DEFENSE_SEED)["execution_status"],
                         "PLANNED_ONLY")

    def test_bad_seeds_or_reused_seed_fail(self):
        with self.assertRaisesRegex(ValueError, "seeds must differ"):
            prospective_schedule(PAIR_SEED, PAIR_SEED)
        with self.assertRaisesRegex(ValueError, "32 lowercase hex bytes"):
            prospective_schedule(PAIR_SEED, "bad")


class GuardBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.visible = VisibleDecision("trial-a", "ACCEPT", "a" * 64, "a" * 64)

    def test_truth_is_only_available_through_priced_callback(self):
        self.assertNotIn("truth", vars(self.visible))
        calls = []

        def fail_check():
            calls.append("charged")
            return "FAIL"

        result = dispatch_guard(self.visible, arm="digest_spot_check",
                                selected=True, priced_check=fail_check)
        self.assertEqual(calls, ["charged"])
        self.assertEqual((result.final_verdict, result.extra_check_units), ("REJECT", 1))
        unchecked = dispatch_guard(self.visible, arm="unchecked_reference",
                                   selected=True, priced_check=fail_check)
        self.assertEqual((unchecked.final_verdict, unchecked.extra_check_units), ("ACCEPT", 0))
        self.assertEqual(calls, ["charged"])

    def test_digest_substitution_blocks_without_hidden_oracle(self):
        swapped = VisibleDecision("trial-a", "ACCEPT", "a" * 64, "b" * 64)

        def forbidden():
            self.fail("digest mismatch should block before oracle")

        guarded = dispatch_guard(swapped, arm="principal_check_budget",
                                 selected=True, priced_check=forbidden)
        self.assertEqual((guarded.final_verdict, guarded.extra_check_units), ("REJECT", 0))

    def test_unknown_check_and_nonlive_reviewer_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "fresh live reviewer"):
            dispatch_guard(self.visible, arm="independent_reviewer",
                           selected=True, priced_check=lambda: "PASS")
        with self.assertRaisesRegex(ValueError, "unknown status"):
            dispatch_guard(self.visible, arm="digest_spot_check",
                           selected=True, priced_check=lambda: "unknown")
        with self.assertRaisesRegex(ValueError, "final"):
            dispatch_guard(VisibleDecision("a", "ABSTAIN", "a", "a"),
                           arm="digest_spot_check", selected=True,
                           priced_check=lambda: "PASS")


class RetrospectiveReplayTests(unittest.TestCase):
    def setUp(self):
        self.trials = make_assignments(PAIR_SEED)
        self.records = verified_records(self.trials)

    def test_same_checked_cells_cost_and_projected_error_are_explicit(self):
        selected = retrospective_spot_cells(SPOT_SEED)
        self.assertEqual(len(selected), 4)
        output = replay_verified_g4(self.trials, self.records, seed_hex=SPOT_SEED)
        self.assertEqual(output["payment_tier"], "SOURCE_NATIVE_LOCAL_DEFENSE_NOT_EXECUTED")
        self.assertTrue(output["matched_extra_check_cost"])
        arms = output["arms"]
        self.assertEqual(arms["unchecked_reference"]["extra_check_spent_units"], 0)
        for arm in ("digest_spot_check", "principal_check_budget"):
            self.assertEqual(arms[arm]["valid_source_count"], 32)
            self.assertEqual(arms[arm]["extra_check_spent_units"], 16)
            self.assertEqual(arms[arm]["projected_bad_paid_observed"], 8)
            self.assertEqual(arms[arm]["projected_good_unpaid_observed"], 0)
            self.assertTrue(all(row["defense_status"] == "PROJECTED_ONLY"
                                for row in arms[arm]["rows"]))
        self.assertEqual(arms["unchecked_reference"]["projected_bad_paid_observed"], 16)
        self.assertNotIn("independent_reviewer", arms)

    def test_missing_run_stays_in_denominator_and_cannot_be_scored(self):
        self.records[0] = dict(self.records[0], status="PENDING",
                               evidence_validation="NO_OUTPUT", payment_status="UNKNOWN")
        output = replay_verified_g4(self.trials, self.records, seed_hex=SPOT_SEED)
        for arm in output["arms"].values():
            self.assertEqual(arm["valid_source_count"], 31)
            self.assertEqual(arm["pending_source_count"], 1)
            self.assertEqual(sum(row["defense_status"] == "PENDING" for row in arm["rows"]), 1)

    def test_invalid_complete_record_or_missing_assignment_rejected(self):
        self.records[0] = dict(self.records[0], oracle_truth=9)
        with self.assertRaisesRegex(ValueError, "disagrees"):
            replay_verified_g4(self.trials, self.records, seed_hex=SPOT_SEED)
        with self.assertRaisesRegex(ValueError, "every assigned pair"):
            replay_verified_g4(self.trials, self.records[:-1], seed_hex=SPOT_SEED)


if __name__ == "__main__":
    unittest.main()
