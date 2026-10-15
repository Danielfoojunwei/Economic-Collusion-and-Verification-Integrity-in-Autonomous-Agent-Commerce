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
        ledger = create_ledger(self.path, "20.00", "2.25")
        self.assertEqual(ledger.snapshot()["cap_usd"], "20")
        self.assertEqual(ledger.read()["settled_spent_usd"], "2.25")
        self.assertEqual(ledger.snapshot()["available_usd"], "17.75")
        with self.assertRaises(FileExistsError):
            create_ledger(self.path, "20", "0")
        self.assertEqual(read_ledger(self.path)["cap_usd"], "20")

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
