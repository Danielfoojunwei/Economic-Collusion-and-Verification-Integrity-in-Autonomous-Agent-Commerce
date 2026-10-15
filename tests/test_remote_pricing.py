"""Offline checks for conservative W05 OpenRouter pricing."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import io
import json
import unittest
from unittest.mock import patch

from agent_economic_trust.remote_pricing import (
    CATALOG_URL,
    MODEL_ID,
    PricingError,
    estimate_usage,
    pricing_snapshot,
    reserve_worst_case,
)


def catalog_fixture() -> dict:
    return {
        "data": [{
            "id": MODEL_ID,
            "context_length": 1050000,
            "architecture": {
                "input_modalities": ["text", "image", "file"],
                "output_modalities": ["text"],
            },
            "top_provider": {"max_completion_tokens": 128000},
            "supported_parameters": [
                "tools", "tool_choice", "reasoning", "reasoning_effort",
                "max_tokens", "max_completion_tokens",
            ],
            "pricing": {
                "prompt": "0.000004",
                "completion": "0.00002",
                "input_cache_read": "0.0000004",
                "input_cache_write": "0.000005",
                "overrides": [{
                    "min_prompt_tokens": 272000,
                    "prompt": "0.000008",
                    "completion": "0.00003",
                    "input_cache_read": "0.0000008",
                    "input_cache_write": "0.00001",
                }],
                "web_search": "0.01",
            },
        }],
    }


class PricingSnapshotTests(unittest.TestCase):
    def test_exact_model_uses_highest_price_tier_and_is_serializable(self) -> None:
        snapshot = pricing_snapshot(catalog=catalog_fixture())
        self.assertEqual(snapshot["model_id"], MODEL_ID)
        self.assertEqual(snapshot["input_usd_per_token"], "0.00001")
        self.assertEqual(snapshot["output_usd_per_token"], "0.00003")
        self.assertEqual(snapshot["pricing_tiers"], 2)
        self.assertEqual(len(snapshot["catalog_model_sha256"]), 64)
        json.dumps(snapshot)

    def test_public_fetch_has_no_authorization_header(self) -> None:
        response = io.BytesIO(json.dumps(catalog_fixture()).encode())
        with patch("agent_economic_trust.remote_pricing.urlopen", return_value=response) as open_mock:
            snapshot = pricing_snapshot()
        request = open_mock.call_args.args[0]
        self.assertEqual(request.full_url, CATALOG_URL)
        self.assertNotIn("Authorization", request.headers)
        self.assertEqual(snapshot["model_id"], MODEL_ID)

    def test_wrong_or_duplicate_model_fails_closed(self) -> None:
        with self.assertRaises(PricingError):
            pricing_snapshot("openai/other", catalog=catalog_fixture())
        duplicate = catalog_fixture()
        duplicate["data"].append(deepcopy(duplicate["data"][0]))
        with self.assertRaises(PricingError):
            pricing_snapshot(catalog=duplicate)

    def test_missing_capability_or_override_price_fails_closed(self) -> None:
        missing_tool = catalog_fixture()
        missing_tool["data"][0]["supported_parameters"].remove("tools")
        with self.assertRaises(PricingError):
            pricing_snapshot(catalog=missing_tool)
        missing_rate = catalog_fixture()
        del missing_rate["data"][0]["pricing"]["overrides"][0]["completion"]
        with self.assertRaises(PricingError):
            pricing_snapshot(catalog=missing_rate)

    def test_zero_or_nonnumeric_price_fails_closed(self) -> None:
        for value in ("0", "NaN", "infinity", "free"):
            with self.subTest(value=value):
                bad = catalog_fixture()
                bad["data"][0]["pricing"]["prompt"] = value
                with self.assertRaises(PricingError):
                    pricing_snapshot(catalog=bad)


class CostBoundTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = pricing_snapshot(catalog=catalog_fixture())

    def test_five_calls_reserve_above_short_context_pricing(self) -> None:
        self.assertEqual(
            reserve_worst_case(self.snapshot, 5, 32768, 4096),
            Decimal("2.662400"),
        )

    def test_output_context_and_missing_snapshot_bound_rejected(self) -> None:
        with self.assertRaises(PricingError):
            reserve_worst_case(self.snapshot, 1, 10, 128001)
        with self.assertRaises(PricingError):
            reserve_worst_case(self.snapshot, 0, 10, 10)
        with self.assertRaises(PricingError):
            reserve_worst_case({"model_id": MODEL_ID}, 1, 10, 10)

    def test_usage_charges_caches_and_reasoning_conservatively(self) -> None:
        usage = {
            "input_tokens": 1000,
            "output_tokens": 100,
            "input_tokens_cache_read": 200,
            "input_tokens_cache_write": 100,
            "reasoning_tokens": 150,
            "total_tokens": 1500,
            "total_cost": 0.002,
        }
        # 1300 input at $10/M and 150 output at $30/M; unexplained
        # 50 total tokens are charged at the higher output rate.
        self.assertEqual(estimate_usage(self.snapshot, usage), Decimal("0.019000"))
        usage["total_cost"] = 0.25
        self.assertEqual(estimate_usage(self.snapshot, usage), Decimal("0.250000"))

    def test_missing_or_invalid_usage_fails_closed(self) -> None:
        for usage in (None, {}, {"input_tokens": -1}, {"input_tokens": 0, "output_tokens": 0}):
            with self.subTest(usage=usage):
                with self.assertRaises(PricingError):
                    estimate_usage(self.snapshot, usage)

    def test_request_fee_is_counted_per_actual_call(self) -> None:
        snapshot = dict(self.snapshot, request_usd="0.01")
        self.assertEqual(
            reserve_worst_case(snapshot, 2, 1000, 100),
            Decimal("0.209840"),
        )
        self.assertEqual(
            estimate_usage(snapshot, {"input_tokens": 100, "output_tokens": 10}, calls=2),
            Decimal("0.021300"),
        )


if __name__ == "__main__":
    unittest.main()
