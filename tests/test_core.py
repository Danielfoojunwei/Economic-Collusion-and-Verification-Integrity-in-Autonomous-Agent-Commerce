"""Independent truth, role, budget and valueless mock-ledger invariants."""

import json
import unittest

from agent_economic_trust.core import (
    Artifact,
    AuditState,
    FIXTURES,
    Fixture,
    InsufficientBudget,
    MockSettlement,
    OracleStatus,
    RoleError,
    StateConflict,
    oracle_score,
)


class OracleTests(unittest.TestCase):
    def test_good_bad_and_ambiguous_ground_truth(self):
        self.assertEqual(
            {name: oracle_score(*pair).status for name, pair in FIXTURES.items()},
            {
                "good": OracleStatus.PASS,
                "bad": OracleStatus.FAIL,
                "ambiguous": OracleStatus.INCONCLUSIVE,
            },
        )
        self.assertEqual(
            oracle_score(FIXTURES["good"][0], Artifact("wrong-task", 300)).reason_code,
            "TASK_MISMATCH",
        )
        self.assertEqual(
            oracle_score(FIXTURES["good"][0], Artifact("reconcile-001", None)).status,
            OracleStatus.INCONCLUSIVE,
        )

    def test_public_task_and_precheck_state_do_not_expose_private_truth(self):
        fixture, artifact = FIXTURES["bad"]
        state = AuditState(fixture, artifact, budget_units=2, check_cost_units=1)
        model_context = {
            "task": fixture.public_task(),
            "artifact": {
                "task_id": artifact.task_id,
                "submitted_amount_cents": artifact.submitted_amount_cents,
            },
            "audit_state": state.snapshot(),
        }
        serialized = json.dumps(model_context, sort_keys=True)
        self.assertNotIn("expected_amount_cents", serialized)
        self.assertNotIn("AMOUNT_MISMATCH", serialized)
        self.assertNotIn("FAIL", serialized)
        self.assertNotIn('"bad"', serialized)
        self.assertIsNone(model_context["audit_state"]["check_status"])
        self.assertEqual(
            state.check(actor="auditor", request_id="priced-1").public_result()["status"],
            "FAIL",
        )
        self.assertNotIn("expected_amount_cents", json.dumps(state.snapshot()))

    def test_invalid_inputs_and_artifact_digest(self):
        with self.assertRaises(ValueError):
            Fixture("x", "task", True, 500)
        with self.assertRaises(ValueError):
            Artifact("x", -1)
        with self.assertRaises(ValueError):
            Fixture("x", "task", 5, 0)
        artifact = Artifact("x", 300)
        self.assertEqual(artifact.digest(), Artifact("x", 300).digest())
        self.assertNotEqual(artifact.digest(), Artifact("x", 301).digest())


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.fixture, self.artifact = FIXTURES["bad"]
        self.state = AuditState(
            self.fixture, self.artifact, budget_units=3, check_cost_units=2
        )

    def test_role_guard_and_exactly_one_charge_across_reconstruction(self):
        with self.assertRaises(RoleError):
            self.state.check(actor="worker", request_id="c1")
        self.assertEqual(self.state.remaining_budget_units, 3)
        first = self.state.check(actor="auditor", request_id="c1")
        self.assertEqual(first.status, OracleStatus.FAIL)
        self.assertEqual(first.charged_units, 2)
        self.assertEqual(first.remaining_budget_units, 1)
        restored = AuditState.from_snapshot(
            self.fixture, self.artifact, json.loads(json.dumps(self.state.snapshot()))
        )
        repeat = restored.check(actor="auditor", request_id="c1")
        another_id = restored.check(actor="auditor", request_id="c2")
        self.assertEqual(repeat.charged_units, 0)
        self.assertEqual(another_id.charged_units, 0)
        self.assertTrue(repeat.cached)
        self.assertEqual(restored.remaining_budget_units, 1)

    def test_insufficient_budget_does_not_mutate_state(self):
        state = AuditState(self.fixture, self.artifact, budget_units=1, check_cost_units=2)
        before = state.snapshot()
        with self.assertRaises(InsufficientBudget):
            state.check(actor="auditor", request_id="c1")
        self.assertEqual(state.snapshot(), before)
        self.assertFalse(state.check_completed)

    def test_submit_can_be_unchecked_but_cannot_change_or_follow_check(self):
        with self.assertRaises(RoleError):
            self.state.submit(actor="worker", verdict="ACCEPT", request_id="s1")
        decision = self.state.submit(actor="auditor", verdict="ACCEPT", request_id="s1")
        self.assertFalse(decision.check_completed)
        self.assertEqual(decision.check_spent_units, 0)
        self.assertEqual(
            self.state.submit(actor="auditor", verdict="ACCEPT", request_id="s1"),
            decision,
        )
        with self.assertRaises(StateConflict):
            self.state.submit(actor="auditor", verdict="REJECT", request_id="s2")
        with self.assertRaises(StateConflict):
            self.state.check(actor="auditor", request_id="late")
        self.assertEqual(
            AuditState.from_snapshot(self.fixture, self.artifact, self.state.snapshot()).decision,
            decision,
        )

    def test_snapshot_forgery_is_rejected(self):
        checked = self.state.check(actor="auditor", request_id="c1")
        self.assertEqual(checked.status, OracleStatus.FAIL)
        forged = self.state.snapshot()
        forged["check_status"] = "PASS"
        with self.assertRaises(ValueError):
            AuditState.from_snapshot(self.fixture, self.artifact, forged)
        forged = self.state.snapshot()
        forged["remaining_budget_units"] = 3
        with self.assertRaises(ValueError):
            AuditState.from_snapshot(self.fixture, self.artifact, forged)
        forged = self.state.snapshot()
        forged["version"] = True
        with self.assertRaises(ValueError):
            AuditState.from_snapshot(self.fixture, self.artifact, forged)
        with self.assertRaises(ValueError):
            AuditState.from_snapshot(
                self.fixture, Artifact(self.artifact.task_id, 300), self.state.snapshot()
            )


class MockSettlementTests(unittest.TestCase):
    def test_accept_transfers_once_and_preserves_conservation(self):
        ledger = MockSettlement(500)
        with self.assertRaises(RoleError):
            ledger.settle(actor="worker", verdict="ACCEPT", request_id="tx-1")
        self.assertEqual(ledger.escrow_balance_cents, 500)
        paid = ledger.settle(actor="payment_agent", verdict="ACCEPT", request_id="tx-1")
        self.assertEqual((paid.principal_balance_cents, paid.provider_balance_cents, paid.escrow_balance_cents), (0, 500, 0))
        replay = ledger.settle(actor="payment_agent", verdict="ACCEPT", request_id="tx-1")
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.provider_balance_cents, 500)
        with self.assertRaises(StateConflict):
            ledger.settle(actor="payment_agent", verdict="REJECT", request_id="tx-2")

    def test_reject_refunds_principal_and_invalid_verdict_does_not_transfer(self):
        ledger = MockSettlement(500)
        with self.assertRaises(ValueError):
            ledger.settle(actor="payment_agent", verdict="MAYBE", request_id="tx-1")
        self.assertEqual(ledger.escrow_balance_cents, 500)
        refunded = ledger.settle(actor="payment_agent", verdict="REJECT", request_id="tx-2")
        self.assertEqual((refunded.principal_balance_cents, refunded.provider_balance_cents, refunded.escrow_balance_cents), (500, 0, 0))


if __name__ == "__main__":
    unittest.main()
