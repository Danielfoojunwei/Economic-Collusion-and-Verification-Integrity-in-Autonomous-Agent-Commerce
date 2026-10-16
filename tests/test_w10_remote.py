"""Offline W10 pilot boundary tests; no provider inference is made."""

from __future__ import annotations

from decimal import Decimal
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from inspect_ai import eval as inspect_eval

from agent_economic_trust.protected_receipts import (
    ReceiptArtifact, protected_receipt_orbit, receipt_oracle,
)
from agent_economic_trust.remote import RemoteBoundaryError
from agent_economic_trust.remote_budget import BudgetLedger, create_ledger
from agent_economic_trust.remote_pricing import pricing_snapshot
from agent_economic_trust.w10_remote import (
    FROZEN_ARTIFACT, ProtectedPlan, execute, pilot_case, preflight,
)
from tests.test_protected_receipts import scripted_model
from tests.test_remote_pricing import catalog_fixture


class ProtectedRemoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory(prefix="w10-remote-test-", dir="/workspace")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.ledger_path = self.root / "budget.jsonl"
        create_ledger(self.ledger_path, "20", "0.09527")
        self.plan = ProtectedPlan(
            model_id="openai/gpt-5.6-sol", world="good",
            output_dir=self.root / "fresh", ledger_path=self.ledger_path,
        )
        self.pricing = pricing_snapshot(catalog=catalog_fixture())
        self.canonical_ledger = patch(
            "agent_economic_trust.w10_remote.PROJECT_LEDGER_PATH", self.ledger_path,
        )
        self.canonical_ledger.start()
        self.addCleanup(self.canonical_ledger.stop)

    def test_good_bad_worlds_have_same_visible_claim_and_opposite_truth(self) -> None:
        good, bad = pilot_case("good"), pilot_case("bad")
        self.assertEqual(good.public_task(), bad.public_task())
        self.assertEqual(good.provider_copy(), bad.provider_copy())
        self.assertEqual(good.provider_digest(), bad.provider_digest())
        self.assertNotEqual(good.private_commitment(), bad.private_commitment())
        self.assertEqual(receipt_oracle(good, FROZEN_ARTIFACT).status.value, "PASS")
        self.assertEqual(receipt_oracle(bad, FROZEN_ARTIFACT).status.value, "FAIL")
        with self.assertRaises(RemoteBoundaryError):
            pilot_case("other")

    def test_dry_run_reserves_six_calls_from_existing_project_budget(self) -> None:
        with patch("agent_economic_trust.w10_remote.pricing_snapshot", return_value=self.pricing):
            forecast = preflight(self.plan)
        self.assertEqual(forecast["worst_case_reservation_usd"], "3.194880")
        self.assertEqual(forecast["max_provider_calls"], 6)
        self.assertEqual(forecast["payment_tier"], "NO_PAYMENT")
        self.assertTrue(forecast["ready_to_execute"])
        self.assertFalse(self.plan.output_dir.exists())
        self.assertEqual(BudgetLedger(self.ledger_path).snapshot()["seq"], 0)

    def test_paid_path_stays_disabled_without_explicit_environment(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RemoteBoundaryError):
                execute(self.plan, pricing=self.pricing)
        self.assertFalse(self.plan.output_dir.exists())
        self.assertEqual(BudgetLedger(self.ledger_path).snapshot()["seq"], 0)

    def test_missing_account_counter_holds_reservation_and_stops(self) -> None:
        env = {"ALLOW_EXTERNAL_MODEL_CALLS": "true", "MAX_REAL_SPEND": "20",
               "OPENROUTER_API_KEY": "unit-test-only", "ALLOW_MAINNET": "false"}
        with patch.dict(os.environ, env, clear=True):
            with patch("agent_economic_trust.w10_remote.account_usage_usd",
                       side_effect=RemoteBoundaryError("unavailable")):
                with self.assertRaises(RemoteBoundaryError):
                    execute(self.plan, pricing=self.pricing)
        snapshot = BudgetLedger(self.ledger_path).snapshot()
        self.assertTrue(snapshot["blocked"])
        self.assertEqual(snapshot["reserved_usd"], "3.19488")
        self.assertIn('"status": "PARTIAL"', (self.plan.output_dir / "STOPPED.json").read_text())

    def test_frozen_authored_artifact_rejects_different_worker_claim(self) -> None:
        case = pilot_case("good")
        wrong_freeze = ReceiptArtifact(case.task_id, 2, 200)
        [log] = inspect_eval(
            protected_receipt_orbit(case, budget_units=1, frozen_artifact=wrong_freeze),
            model=scripted_model("accept"), log_dir=str(self.root / "offline"),
            display="none", log_realtime=False, max_retries=0,
        )
        self.assertEqual(log.status, "success", log.error)
        sample = log.samples[0]
        rejected = [event for event in sample.events
                    if event.event == "tool" and event.function == "submit_receipt_artifact"
                    and event.error is not None]
        self.assertTrue(rejected)
        self.assertIn("frozen authored artifact", rejected[0].error.message)
        self.assertIsNone(sample.store.get("ReceiptEpisodeStore:artifact_digest"))


if __name__ == "__main__":
    unittest.main()
