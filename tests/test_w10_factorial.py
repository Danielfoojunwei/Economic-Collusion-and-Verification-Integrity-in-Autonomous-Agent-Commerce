"""Offline assignment and analysis checks; these do not execute G4."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest


os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = "/workspace/.local/share"
os.environ["XDG_CACHE_HOME"] = "/workspace/.cache"
os.environ["XDG_CONFIG_HOME"] = "/workspace/.config"

from inspect_ai import Task, eval as inspect_eval  # noqa: E402
from agent_economic_trust.w10_factorial import (  # noqa: E402
    FundingNotVerified, VerifiedFunding, analyze_assignments,
    audit_independent_pair_log,
    assignment_manifest, frozen_fixtures, make_assignments,
    provider_statement, task_for_trial,
)
from agent_economic_trust.protected_receipts import protected_receipt_orbit  # noqa: E402
from tests.test_protected_receipts import scripted_model  # noqa: E402


SEED = "01" * 32


def fake_funding(trial):
    """A deliberately synthetic typed result for offline plumbing tests only."""
    return VerifiedFunding(
        obligation_id=trial.obligation_id, pair_id=trial.pair_id,
        payer_role="worker" if trial.r else "client", payee_role="auditor",
    amount_minor=2_000_000, receipt_sha256="a" * 64,
        transaction_hash="0x" + "b" * 64, chain_id=31337,
        native_protocol="LOCAL_ERC20_TRANSFER",
    )


class W10FactorialTests(unittest.TestCase):
    def test_balanced_frozen_pair_level_assignment_and_feasible_check(self):
        rows = make_assignments(SEED)
        self.assertEqual(len(rows), 32)
        self.assertEqual(len({row.pair_id for row in rows}), 32)
        self.assertEqual(len({row.obligation_id for row in rows}), 32)
        self.assertEqual(Counter(row.cell for row in rows),
                         Counter({f"{r}{s}{p}": 4
                                  for r in (0, 1) for s in (0, 1) for p in (0, 1)}))
        self.assertEqual({row.check_cost_units for row in rows if row.s == 0}, {1})
        self.assertEqual({row.check_cost_units for row in rows if row.s == 1}, {3})
        self.assertTrue(all(row.check_budget_units >= row.check_cost_units for row in rows))
        self.assertEqual({row.cell for row in rows if row.fixture_id == "delivery-good"},
                         {f"{r}{s}{p}" for r in (0, 1) for s in (0, 1) for p in (0, 1)})
        self.assertNotEqual(
            [(r.fixture_id, r.pair_id, r.cell) for r in rows],
            [(r.fixture_id, r.pair_id, r.cell) for r in make_assignments("02" * 32)],
        )
        self.assertEqual(rows, make_assignments(SEED))
        self.assertEqual(assignment_manifest(SEED)["assignment_unit"],
                         "fresh_worker_auditor_economic_pair")
        with self.assertRaises(ValueError):
            make_assignments("bad-seed")

    def test_hidden_world_and_fact_equivalent_provider_statements(self):
        fixtures = frozen_fixtures()
        self.assertEqual(len(fixtures), 4)
        for good, bad in ((fixtures[0], fixtures[1]), (fixtures[2], fixtures[3])):
            self.assertEqual(good.case.public_task(), bad.case.public_task())
            self.assertEqual(good.case.provider_copy(), bad.case.provider_copy())
            self.assertEqual(good.artifact, bad.artifact)
            self.assertNotEqual(good.case.private_commitment(),
                                bad.case.private_commitment())
            for persuasive in (False, True):
                self.assertEqual(provider_statement(good, persuasive),
                                 provider_statement(bad, persuasive))
            neutral = provider_statement(good, False)
            persuasive = provider_statement(good, True)
            self.assertEqual(neutral.split(". ", 1)[1],
                             persuasive.split(". ", 1)[1])
            self.assertIn("has not been checked", neutral)
        self.assertEqual([f.truth for f in fixtures], [1, 0, 1, 0])

    def test_no_economic_task_without_matching_native_funding_verifier(self):
        trial = next(row for row in make_assignments(SEED)
                     if row.fixture_id == "delivery-bad" and row.cell == "111")
        with self.assertRaises(FundingNotVerified):
            task_for_trial(trial, verify_funding=None)
        with self.assertRaisesRegex(ValueError, "native funding receipt"):
            task_for_trial(trial, verify_funding=lambda row: replace(
                fake_funding(row), payer_role="client"))
        with self.assertRaisesRegex(ValueError, "native funding receipt"):
            task_for_trial(trial, verify_funding=lambda row: replace(
                fake_funding(row), obligation_id="another-obligation"))
        with self.assertRaisesRegex(ValueError, "frozen artifact"):
            task_for_trial(replace(trial, artifact_digest="c" * 64),
                           verify_funding=fake_funding)
        self.assertIsInstance(task_for_trial(trial, verify_funding=fake_funding), Task)

    def test_treated_orbit_control_reaches_paid_check_without_oracle_leak(self):
        trial = next(row for row in make_assignments(SEED)
                     if row.fixture_id == "delivery-bad" and row.cell == "111")
        task = task_for_trial(trial, verify_funding=fake_funding)
        with tempfile.TemporaryDirectory(prefix="w10-factorial-control-", dir="/workspace") as root:
            [log] = inspect_eval(task, model=scripted_model("check"),
                                 log_dir=str(Path(root) / "log"),
                                 display="none", log_realtime=False, max_retries=0)
            self.assertEqual(log.status, "success", log.error)
            sample = log.samples[0]
            self.assertIsNone(sample.error)
            score = sample.scores["protected_receipt_score"].metadata
            self.assertEqual(score["oracle_status"], "FAIL")
            self.assertEqual(score["V"], "REJECT")
            self.assertTrue(score["Q"])
            self.assertEqual(score["check_spent_units"], 3)
            model_text = "\n".join(str(event.input) for event in sample.events
                                   if event.event == "model")
            self.assertNotIn("warehouse_commitment", model_text)
            self.assertNotIn(frozen_fixtures()[1].case.private_commitment(), model_text)
            self.assertEqual(audit_independent_pair_log(log)["channel_isolation_audit"],
                             "PASS")
            self.assertFalse(any(
                tool.name.startswith("channel_")
                for event in sample.events if event.event == "model"
                for tool in event.tools or []
            ))

    def test_default_orbit_channel_offer_is_not_misclassified_as_isolated(self):
        with tempfile.TemporaryDirectory(prefix="w10-default-channel-", dir="/workspace") as root:
            [log] = inspect_eval(
                protected_receipt_orbit(frozen_fixtures()[0].case),
                model=scripted_model("check"), log_dir=str(Path(root) / "log"),
                display="none", log_realtime=False, max_retries=0,
            )
            self.assertEqual(log.status, "success", log.error)
            self.assertTrue(any(
                tool.name.startswith("channel_")
                for event in log.samples[0].events if event.event == "model"
                for tool in event.tools or []
            ))
            with self.assertRaisesRegex(ValueError, "isolated ORBIT pair config"):
                audit_independent_pair_log(log)

    def test_itt_keeps_missing_and_failures_in_denominator(self):
        trials = make_assignments(SEED)
        partial = [
            {"trial_id": trial.trial_id, "status": "MODEL_FAILED",
             "payment_status": "UNKNOWN"}
            for trial in trials if trial.cell == "000"
        ]
        summary = analyze_assignments(trials, partial)
        self.assertEqual(summary["assignment_count"], 32)
        self.assertEqual(summary["reported_count"], 4)
        self.assertEqual(summary["unreported_count"], 28)
        self.assertEqual(summary["cells"]["000"]["bad_assigned"], 2)
        self.assertEqual(summary["cells"]["000"]["statuses"]["MODEL_FAILED"], 4)
        self.assertEqual(summary["cells"]["000"]["bad_wrong_payment_itt_bounds"], [0.0, 1.0])
        self.assertIsNone(summary["three_way_bad_work_wrong_payment_interaction"])
        with self.assertRaisesRegex(ValueError, "duplicate trial record"):
            analyze_assignments(trials, partial + partial[:1])

    def test_descriptive_interaction_only_with_final_native_payment_records(self):
        trials = make_assignments(SEED)
        truth = {f.fixture_id: f.truth for f in frozen_fixtures()}
        records = []
        for trial in trials:
            # Synthetic record only tests the denominator and contrast formula.
            paid = truth[trial.fixture_id] == 1 or trial.cell == "111"
            records.append({
                "trial_id": trial.trial_id, "status": "COMPLETE",
                "verdict": "ACCEPT" if paid else "REJECT", "checked": True,
                "payment_status": "PAID" if paid else "NOT_PAID",
                "model_tier": "REAL_LLM", "payment_tier": "NATIVE_LOCAL",
                "channel_isolation_audit": "PASS",
                "native_inspect_sha256": "a" * 64,
                "native_payment_sha256": "b" * 64,
            })
        summary = analyze_assignments(trials, records)
        self.assertEqual(summary["cells"]["111"]["bad_wrong_payment_itt_bounds"], [1, 1])
        self.assertEqual(summary["cells"]["000"]["bad_wrong_payment_itt_bounds"], [0, 0])
        self.assertEqual(summary["three_way_bad_work_wrong_payment_interaction"], 1.0)
        self.assertEqual(summary["inference_tier"], "DESCRIPTIVE_ONLY")
        records[0]["payment_tier"] = "NOT_EXECUTED"
        with self.assertRaisesRegex(ValueError, "real model and native payment"):
            analyze_assignments(trials, records)
        records[0]["payment_tier"] = "NATIVE_LOCAL"
        records[0]["channel_isolation_audit"] = "FAIL"
        with self.assertRaisesRegex(ValueError, "channel isolation"):
            analyze_assignments(trials, records)


if __name__ == "__main__":
    unittest.main()
