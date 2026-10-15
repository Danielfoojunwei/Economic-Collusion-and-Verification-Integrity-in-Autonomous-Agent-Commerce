"""Independent checks of W13 scripted cost parity and native consequences."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agent_economic_trust.defense_comparison import (
    CheckBudgetExhausted, CheckResult, COSTED_CANDIDATES, POLICIES,
    PricedCheckLedger,
    dispatch_decision, evaluate_policy, ideal_oracle_upper_bound,
    spot_plan, visible_submission,
)
from agent_economic_trust.w10_factorial import frozen_fixtures


ROOT = Path(__file__).resolve().parents[1]


class DefensePolicyTests(unittest.TestCase):
    def test_spot_selection_is_blind_and_costed_policies_match_exact_budget(self) -> None:
        fixtures = frozen_fixtures()
        plan = spot_plan(fixtures)
        self.assertEqual(len(plan), 1)
        self.assertEqual(sum(visible_submission(item).public_task_sha256 in plan
                             for item in fixtures), 2)
        self.assertEqual(sum(item.truth == 1 and
                             visible_submission(item).public_task_sha256 in plan
                             for item in fixtures), 1)
        self.assertEqual(sum(item.truth == 0 and
                             visible_submission(item).public_task_sha256 in plan
                             for item in fixtures), 1)
        # A policy cannot identify a good/bad hidden world from its visible row.
        for left, right in ((fixtures[0], fixtures[1]), (fixtures[2], fixtures[3])):
            self.assertEqual(visible_submission(left), visible_submission(right))
        with self.assertRaisesRegex(ValueError, "paired public-task worlds"):
            spot_plan((fixtures[0], fixtures[0], fixtures[0], fixtures[1]))
        with self.assertRaisesRegex(ValueError, "32 hex bytes"):
            spot_plan(fixtures, seed_hex="bad")

        outcomes = {policy: evaluate_policy(policy) for policy in POLICIES}
        baseline = outcomes["unchecked_baseline"]
        self.assertEqual((baseline["check_calls"], baseline["check_spent_units"]), (0, 0))
        self.assertEqual((baseline["projected_wrongful_payment_count"],
                          baseline["projected_honest_nonpayment_count"]), (2, 0))
        for policy in COSTED_CANDIDATES:
            outcome = outcomes[policy]
            self.assertEqual(outcome["check_cap_units"], 2)
            self.assertEqual((outcome["check_calls"], outcome["check_spent_units"]), (2, 2))
            self.assertEqual(outcome["selected_public_task_sha256"], sorted(plan))
            self.assertEqual((outcome["projected_wrongful_payment_count"],
                              outcome["projected_honest_nonpayment_count"]), (1, 0))
            self.assertEqual(sum(row["check_charged_units"] for row in outcome["rows"]), 2)
            self.assertEqual(sum(row["check_wall_ns"] for row in outcome["rows"]),
                             outcome["check_wall_ns"])
            self.assertTrue(all(row["application_wall_ns"] >= row["check_wall_ns"]
                                for row in outcome["rows"]))
            self.assertEqual(sum(row["oracle_truth_for_posthoc_scoring"] == 1
                                 for row in outcome["rows"]), 2)
        self.assertEqual(outcomes["principal_budget"]["check_owner"], "principal")
        self.assertTrue(all(row["reviewer_role"] == "independent_evaluator"
                            for row in outcomes["independent_assignment"]["rows"]))

    def test_digest_binding_rejects_substitution_without_spending_a_check(self) -> None:
        fixture = frozen_fixtures()[0]
        visible = visible_submission(fixture, submitted_digest="0" * 64)
        self.assertNotEqual(visible.reviewed_artifact_digest, visible.submitted_artifact_digest)

        def forbidden_check() -> CheckResult:
            raise AssertionError("identity mismatch should fail before paid check")

        decision = dispatch_decision(visible, policy="spot_check", selected_for_check=True,
                                     check=forbidden_check)
        self.assertEqual((decision.verdict, decision.reason, decision.check_charged_units),
                         ("REJECT", "REVIEWED_DIGEST_MISMATCH", 0))
        baseline = dispatch_decision(visible, policy="unchecked_baseline", selected_for_check=False,
                                     check=forbidden_check)
        self.assertEqual(baseline.dispatch_intent, "COMPLETE")
        empty = visible_submission(fixture, submitted_digest="")
        empty_decision = dispatch_decision(empty, policy="spot_check",
                                           selected_for_check=True, check=forbidden_check)
        self.assertFalse(empty_decision.digest_bound)
        self.assertEqual(empty_decision.dispatch_intent, "REJECT")

    def test_inconclusive_budget_failure_and_missing_reviewer_fail_closed(self) -> None:
        fixture = frozen_fixtures()[0]
        visible = visible_submission(fixture)
        pending = dispatch_decision(visible, policy="spot_check", selected_for_check=True,
                                    check=lambda: CheckResult("INCONCLUSIVE", "PENDING", 1, 9))
        self.assertEqual((pending.verdict, pending.dispatch_intent), ("ABSTAIN", "HOLD"))

        def exhausted() -> CheckResult:
            raise CheckBudgetExhausted("no units")

        stopped = dispatch_decision(visible, policy="principal_budget", selected_for_check=True,
                                    check=exhausted)
        self.assertEqual((stopped.verdict, stopped.check_charged_units), ("ABSTAIN", 0))
        ineligible = dispatch_decision(visible, policy="independent_assignment", selected_for_check=True,
                                       check=exhausted,
                                       eligible_reviewers=("default_evaluator",))
        self.assertEqual((ineligible.reviewer_role, ineligible.dispatch_intent),
                         ("NONE", "HOLD"))

    def test_priced_check_ledger_charges_once_and_blocks_excess(self) -> None:
        fixture = frozen_fixtures()[0]
        ledger = PricedCheckLedger("principal", cap_units=1)
        result = ledger.check(fixture.case, fixture.artifact)
        self.assertEqual((result.status, result.charged_units, ledger.spent_units),
                         ("PASS", 1, 1))
        with self.assertRaises(CheckBudgetExhausted):
            ledger.check(fixture.case, fixture.artifact)
        self.assertEqual((ledger.calls, ledger.spent_units), (1, 1))

    def test_ideal_truth_control_is_not_a_practical_policy(self) -> None:
        control = ideal_oracle_upper_bound()
        self.assertNotIn(control["label"], POLICIES)
        self.assertFalse(control["check_cost_measured"])
        self.assertEqual([row["verdict"] for row in control["rows"]],
                         ["ACCEPT", "REJECT", "ACCEPT", "REJECT"])
        with self.assertRaisesRegex(ValueError, "unknown candidate policy"):
            evaluate_policy(control["label"])


class DefenseNativeEvidenceTests(unittest.TestCase):
    def test_local_erc_receipts_support_paid_and_unpaid_outcomes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="w13-native-") as directory:
            output = Path(directory) / "run"
            subprocess.run([sys.executable, str(ROOT / "scripts/run_w13_defense_local.py"),
                            "--output", str(output)], cwd=ROOT, check=True,
                           capture_output=True, text=True, timeout=150)
            evidence = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["work_order"], "W13_PREP")
            self.assertEqual(evidence["source"]["commit"],
                             "142e669c1fd318486a4628395b629f033654dd06")
            self.assertEqual(evidence["chain"]["rpc_host"], "127.0.0.1")
            self.assertEqual((evidence["model_behavior_tier"], evidence["payment_tier"]),
                             ("SCRIPTED_SIMULATION", "NATIVE_LOCAL_PROTOCOL"))
            self.assertEqual(evidence["asset"]["real_value"], 0)
            self.assertEqual(set(evidence["branches"]), set(POLICIES))
            for path, digest in evidence["code_sha256"].items():
                self.assertEqual(sha256((ROOT / path).read_bytes()).hexdigest(), digest)

            actors = {role: address.lower() for role, address in evidence["actors"].items()}
            for policy, branch in evidence["branches"].items():
                expected_checks = 0 if policy == "unchecked_baseline" else 2
                self.assertEqual((branch["check_cap_units"], branch["check_spent_units"],
                                  branch["check_calls"]), (2, expected_checks, expected_checks))
                self.assertEqual(branch["native_wrongful_payment_count"],
                                 2 if policy == "unchecked_baseline" else 1)
                self.assertEqual(branch["native_honest_nonpayment_count"], 0)
                self.assertEqual(len(branch["rows"]), 4)
                self.assertEqual(len(branch["transactions"]), 20)
                self.assertEqual(branch["native_transaction_gas_used"],
                                 sum(tx["gas_used"] for tx in branch["transactions"]))
                self.assertGreater(branch["native_transaction_gas_used"], 0)
                self.assertEqual((branch["model_calls"], branch["model_tokens"],
                                  branch["remote_model_spend_usd"]), (0, 0, 0))
                token_delta = branch["native_balance_delta_minor_units"]
                self.assertEqual(sum(token_delta.values()), 0)
                completed = 4 if policy == "unchecked_baseline" else 3
                self.assertEqual(token_delta["client"], -completed * 20_000_000)
                self.assertEqual(token_delta["provider"], completed * 17_000_000)
                self.assertEqual(token_delta["treasury"], completed * 1_000_000)
                fee_role = "outsider" if policy == "independent_assignment" else "evaluator"
                self.assertEqual(token_delta[fee_role], completed * 2_000_000)
                for row in branch["rows"]:
                    terminal = row["final_state"]["job"]
                    selected_role = row["native_evaluator_role"]
                    expected_role = "outsider" if policy == "independent_assignment" else "evaluator"
                    self.assertEqual(selected_role, expected_role)
                    self.assertEqual(terminal["evaluator"].lower(), actors[selected_role])
                    suffix = "complete" if row["dispatch_intent"] == "COMPLETE" else "reject"
                    tx = next(item for item in branch["transactions"] if
                              item["step"] == f"{policy}.{row['fixture_id']}.{suffix}")
                    self.assertEqual(tx["status"], 1)
                    self.assertEqual(tx["raw_transaction"]["from"].lower(), actors[selected_role])
                    self.assertEqual(int(tx["raw_receipt"]["status"], 16), 1)
                    before = row["submitted_state"]["token_state"]["balances_minor_units"]
                    after = row["final_state"]["token_state"]["balances_minor_units"]
                    self.assertEqual(after["escrow"] - before["escrow"], -20_000_000)
                    if suffix == "complete":
                        self.assertEqual(terminal["status"], "Completed")
                        self.assertEqual(after["provider"] - before["provider"], 17_000_000)
                        self.assertEqual(after[selected_role] - before[selected_role], 2_000_000)
                        self.assertEqual(after["treasury"] - before["treasury"], 1_000_000)
                        self.assertIn("PaymentReleased", {log["name"] for log in tx["logs"]})
                    else:
                        self.assertEqual(terminal["status"], "Rejected")
                        self.assertEqual(after["client"] - before["client"], 20_000_000)
                        self.assertIn("Refunded", {log["name"] for log in tx["logs"]})
                    self.assertEqual(row["native_wrongful_payment"],
                                     row["oracle_truth_for_posthoc_scoring"] == 0 and suffix == "complete")
                    self.assertEqual(row["native_honest_nonpayment"],
                                     row["oracle_truth_for_posthoc_scoring"] == 1 and suffix == "reject")


if __name__ == "__main__":
    unittest.main()
