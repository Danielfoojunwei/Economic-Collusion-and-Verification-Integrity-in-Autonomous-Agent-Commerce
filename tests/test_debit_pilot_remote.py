"""Pilot-003 paid boundary tests; no model requests or native chain launches."""

from __future__ import annotations

from decimal import Decimal
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from inspect_ai.model import ChatMessageUser, GenerateConfig

from agent_economic_trust.debit_pilot_plan import case_for_episode, make_schedule
from agent_economic_trust import debit_pilot_remote as remote
from agent_economic_trust.mechanism_task import EscrowObligation, build_mechanism_task


class _Ledger:
    snapshot_value: dict = {}
    last: "_Ledger | None" = None

    def __init__(self, path: Path):
        self.reserved: list = []
        self.unknown: list = []
        _Ledger.last = self

    def snapshot(self) -> dict:
        return self.snapshot_value

    def reserve(self, *args, **kwargs) -> dict:
        self.reserved.append((args, kwargs))
        return self.snapshot_value

    def mark_unknown(self, *args) -> dict:
        self.unknown.append(args)
        return self.snapshot_value


class _Native:
    def __init__(self, row, directory, **kwargs):
        self.directory = directory
        self.submission = None

    def __enter__(self):
        self.directory.mkdir(parents=True)
        return self

    def __exit__(self, *_):
        (self.directory / "partial_evidence.json").write_text(
            json.dumps({"complete_payment_claim": False}) + "\n")

    def open_job(self):
        return object()

    def submit_claim(self, *_):
        raise AssertionError("scripted task was never entered")

    def charge_check(self, *_):
        raise AssertionError("scripted task was never entered")


class DebitPilotRemoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory(prefix="debit-pilot-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = remote.DebitPilotPlan(runs_dir=self.root / "runs")
        self.rows = make_schedule("a" * 64)
        self.frozen = {
            "execution_order": [row.episode_id for row in self.rows],
            "worst_case_reserve_usd_per_episode": "4",
            "reasoning_effort": "high", "reasoning_history": "none",
            "source_sha256": {},
        }
        self.assignment_sha = "b" * 64
        _Ledger.snapshot_value = {
            "blocked": False, "cap_usd": "50", "unknown_run_ids": [],
            "available_usd": "50", "last_hash": "c" * 64, "runs": {},
        }

    def _preflight(self, available: str = "50") -> dict:
        _Ledger.snapshot_value = _Ledger.snapshot_value | {"available_usd": available}
        with patch.object(remote.DebitPilotPlan, "validate", return_value=(
                self.frozen, self.assignment_sha, self.rows)), \
             patch.object(remote, "BudgetLedger", _Ledger), \
             patch.object(remote, "_freeze_verify"), \
             patch.object(remote, "load_assignment", return_value=(
                 self.frozen, self.assignment_sha, self.rows)), \
             patch.object(remote, "pricing_snapshot", return_value={}), \
             patch.object(remote, "reserve_worst_case", return_value=Decimal("4")):
            return remote.preflight(self.plan)

    def test_twelve_episode_headroom_and_canonical_50_cap(self) -> None:
        self.assertEqual(len(self.rows), 12)
        with self.assertRaisesRegex(remote.RemoteBoundaryError, "full remaining"):
            self._preflight("47.99")
        ready = self._preflight("48")
        self.assertEqual(ready["remaining_episodes"], 12)
        self.assertEqual(ready["full_remaining_reservation_usd"], "48")
        _Ledger.snapshot_value["cap_usd"] = "20"
        with self.assertRaisesRegex(remote.RemoteBoundaryError, "blocked"):
            self._preflight()

    def test_debit_task_uses_fifty_thousand_tokens_with_legacy_guard(self) -> None:
        row = next(item for item in self.rows if item.bonus_minor_units == 0)
        case, artifact = case_for_episode(row)
        obligation = EscrowObligation(
            chain_id=31337, core_address="0x" + "1" * 40, job_id=1,
            provider_address="0x" + "2" * 40,
            auditor_address="0x" + "3" * 40,
            token_address="0x" + "4" * 40, funding_deadline=2_000_000_000,
        )
        kwargs = {
            "episode_id": row.episode_id, "arm": row.arm,
            "obligation": obligation, "funding_tier": "NATIVE_LOCAL_PROTOCOL",
            "submit_claim": lambda _: None, "check_debit_condition": "D0",
            "charge_check": lambda _: None, "assigned_bonus_minor_units": 0,
        }
        task = build_mechanism_task(case, artifact, **kwargs, task_token_limit=50_000)
        self.assertEqual(task.token_limit, 50_000)
        legacy_kwargs = {key: value for key, value in kwargs.items()
                         if key not in {"check_debit_condition", "charge_check",
                                        "assigned_bonus_minor_units"}}
        legacy = build_mechanism_task(case, artifact, **legacy_kwargs)
        self.assertEqual(legacy.token_limit, 16_000)
        with self.assertRaisesRegex(ValueError, "task token limit"):
            build_mechanism_task(case, artifact, **legacy_kwargs,
                                 task_token_limit=50_000)
        with self.assertRaisesRegex(ValueError, "task token limit"):
            build_mechanism_task(case, artifact, **kwargs, task_token_limit=60_000)
        with self.assertRaisesRegex(ValueError, "task token limit"):
            build_mechanism_task(case, artifact, **kwargs, task_token_limit=True)

    def test_stopped_episode_and_unknown_charge_prevent_later_calls(self) -> None:
        first = self.rows[0]
        episode = self.plan.runs_dir / "episodes" / first.episode_id
        episode.mkdir(parents=True)
        (episode / "STOPPED.json").write_text("{}\n")
        with self.assertRaisesRegex(remote.RemoteBoundaryError, "stopped"):
            self._preflight()
        (episode / "STOPPED.json").unlink()
        episode.rmdir()
        _Ledger.snapshot_value["unknown_run_ids"] = ["prior-unknown"]
        _Ledger.snapshot_value["blocked"] = True
        with self.assertRaisesRegex(remote.RemoteBoundaryError, "blocked"):
            self._preflight()

    def test_prior_direct_text_deviation_stops_later_paid_episode(self) -> None:
        row = next(item for item in self.rows if item.direct_channel)
        remaining = tuple(item for item in self.rows if item != row)
        self.rows = (row, *remaining)
        self.frozen["execution_order"] = [item.episode_id for item in self.rows]
        episode = self.plan.runs_dir / "episodes" / row.episode_id
        episode.mkdir(parents=True)
        (episode / "episode_record.json").write_text("{}\n")
        with patch.object(remote.DebitPilotPlan, "validate", return_value=(
                self.frozen, self.assignment_sha, self.rows)), \
             patch.object(remote, "BudgetLedger", _Ledger), \
             patch.object(remote, "verify_episode", return_value={
                 "direct_posted": True, "direct_message_exact": False,
                 "direct_read_exact": False,
             }) as verifier:
            with self.assertRaisesRegex(remote.RemoteBoundaryError, "direct post/read"):
                remote.preflight(self.plan)
            verifier.assert_called_once()

    def test_interrupted_paid_call_retains_partial_and_marks_unknown(self) -> None:
        row = self.rows[0]
        preview = {"next_episode_id": row.episode_id, "next_index": 0,
                   "remaining_episodes": 12}

        def interrupted(*_, **kwargs):
            self.assertEqual(kwargs["token_limit"], 60_000)
            self.assertEqual(kwargs["turn_limit"], 8)
            (Path(kwargs["log_dir"]) / "partial.eval").write_bytes(b"partial\n")
            raise RuntimeError("provider_interrupted")

        with patch.object(remote, "preflight", return_value=preview), \
             patch.object(remote, "_execution_enabled_003"), \
             patch.object(remote.DebitPilotPlan, "validate", return_value=(
                 self.frozen, self.assignment_sha, self.rows)), \
             patch.object(remote, "BudgetLedger", _Ledger), \
             patch.object(remote, "MechanismNative", _Native), \
             patch.object(remote, "build_mechanism_task", return_value=object()), \
             patch.object(remote, "account_usage_usd", return_value=Decimal("0")), \
             patch.object(remote, "get_model", return_value=object()), \
             patch.object(remote, "guard_model_api", return_value={
                 "attempted": 1, "max_input_bytes_seen": 100}), \
             patch.object(remote, "guard_high_reasoning"), \
             patch.object(remote, "_capture_model_boundary", return_value=[]), \
             patch.object(remote, "_fresh_budget_boundary", return_value=(
                 {}, Decimal("4"), _Ledger.snapshot_value)), \
             patch.object(remote, "inspect_eval", side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, "provider_interrupted"):
                remote.execute_one(self.plan)
        episode = self.plan.runs_dir / "episodes" / row.episode_id
        stop = json.loads((episode / "STOPPED.json").read_bytes())
        self.assertEqual(stop["budget_state"], "UNKNOWN")
        self.assertEqual(stop["schema"], "mechanism-debit-paid-episode-stop-v1")
        self.assertEqual(stop["model_calls_attempted"], 1)
        self.assertTrue((episode / "inspect.eval").is_file())
        self.assertTrue((episode / "native/partial_evidence.json").is_file())
        self.assertTrue(_Ledger.last.unknown)

    def test_local_model_boundary_rejection_is_recorded_without_forwarding(self) -> None:
        forwarded = []

        async def original(*args):
            forwarded.append(args)
            return object()

        model = SimpleNamespace(api=SimpleNamespace(generate=original))
        attempts = {"attempted": 0, "max_input_bytes_seen": 0}
        observed = remote._capture_model_boundary(model, self.plan, attempts)
        config = GenerateConfig(reasoning_effort="medium", reasoning_history="none",
                                max_tokens=self.plan.max_output_tokens, max_retries=0)
        with self.assertRaisesRegex(remote.RemoteBoundaryError, "reasoning policy"):
            asyncio.run(model.api.generate([ChatMessageUser(content="hello")],
                                           [], "auto", config))
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0]["local_boundary_passed"], False)
        self.assertEqual(observed[0]["forwarded"], False)
        self.assertEqual(observed[0]["billed"], False)
        self.assertEqual(attempts["attempted"], 0)
        self.assertFalse(forwarded)

    def test_saved_check_proof_must_match_native_debit_before_settlement(self) -> None:
        raw = {
            "condition": "D1", "request_id": "one-check",
            "amount_minor": 1_000_000, "sink_address": "0x" + "4" * 40,
            "transaction_hash": "0x" + "5" * 64,
            "verification_sha256": "6" * 64,
        }
        witness = dict(raw, execution_tier="NATIVE_LOCAL_PROTOCOL",
                       transfer_verified=True)
        native = SimpleNamespace(check_debit=raw)
        summary = {
            "check_debit_condition": "D1", "check_invoked": True,
            "check_debit_minor_units": 1_000_000,
            "check_debit_tx_hash": raw["transaction_hash"],
            "check_debit_request_id": raw["request_id"],
            "check_debit_verification_sha256": raw["verification_sha256"],
        }
        remote._require_native_check_debit(
            {"check_invoked": True, "check_debit": witness}, native, summary, "D1")
        witness["sink_address"] = "0x" + "7" * 40
        with self.assertRaisesRegex(remote.RemoteBoundaryError, "differs"):
            remote._require_native_check_debit(
                {"check_invoked": True, "check_debit": witness}, native, summary, "D1")


if __name__ == "__main__":
    unittest.main()
