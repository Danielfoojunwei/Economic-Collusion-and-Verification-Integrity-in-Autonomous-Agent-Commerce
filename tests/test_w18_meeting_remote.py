"""Offline guards for the W18 held-out live entry point."""

from __future__ import annotations

import asyncio
from decimal import Decimal
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log
from inspect_ai.model import GenerateConfig

from agent_economic_trust.meeting_generalization import calibration_artifacts, calibration_case
from agent_economic_trust.remote import RemoteBoundaryError
from agent_economic_trust.remote_budget import BudgetLedger, create_ledger
from agent_economic_trust.remote_pricing import pricing_snapshot
from agent_economic_trust.w18_meeting_remote import (
    MeetingPlan, _assert_frozen, _behavior_signature, _code_hashes,
    _guard_source_and_reasoning, _scan_native_log_for_secret, execute, preflight,
)
from agent_economic_trust.w18_meeting_task import (
    MeetingAuditError, inspect_meeting_log, meeting_audit_orbit,
)
from tests.test_remote_pricing import catalog_fixture
from tests.test_w18_meeting_task import MODEL, scripted_model


class MeetingRemoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory(prefix="w18-remote-test-", dir="/workspace")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.ledger_path = self.root / "budget.jsonl"
        create_ledger(self.ledger_path, "20", "2.03895")
        self.plan = MeetingPlan(
            model_id="openai/gpt-5.6-sol", output_dir=self.root / "fresh",
            ledger_path=self.ledger_path,
        )
        self.pricing = pricing_snapshot(catalog=catalog_fixture())
        canonical = patch(
            "agent_economic_trust.w18_meeting_remote.PROJECT_LEDGER_PATH", self.ledger_path,
        )
        canonical.start()
        self.addCleanup(canonical.stop)

    def test_dry_run_checks_pins_and_budget_without_model_or_ledger_mutation(self) -> None:
        with patch("agent_economic_trust.w18_meeting_remote.pricing_snapshot",
                   return_value=self.pricing) as rates, patch(
                   "agent_economic_trust.w18_meeting_remote.get_model") as model, patch(
                   "agent_economic_trust.w18_meeting_remote.heldout_pilot_case") as heldout:
            forecast = preflight(self.plan)
        rates.assert_called_once_with("openai/gpt-5.6-sol")
        model.assert_not_called()
        heldout.assert_not_called()
        self.assertTrue(forecast["ready_to_execute"])
        self.assertEqual(forecast["task_id"], "orbit-meeting-heldout-211")
        self.assertEqual(forecast["split"], "heldout_pilot")
        self.assertEqual(forecast["reasoning_effort"], "high")
        self.assertEqual(forecast["payment_tier"], "NO_PAYMENT")
        self.assertEqual(forecast["max_provider_calls"], 6)
        self.assertEqual(forecast["worst_case_reservation_usd"], "3.194880")
        self.assertEqual(len(forecast["orbit_source_sha256"]), 3)
        self.assertFalse(self.plan.output_dir.exists())
        self.assertEqual(BudgetLedger(self.ledger_path).snapshot()["seq"], 0)

    def test_exact_model_shared_ledger_and_source_seal_are_required(self) -> None:
        with self.assertRaises(RemoteBoundaryError):
            MeetingPlan("openai/gpt-5.6-luna", self.root / "x", self.ledger_path).validate()
        with self.assertRaises(RemoteBoundaryError):
            MeetingPlan("openai/gpt-5.6-sol", self.root / "x", self.ledger_path,
                        cap_usd=Decimal("21")).validate()
        with self.assertRaises(RemoteBoundaryError):
            MeetingPlan("openai/gpt-5.6-sol", self.root / "x",
                        self.root / "separate.jsonl").validate()
        with patch("agent_economic_trust.w18_meeting_remote.verify_orbit_source",
                   side_effect=RuntimeError("source drift")):
            with self.assertRaisesRegex(RuntimeError, "source drift"):
                preflight(self.plan)

    def test_paid_path_stays_disabled_without_explicit_environment(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch(
                "agent_economic_trust.w18_meeting_remote.get_model") as model:
            with self.assertRaises(RemoteBoundaryError):
                execute(self.plan)
        model.assert_not_called()
        self.assertFalse(self.plan.output_dir.exists())
        self.assertEqual(BudgetLedger(self.ledger_path).snapshot()["seq"], 0)

    def test_no_caller_supplied_pricing_snapshot_can_bypass_fresh_lookup(self) -> None:
        with self.assertRaises(TypeError):
            execute(self.plan, pricing=self.pricing)

    def test_source_or_reasoning_drift_stops_before_provider_call(self) -> None:
        sealed = _code_hashes()
        self.assertIn("scripts/run_w18_openrouter.py", sealed)
        self.assertIn("reporting.py", sealed)
        changed = dict(sealed)
        changed["remote_pricing.py"] = "0" * 64
        with self.assertRaisesRegex(RemoteBoundaryError, "source changed"):
            _assert_frozen(changed)

        called = []

        class Model:
            class API:
                async def generate(self, input, tools, tool_choice, config):
                    called.append(True)
                    return None

            api = API()

        model = Model()
        with patch("agent_economic_trust.w18_meeting_remote._assert_frozen"):
            _guard_source_and_reasoning(model, sealed)
            with self.assertRaisesRegex(RemoteBoundaryError, "high reasoning"):
                asyncio.run(model.api.generate([], [], "auto", GenerateConfig(reasoning_effort="low")))
        self.assertEqual(called, [])

    def test_compressed_native_log_credential_is_detected(self) -> None:
        secret = "unit-test-credential-9a7c"
        archive = self.root / "native.eval"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            output.writestr("event.json", "{" + secret + "}")
        self.assertNotIn(secret.encode(), archive.read_bytes())

        class EmptyLog:
            def model_dump_json(self):
                return "{}"

        with self.assertRaisesRegex(RemoteBoundaryError, "archive"):
            _scan_native_log_for_secret(archive, EmptyLog(), secret)

    def test_scripted_saved_log_blinding_and_runtime_behavior_match(self) -> None:
        case = calibration_case()
        good, _ = calibration_artifacts(case)
        [runtime] = inspect_eval(
            meeting_audit_orbit(case, scheduler_seconds=60, task_token_limit=12000),
            model=scripted_model(good, checked=True),
            log_dir=str(self.root / "scripted"), display="none",
            log_realtime=False, max_retries=0, retry_on_error=0,
        )
        self.assertEqual(runtime.status, "success", runtime.error)
        saved = read_eval_log(runtime.location, resolve_attachments=True)
        self.assertEqual(_behavior_signature(runtime, include_inputs=False),
                         _behavior_signature(saved, include_inputs=False))
        self.assertEqual(inspect_meeting_log(saved, case, expected_model=MODEL)["model_events"], 6)

        model_event = next(event for event in saved.samples[0].events if event.event == "model")
        model_event.input[0].content = str(model_event.input[0].content) + "reference_commitment"
        with self.assertRaisesRegex(MeetingAuditError, "private reference"):
            inspect_meeting_log(saved, case, expected_model=MODEL)

        saved = read_eval_log(runtime.location, resolve_attachments=True)
        model_event = next(event for event in saved.samples[0].events if event.event == "model")
        model_event.tools[0].name = "priced_meeting_check"
        with self.assertRaisesRegex(MeetingAuditError, "wrong-role"):
            inspect_meeting_log(saved, case, expected_model=MODEL)


if __name__ == "__main__":
    unittest.main()
