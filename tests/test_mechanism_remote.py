"""Fail-closed prospectively assigned paid-call guards, with no paid requests."""

from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent_economic_trust.mechanism_plan import make_schedule
from agent_economic_trust import mechanism_remote as remote
from agent_economic_trust.mechanism_task import EscrowObligation


class _Ledger:
    snapshot_value: dict = {}
    last: "_Ledger | None" = None

    def __init__(self, path: Path):
        self.path = path
        self.reserved: list[tuple] = []
        self.unknown: list[tuple] = []
        _Ledger.last = self

    def snapshot(self) -> dict:
        return self.snapshot_value

    def reserve(self, *args, **kwargs) -> dict:
        self.reserved.append((args, kwargs))
        return self.snapshot_value

    def mark_unknown(self, *args) -> dict:
        self.unknown.append(args)
        return self.snapshot_value


class _FakeNative:
    def __init__(self, row, directory, **kwargs):
        self.directory = directory

    def __enter__(self):
        self.directory.mkdir(parents=True)
        return self

    def __exit__(self, exc_type, exc, tb):
        (self.directory / "partial_evidence.json").write_text(
            json.dumps({"complete_payment_claim": False}) + "\n")

    def open_job(self):
        return object()

    def submit_claim(self, submission):
        raise AssertionError("no task tool call expected")


class MechanismRemoteGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory(prefix="mechanism-remote-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.plan = remote.MechanismPilotPlan(runs_dir=self.directory / "runs")
        self.rows = make_schedule("a" * 64)
        self.frozen = {
            "execution_order": [row.episode_id for row in self.rows],
            "worst_case_reserve_usd_per_episode": "4",
            "source_sha256": {},
        }
        self.assignment_sha = "b" * 64
        _Ledger.snapshot_value = {
            "blocked": False, "cap_usd": "20", "unknown_run_ids": [],
            "available_usd": "20", "last_hash": "c" * 64, "runs": {},
        }

    def _preflight(self, available: str = "20") -> dict:
        _Ledger.snapshot_value = _Ledger.snapshot_value | {"available_usd": available}
        with (patch.object(remote.MechanismPilotPlan, "validate",
                           return_value=(self.frozen, self.assignment_sha, self.rows)),
              patch.object(remote, "BudgetLedger", _Ledger),
              patch.object(remote, "_freeze_verify"),
              patch.object(remote, "load_assignment",
                           return_value=(self.frozen, self.assignment_sha, self.rows)),
              patch.object(remote, "pricing_snapshot", return_value={"rate": "4"}),
              patch.object(remote, "reserve_worst_case", return_value=Decimal("4"))):
            return remote.preflight(self.plan)

    def test_full_four_cell_headroom_and_duplicate_run_stop_without_model(self) -> None:
        with self.assertRaisesRegex(remote.RemoteBoundaryError, "full remaining"):
            self._preflight("15.99")
        ready = self._preflight("16")
        self.assertEqual(ready["next_reservation_usd"], "4")
        _Ledger.snapshot_value["runs"] = {
            remote._run_id(self.assignment_sha, self.rows[0].episode_id):
                {"status": "UNKNOWN"}}
        with self.assertRaisesRegex(remote.RemoteBoundaryError, "run ID"):
            self._preflight()

    def test_blocked_ledger_and_source_drift_never_reach_paid_boundary(self) -> None:
        _Ledger.snapshot_value["blocked"] = True
        with patch.object(remote.MechanismPilotPlan, "validate",
                          return_value=(self.frozen, self.assignment_sha, self.rows)), \
             patch.object(remote, "BudgetLedger", _Ledger), \
             patch.object(remote, "inspect_eval") as paid:
            with self.assertRaisesRegex(remote.RemoteBoundaryError, "blocked"):
                remote.execute_one(self.plan)
            paid.assert_not_called()
        with patch.object(remote, "_freeze_verify", side_effect=ValueError("source drift")):
            with self.assertRaisesRegex(ValueError, "source drift"):
                remote.MechanismPilotPlan().validate()

    def test_price_refresh_rejects_later_higher_full_block_cost(self) -> None:
        prices = iter(({"reserve": "3"}, {"reserve": "5"}))
        with patch.object(remote, "_freeze_verify"), \
             patch.object(remote, "load_assignment",
                          return_value=(self.frozen, self.assignment_sha, self.rows)), \
             patch.object(remote, "BudgetLedger", _Ledger), \
             patch.object(remote, "pricing_snapshot", side_effect=lambda _: next(prices)), \
             patch.object(remote, "reserve_worst_case",
                          side_effect=lambda rates, *_: Decimal(rates["reserve"])):
            _Ledger.snapshot_value["available_usd"] = "19"
            first = remote._fresh_budget_boundary(
                self.plan, self.frozen, self.assignment_sha, self.rows[0], 0)
            self.assertEqual(first[1], Decimal("4"))
            with self.assertRaisesRegex(remote.RemoteBoundaryError, "full remaining"):
                remote._fresh_budget_boundary(
                    self.plan, self.frozen, self.assignment_sha, self.rows[0], 0)

    def test_post_request_exception_keeps_partial_eval_and_blocks_ledger(self) -> None:
        row = self.rows[0]
        preview = {
            "next_episode_id": row.episode_id, "next_index": 0,
            "remaining_episodes": 4,
        }

        def interrupted_eval(*args, **kwargs):
            work = Path(kwargs["log_dir"])
            (work / "partial.eval").write_bytes(b"saved incomplete native Inspect archive\n")
            raise RuntimeError("provider_interrupted")

        with patch.object(remote, "preflight", return_value=preview), \
             patch.object(remote, "_execution_enabled"), \
             patch.object(remote.MechanismPilotPlan, "validate",
                          return_value=(self.frozen, self.assignment_sha, self.rows)), \
             patch.object(remote, "BudgetLedger", _Ledger), \
             patch.object(remote, "MechanismNative", _FakeNative), \
             patch.object(remote, "build_mechanism_task", return_value=object()), \
             patch.object(remote, "account_usage_usd", return_value=Decimal("0")), \
             patch.object(remote, "get_model", return_value=object()), \
             patch.object(remote, "guard_model_api",
                          return_value={"attempted": 1, "max_input_bytes_seen": 100}), \
             patch.object(remote, "guard_high_reasoning"), \
             patch.object(remote, "_fresh_budget_boundary",
                          return_value=({}, Decimal("4"), _Ledger.snapshot_value)), \
             patch.object(remote, "inspect_eval", side_effect=interrupted_eval):
            with self.assertRaisesRegex(RuntimeError, "provider_interrupted"):
                remote.execute_one(self.plan)
        directory = self.plan.runs_dir / "episodes" / row.episode_id
        stop = json.loads((directory / "STOPPED.json").read_bytes())
        self.assertEqual(stop["budget_state"], "UNKNOWN")
        self.assertEqual(stop["model_calls_attempted"], 1)
        self.assertIs(stop["complete_payment_claim"], False)
        self.assertTrue(stop["partial_inspect_archives"])
        self.assertTrue((directory / "inspect.eval").is_file())
        self.assertTrue((directory / "native" / "partial_evidence.json").is_file())
        self.assertTrue(_Ledger.last.unknown)

    def test_account_counter_failure_precedes_reservation_and_paid_call(self) -> None:
        row = self.rows[0]
        preview = {"next_episode_id": row.episode_id, "next_index": 0,
                   "remaining_episodes": 4}
        with patch.object(remote, "preflight", return_value=preview), \
             patch.object(remote, "_execution_enabled"), \
             patch.object(remote.MechanismPilotPlan, "validate",
                          return_value=(self.frozen, self.assignment_sha, self.rows)), \
             patch.object(remote, "BudgetLedger", _Ledger), \
             patch.object(remote, "MechanismNative", _FakeNative), \
             patch.object(remote, "build_mechanism_task", return_value=object()), \
             patch.object(remote, "account_usage_usd",
                          side_effect=remote.RemoteBoundaryError("account counter unavailable")), \
             patch.object(remote, "inspect_eval") as paid:
            with self.assertRaisesRegex(remote.RemoteBoundaryError, "account counter"):
                remote.execute_one(self.plan)
            paid.assert_not_called()
        stop = json.loads((self.plan.runs_dir / "episodes" / row.episode_id
                           / "STOPPED.json").read_bytes())
        self.assertEqual(stop["budget_state"], "UNRESERVED")
        self.assertFalse(_Ledger.last.reserved)
        self.assertFalse(_Ledger.last.unknown)

    def test_auditor_proof_must_match_provider_funded_escrow(self) -> None:
        obligation = EscrowObligation(
            chain_id=31337, core_address="0x" + "1" * 40, job_id=1,
            provider_address="0x" + "2" * 40,
            auditor_address="0x" + "3" * 40,
            token_address="0x" + "4" * 40, funding_deadline=123456,
        )
        bonus = {
            "status": "FUNDED", "proposal_id": "assigned-proposal",
            "amount_minor": 5_000_000, "escrow_address": "0x" + "5" * 40,
            "funding_tx_hash": "0x" + "6" * 64,
            "funding_receipt_sha256": "7" * 64,
        }
        native = SimpleNamespace(obligation=obligation, bonus=bonus)
        proof = {
            "chain_id": obligation.chain_id,
            "core_address": obligation.core_address, "job_id": obligation.job_id,
            "provider_address": obligation.provider_address,
            "auditor_address": obligation.auditor_address,
            "token_address": obligation.token_address,
            "condition": remote.BONUS_CONDITION,
            "currency": remote.BONUS_CURRENCY,
            "status": "VERIFIED_NATIVE_LOCAL",
            "execution_tier": "NATIVE_LOCAL_PROTOCOL",
            "proposal_id": bonus["proposal_id"],
            "amount_minor": bonus["amount_minor"],
            "escrow_address": bonus["escrow_address"],
            "funding_tx_hash": bonus["funding_tx_hash"],
            "receipt_sha256": bonus["funding_receipt_sha256"],
        }
        audit = {"trusted_bonus_proof_seen_before_verdict": True,
                 "trusted_bonus_status": "VERIFIED_NATIVE_LOCAL",
                 "auditor_verified_bonus": proof}
        remote._require_auditor_native_bonus_proof(audit, native)
        audit["auditor_verified_bonus"] = proof | {"funding_tx_hash": "0x" + "8" * 64}
        with self.assertRaisesRegex(remote.RemoteBoundaryError, "differs"):
            remote._require_auditor_native_bonus_proof(audit, native)
        audit["auditor_verified_bonus"] = proof
        audit["trusted_bonus_proof_seen_before_verdict"] = False
        with self.assertRaisesRegex(remote.RemoteBoundaryError, "did not reach"):
            remote._require_auditor_native_bonus_proof(audit, native)


if __name__ == "__main__":
    unittest.main()
