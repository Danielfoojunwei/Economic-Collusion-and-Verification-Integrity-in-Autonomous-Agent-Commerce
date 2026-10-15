"""No-network W05 control-plane checks; no test sends model requests."""

from __future__ import annotations

from decimal import Decimal
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from inspect_ai.model import GenerateConfig, get_model

from agent_economic_trust.remote import (
    RemoteBoundaryError, RemotePlan, _execution_enabled, account_usage_delta_usd,
    account_usage_usd, guard_model_api, preflight,
)
from agent_economic_trust.remote_budget import create_ledger
from agent_economic_trust.remote_pricing import pricing_snapshot

from test_remote_pricing import catalog_fixture


class RemotePlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.plan = RemotePlan(
            model_id="openai/gpt-5.6-sol", sample_ids=("reconcile-002",),
            output_dir=root / "new-output", ledger_path=root / "budget.jsonl",
        )

    def test_dry_run_has_no_inference_and_requires_explicit_ledger(self) -> None:
        snapshot = pricing_snapshot(catalog=catalog_fixture())
        with patch("agent_economic_trust.remote.pricing_snapshot", return_value=snapshot):
            forecast = preflight(self.plan)
        self.assertEqual(forecast["sample_ids"], ["reconcile-002"])
        self.assertEqual(forecast["worst_case_reservation_usd_per_sample"], "2.662400")
        self.assertFalse(forecast["ready_to_execute"])
        self.assertFalse(self.plan.output_dir.exists())
        create_ledger(self.plan.ledger_path, "20", "1.50")
        with patch("agent_economic_trust.remote.pricing_snapshot", return_value=snapshot):
            forecast = preflight(self.plan)
        self.assertTrue(forecast["ready_to_execute"])
        self.assertEqual(forecast["ledger"]["available_usd"], "18.5")

    def test_wrong_model_cap_sample_and_output_path_fail_closed(self) -> None:
        changes = (
            {"model_id": "openai/other"},
            {"cap_usd": Decimal("20.01")},
            {"sample_ids": ("reconcile-001", "reconcile-001")},
            {"sample_ids": ("unknown",)},
            {"max_output_tokens": 4097},
            {"max_input_bytes": 32769},
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(RemoteBoundaryError):
                RemotePlan(**{**self.plan.__dict__, **change}).validate()
        self.plan.output_dir.mkdir()
        with self.assertRaises(RemoteBoundaryError):
            self.plan.validate()

    def test_execution_env_is_explicit_and_does_not_log_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RemoteBoundaryError):
                _execution_enabled()
        good = {
            "ALLOW_EXTERNAL_MODEL_CALLS": "true", "MAX_REAL_SPEND": "20",
            "OPENROUTER_API_KEY": "test-secret-not-for-network",
            "ALLOW_MAINNET": "false",
        }
        with patch.dict(os.environ, good, clear=True):
            _execution_enabled()
            os.environ["MAX_REAL_SPEND"] = "21"
            with self.assertRaises(RemoteBoundaryError):
                _execution_enabled()
            os.environ["MAX_REAL_SPEND"] = "20"
            os.environ["ALLOW_MAINNET"] = "true"
            with self.assertRaises(RemoteBoundaryError):
                _execution_enabled()

    def test_provider_request_shape_is_bounded_without_network(self) -> None:
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "unit-test-only"}):
            config = GenerateConfig(
                reasoning_effort="high", max_tokens=4096, max_retries=0,
                timeout=180, max_connections=1, cache=False,
            )
            model = get_model(
                "openrouter/openai/gpt-5.6-sol", config=config, memoize=False,
                base_url="https://openrouter.ai/api/v1", max_retries=0,
                stream=False, responses_api=False,
            )
            params = model.api.completion_params(config, tools=True)
        self.assertEqual(params["model"], "openai/gpt-5.6-sol")
        self.assertEqual(params["extra_body"]["reasoning"]["effort"], "high")
        self.assertEqual(params.get("max_completion_tokens", params.get("max_tokens")), 4096)
        self.assertEqual(model.api.client.max_retries, 0)
        self.assertFalse(model.api.stream)

    def test_account_usage_read_and_counter_decrease_fail_closed(self) -> None:
        body = json.dumps({"data": {"usage": 1.25, "limit_remaining": 99}}).encode()
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "unit-test-only"}):
            with patch("agent_economic_trust.remote.urlopen", return_value=io.BytesIO(body)) as request:
                self.assertEqual(account_usage_usd(), Decimal("1.25"))
            self.assertEqual(request.call_args.args[0].full_url,
                             "https://openrouter.ai/api/v1/auth/key")
            with patch("agent_economic_trust.remote.urlopen", side_effect=OSError("redacted")):
                with self.assertRaises(RemoteBoundaryError):
                    account_usage_usd()
        self.assertEqual(account_usage_delta_usd(Decimal("1.25"), Decimal("1.3")), Decimal("0.05"))
        with self.assertRaises(RemoteBoundaryError):
            account_usage_delta_usd(Decimal("2"), Decimal("1"))


class GuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_call_input_and_output_caps_block_before_provider(self) -> None:
        provider_calls = []

        async def provider(input, tools, tool_choice, config):
            provider_calls.append(input)
            return "ok"

        model = SimpleNamespace(api=SimpleNamespace(generate=provider))
        counters = guard_model_api(
            model, max_calls=1, max_input_bytes=1024, max_output_tokens=100,
        )
        message = SimpleNamespace(model_dump=lambda mode: {"role": "user", "content": "x"})
        config = GenerateConfig(max_tokens=100, max_retries=0)
        self.assertEqual(await model.api.generate([message], [], "auto", config), "ok")
        self.assertEqual(counters["attempted"], 1)
        with self.assertRaises(RemoteBoundaryError):
            await model.api.generate([message], [], "auto", config)
        self.assertEqual(len(provider_calls), 1)

        another = SimpleNamespace(api=SimpleNamespace(generate=provider))
        guard_model_api(another, max_calls=1, max_input_bytes=1024, max_output_tokens=100)
        with self.assertRaises(RemoteBoundaryError):
            await another.api.generate([message], [], "auto", GenerateConfig(max_tokens=101))
        self.assertEqual(len(provider_calls), 1)

        oversized = SimpleNamespace(
            model_dump=lambda mode: {"role": "user", "content": "x" * 1100}
        )
        with self.assertRaises(RemoteBoundaryError):
            await another.api.generate([oversized], [], "auto", config)
        self.assertEqual(len(provider_calls), 1)


if __name__ == "__main__":
    unittest.main()
