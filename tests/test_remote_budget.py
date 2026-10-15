"""Project-wide remote-spend guard and its fail-closed failure cases."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_economic_trust.remote_budget import (  # noqa: E402
    BudgetExceeded,
    BudgetIntegrityError,
    BudgetLedger,
    BudgetMissingError,
    BudgetStateError,
    create_ledger,
    read_ledger,
)


class RemoteBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "shared" / "remote_budget.jsonl"

    def test_explicit_creation_opening_spend_and_no_reset(self) -> None:
        with self.assertRaises(BudgetMissingError):
            read_ledger(self.path)
        with self.assertRaises(BudgetExceeded):
            create_ledger(self.path, "20.000000000001", "0")
        with self.assertRaises(BudgetExceeded):
            create_ledger(self.path, "50", "0")
        ledger = create_ledger(self.path, "20.00", "2.25")
        self.assertEqual(ledger.snapshot()["cap_usd"], "20")
        self.assertEqual(ledger.read()["settled_spent_usd"], "2.25")
        self.assertEqual(ledger.snapshot()["available_usd"], "17.75")
        with self.assertRaises(FileExistsError):
            create_ledger(self.path, "20", "0")
        self.assertEqual(read_ledger(self.path)["cap_usd"], "20")

    def test_authorized_cap_raise_preserves_old_entries_and_applies_prospectively(self) -> None:
        ledger = create_ledger(self.path, "20", "2.25")
        ledger.reserve("old-run", "10", "20", {})
        ledger.settle("old-run", "3", "provider-usage/old-run")
        original = self.path.read_bytes()
        raised = ledger.raise_cap("50", "docs/BUDGET_AUTHORIZATION_2026-10-15.md")
        self.assertTrue(self.path.read_bytes().startswith(original))
        self.assertEqual(raised["cap_usd"], "50")
        self.assertEqual(raised["settled_spent_usd"], "5.25")
        self.assertEqual(raised["available_usd"], "44.75")
        self.assertEqual(raised["seq"], 3)
        with self.assertRaises(BudgetStateError):
            ledger.reserve("new-run", "1", "20", {})
        with self.assertRaises(BudgetExceeded):
            ledger.raise_cap("50.01", "docs/BUDGET_AUTHORIZATION_2026-10-15.md")
        with self.assertRaises(BudgetExceeded):
            ledger.reserve("new-run", "44.751", "50", {})
        self.assertEqual(ledger.reserve("new-run", "44.75", "50", {})["available_usd"], "0")
        self.assertEqual(read_ledger(self.path)["cap_usd"], "50")

    def test_cap_raise_requires_reference_and_preserves_unknown_charge_block(self) -> None:
        ledger = create_ledger(self.path, "20", "0")
        ledger.reserve("uncertain", "2", "20", {})
        ledger.mark_unknown("uncertain", "provider-timeout")
        with self.assertRaises(ValueError):
            ledger.raise_cap("50", "")
        raised = ledger.raise_cap("50", "owner-message-2026-10-15")
        self.assertTrue(raised["blocked"])
        self.assertEqual(raised["unknown_run_ids"], ["uncertain"])
        with self.assertRaises(BudgetStateError):
            ledger.reserve("later", "1", "50", {})

    def test_reservation_is_atomic_and_counts_against_cap(self) -> None:
        ledger = create_ledger(self.path, "20", "2")
        snapshot = ledger.reserve("run-1", Decimal("10.125"), "20", {"model": "test-model"})
        self.assertEqual(snapshot["reserved_usd"], "10.125")
        self.assertEqual(snapshot["available_usd"], "7.875")
        self.assertEqual(snapshot["runs"]["run-1"]["metadata"], {"model": "test-model"})
        with self.assertRaises(BudgetStateError):
            ledger.reserve("run-1", "1", "20", {})
        with self.assertRaises(BudgetExceeded):
            ledger.reserve("run-2", "7.876", "20", {})
        with self.assertRaises(BudgetStateError):
            ledger.reserve("run-2", "1", "21", {})
        self.assertEqual(ledger.snapshot()["seq"], 1)
        self.assertEqual(ledger.reserve("run-2", "7.875", "20", {})["available_usd"], "0")

    def test_settlement_reconciles_estimate_and_is_idempotent(self) -> None:
        ledger = create_ledger(self.path, "20", "0")
        ledger.reserve("run-1", "9", "20", {})
        settled = ledger.settle("run-1", "3.475", "provider-usage/run-1")
        self.assertEqual(settled["settled_spent_usd"], "3.475")
        self.assertEqual(settled["reserved_usd"], "0")
        self.assertEqual(settled["available_usd"], "16.525")
        self.assertEqual(ledger.settle("run-1", "3.475", "provider-usage/run-1")["seq"], 2)
        with self.assertRaises(BudgetStateError):
            ledger.settle("run-1", "4", "provider-usage/run-1")
        with self.assertRaises(BudgetStateError):
            ledger.settle("missing", "0", "provider-usage/missing")

    def test_unknown_charge_blocks_new_calls_until_reconciled(self) -> None:
        ledger = create_ledger(self.path, "20", "0")
        ledger.reserve("run-1", "5", "20", {})
        unknown = ledger.mark_unknown("run-1", "provider-timeout")
        self.assertTrue(unknown["blocked"])
        self.assertEqual(unknown["unknown_run_ids"], ["run-1"])
        self.assertEqual(ledger.mark_unknown("run-1", "provider-timeout")["seq"], 2)
        with self.assertRaises(BudgetStateError):
            ledger.reserve("run-2", "1", "20", {})
        with self.assertRaises(BudgetStateError):
            ledger.mark_unknown("run-1", "different-reason")
        ledger.settle("run-1", "4", "provider-usage/run-1")
        self.assertEqual(ledger.reserve("run-2", "1", "20", {})["unknown_run_ids"], [])

    def test_contingent_transition_retains_full_hold_and_allows_only_remaining_cap(self) -> None:
        ledger = create_ledger(self.path, "20", "2")
        ledger.reserve("uncertain", "6", "20", {})
        before = ledger.mark_unknown("uncertain", "provider_request_failed")
        self.assertTrue(before["blocked"])
        with self.assertRaises(BudgetStateError):
            ledger.reserve("later", "1", "20", {})

        evidence = "sha256:" + "a" * 64
        after = ledger.mark_contingent("uncertain", evidence)
        for field in ("cap_usd", "settled_spent_usd", "reserved_usd", "committed_usd", "available_usd"):
            self.assertEqual(after[field], before[field], field)
        self.assertFalse(after["blocked"])
        self.assertEqual(after["unknown_run_ids"], [])
        self.assertEqual(after["contingent_run_ids"], ["uncertain"])
        self.assertEqual(after["runs"]["uncertain"], {
            "status": "CONTINGENT", "reserved_usd": "6", "metadata": {},
            "evidence_ref": evidence, "contingent_evidence_ref": evidence,
            "prior_unknown_reason": "provider_request_failed",
        })
        self.assertNotIn("actual_usd", after["runs"]["uncertain"])
        self.assertEqual(after["seq"], before["seq"] + 1)
        self.assertEqual(read_ledger(self.path), after)
        self.assertEqual(ledger.reserve("later", "12", "20", {})["available_usd"], "0")
        with self.assertRaises(BudgetExceeded):
            ledger.reserve("over", "0.01", "20", {})

    def test_contingent_transition_rejects_bad_evidence_and_wrong_states(self) -> None:
        ledger = create_ledger(self.path, "20", "0")
        evidence = "sha256:" + "b" * 64
        with self.assertRaises(BudgetStateError):
            ledger.mark_contingent("absent", evidence)
        ledger.reserve("run", "6", "20", {})
        with self.assertRaises(BudgetStateError):
            ledger.mark_contingent("run", evidence)
        ledger.mark_unknown("run", "provider_timeout")
        for invalid in ("", "b" * 64, "sha256:" + "B" * 64,
                        "sha256:" + "b" * 63, "sha256:" + "b" * 65,
                        "sha256:" + "b" * 63 + "x", "Bearer hidden"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                ledger.mark_contingent("run", invalid)
        self.assertEqual(ledger.snapshot()["seq"], 2)
        ledger.mark_contingent("run", evidence)
        with self.assertRaises(BudgetStateError):
            ledger.mark_contingent("run", evidence)
        self.assertEqual(ledger.snapshot()["seq"], 3)

    def test_contingent_evidence_can_be_discredited_without_releasing_hold(self) -> None:
        ledger = create_ledger(self.path, "20", "0")
        ledger.reserve("run", "6", "20", {})
        ledger.mark_unknown("run", "provider_timeout")
        contingent = ledger.mark_contingent("run", "sha256:" + "c" * 64)
        reblocked = ledger.mark_unknown("run", "evidence_discredited")
        self.assertTrue(reblocked["blocked"])
        self.assertEqual(reblocked["unknown_run_ids"], ["run"])
        self.assertEqual(reblocked["contingent_run_ids"], [])
        self.assertEqual(reblocked["reserved_usd"], contingent["reserved_usd"])
        self.assertEqual(reblocked["committed_usd"], contingent["committed_usd"])
        self.assertEqual(reblocked["available_usd"], contingent["available_usd"])
        self.assertEqual(reblocked["runs"]["run"]["unknown_reason"], "evidence_discredited")
        self.assertEqual(reblocked["runs"]["run"]["contingent_evidence_ref"], "sha256:" + "c" * 64)
        self.assertNotIn("evidence_ref", reblocked["runs"]["run"])
        with self.assertRaises(BudgetStateError):
            ledger.reserve("later", "1", "20", {})
        with self.assertRaises(BudgetStateError):
            ledger.mark_contingent("run", "sha256:" + "d" * 64)
        self.assertEqual(read_ledger(self.path), reblocked)

    def test_contingent_settlement_requires_final_attributable_billing_reference(self) -> None:
        ledger = create_ledger(self.path, "20", "13")
        ledger.reserve("run", "6", "20", {})
        ledger.mark_unknown("run", "provider_timeout")
        ledger.mark_contingent("run", "sha256:" + "a" * 64)
        for evidence in ("provider-usage/run", "sha256:" + "b" * 64,
                         "provider-billing:sha256:" + "B" * 64):
            with self.subTest(evidence=evidence), self.assertRaises(BudgetStateError):
                ledger.settle("run", "8", evidence)
        self.assertEqual(ledger.snapshot()["seq"], 3)
        final = "provider-billing:sha256:" + "b" * 64
        settled = ledger.settle("run", "8", final)
        self.assertEqual(settled["settled_spent_usd"], "21")
        self.assertEqual(settled["reserved_usd"], "0")
        self.assertEqual(settled["available_usd"], "-1")
        self.assertTrue(settled["over_cap"])
        self.assertEqual(settled["contingent_run_ids"], [])
        self.assertEqual(settled["runs"]["run"]["actual_usd"], "8")
        self.assertEqual(settled["runs"]["run"]["evidence_ref"], final)
        self.assertEqual(ledger.settle("run", "8", final)["seq"], 4)
        with self.assertRaises(BudgetExceeded):
            ledger.reserve("later", "0.01", "20", {})

    def test_reblocked_contingent_run_still_requires_final_billing_to_settle(self) -> None:
        ledger = create_ledger(self.path, "20", "0")
        ledger.reserve("run", "6", "20", {})
        ledger.mark_unknown("run", "provider_timeout")
        ledger.mark_contingent("run", "sha256:" + "a" * 64)
        ledger.mark_unknown("run", "evidence_discredited")
        with self.assertRaises(BudgetStateError):
            ledger.settle("run", "0", "provider-usage/run")
        settled = ledger.settle("run", "0", "provider-billing:sha256:" + "b" * 64)
        self.assertFalse(settled["blocked"])
        self.assertEqual(settled["available_usd"], "20")

    def test_actual_charge_above_estimate_is_recorded_and_blocks_overspend(self) -> None:
        ledger = create_ledger(self.path, "20", "18")
        ledger.reserve("run-1", "2", "20", {})
        snapshot = ledger.settle("run-1", "3", "provider-usage/run-1")
        self.assertTrue(snapshot["over_cap"])
        self.assertEqual(snapshot["available_usd"], "-1")
        with self.assertRaises(BudgetExceeded):
            ledger.reserve("run-2", "0.01", "20", {})

    def test_corrupt_record_or_truncated_tail_fails_closed(self) -> None:
        ledger = create_ledger(self.path, "20", "0")
        ledger.reserve("run-1", "1", "20", {})
        original = self.path.read_bytes()
        self.path.write_bytes(original.replace(b'"amount_usd":"1"', b'"amount_usd":"9"'))
        with self.assertRaises(BudgetIntegrityError):
            ledger.snapshot()
        with self.assertRaises(BudgetIntegrityError):
            ledger.reserve("run-2", "1", "20", {})
        self.path.write_bytes(original.split(b"\n", 1)[0] + b"\n")
        with self.assertRaises(BudgetIntegrityError):
            ledger.snapshot()
        self.path.write_bytes(original)
        anchor = self.path.with_name(self.path.name + ".anchor")
        anchor.unlink()
        with self.assertRaises(BudgetMissingError):
            ledger.reserve("run-2", "1", "20", {})

    def test_invalid_amounts_and_sensitive_metadata_never_enter_ledger(self) -> None:
        ledger = create_ledger(self.path, "20", "0")
        for amount in ("NaN", "Infinity", "-1", 0, 0.5, "0.0000000000001"):
            with self.subTest(amount=amount), self.assertRaises((TypeError, ValueError)):
                ledger.reserve("run-1", amount, "20", {})
        with self.assertRaises(ValueError):
            ledger.reserve("run-1", "1", "20", {"api_key": "sk-secretmaterial"})
        with self.assertRaises(ValueError):
            ledger.reserve("run-1", "1", "20", {"note": "Bearer secretmaterial"})
        self.assertEqual(ledger.snapshot()["seq"], 0)
        ledger.reserve("run-1", "1", "20", {})
        unknown = ledger.mark_unknown("run-1", "api_key=secretmaterial")
        self.assertEqual(unknown["runs"]["run-1"]["unknown_reason"], "unspecified_or_sensitive_error")
        self.assertTrue(unknown["blocked"])
        self.assertNotIn(b"secretmaterial", self.path.read_bytes())

    def test_many_concurrent_reservations_cannot_exceed_cap(self) -> None:
        create_ledger(self.path, "5", "0")

        def reserve(index: int) -> bool:
            try:
                BudgetLedger(self.path).reserve(f"run-{index}", "1", "5", {})
                return True
            except BudgetExceeded:
                return False

        with ThreadPoolExecutor(max_workers=12) as executor:
            accepted = list(executor.map(reserve, range(24)))
        self.assertEqual(sum(accepted), 5)
        snapshot = read_ledger(self.path)
        self.assertEqual(snapshot["reserved_usd"], "5")
        self.assertEqual(snapshot["seq"], 5)
        self.assertEqual(len(snapshot["runs"]), 5)


if __name__ == "__main__":
    unittest.main()
