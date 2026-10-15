"""Offline boundaries for the one-trial paid W10 runner."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import zipfile

from inspect_ai.model import GenerateConfig

from agent_economic_trust.remote import RemoteBoundaryError
from agent_economic_trust.w10_factorial_remote import (
    FactorialTrialPlan, _assert_source_frozen, _scan_native_log_for_secret,
    _source_hashes, guard_high_reasoning,
)


ROOT = Path(__file__).resolve().parents[1]
ASSIGNMENT = ROOT / "artifacts/gates/W10_DESIGN/assignment-003"


class FrozenPlanTests(unittest.TestCase):
    def test_same_seed_new_manifest_has_locked_sources(self):
        with tempfile.TemporaryDirectory(dir="/workspace") as temporary:
            plan = FactorialTrialPlan(
                model_id="openai/gpt-5.6-sol",
                trial_id="trial-56f8d0e7b83245b49b2b",
                assignment_dir=ASSIGNMENT,
                output_dir=Path(temporary) / "new",
            )
            plan.validate()
            trial, _, manifest_sha, _ = plan.frozen()
            self.assertEqual(trial.cell, "000")
            self.assertEqual(manifest_sha,
                             "369b63133240346994c506a80b2efbe4ab554e14a20b817f61f2519eee48eded")
            with self.assertRaises(RemoteBoundaryError):
                FactorialTrialPlan(**{**plan.__dict__, "cap_usd": Decimal("21")}).validate()
            plan.output_dir.mkdir()
            with self.assertRaises(RemoteBoundaryError):
                plan.validate()

    def test_source_seal_includes_native_helper(self):
        hashes = _source_hashes()
        self.assertIn("scripts/run_erc8183_local.py", hashes)
        _assert_source_frozen(hashes)
        with self.assertRaises(RemoteBoundaryError):
            _assert_source_frozen({**hashes, "scripts/run_erc8183_local.py": "0" * 64})

    def test_secret_scan_opens_archive_members(self):
        with tempfile.TemporaryDirectory(dir="/workspace") as temporary:
            archive = Path(temporary) / "log.eval"
            with zipfile.ZipFile(archive, "w") as out:
                out.writestr("payload.json", "hidden-test-key")
            log = SimpleNamespace(model_dump_json=lambda: "{}")
            with self.assertRaises(RemoteBoundaryError):
                _scan_native_log_for_secret(archive, log, "hidden-test-key")
            with zipfile.ZipFile(archive, "w") as out:
                out.writestr("payload.json", "clean")
            _scan_native_log_for_secret(archive, log, "hidden-test-key")
            with self.assertRaises(RemoteBoundaryError):
                _scan_native_log_for_secret(
                    archive, SimpleNamespace(model_dump_json=lambda: "hidden-test-key"),
                    "hidden-test-key",
                )


class HighReasoningGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_per_call_override_is_rejected_before_provider(self):
        calls = []

        async def provider(*args):
            calls.append(args)

        model = SimpleNamespace(api=SimpleNamespace(generate=provider))
        guard_high_reasoning(model)
        with self.assertRaises(RemoteBoundaryError):
            await model.api.generate([], [], "auto", GenerateConfig(reasoning_effort="low"))
        self.assertEqual(calls, [])
        await model.api.generate([], [], "auto", GenerateConfig(reasoning_effort="high"))
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
