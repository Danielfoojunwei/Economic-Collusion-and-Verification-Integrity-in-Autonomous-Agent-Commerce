"""Conservative OpenRouter text-call pricing for the bounded W05 pilot.

The public catalog is read without credentials. A snapshot records the highest
price across every listed prompt-length tier, so a run cannot accidentally use
the cheaper short-context price when its prompts grow. These functions do not
send model requests or authorize spending.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from hashlib import sha256
import json
from typing import Any, Mapping
from urllib.request import Request, urlopen


CATALOG_URL = "https://openrouter.ai/api/v1/models"
MODEL_ID = "openai/gpt-5.6-sol"
CATALOG_MAX_BYTES = 4 * 1024 * 1024
# One UTF-8 byte is conservatively treated as one prompt token. The allowance
# covers provider chat/tool framing not represented in the serialized payload.
INPUT_FRAMING_TOKENS_PER_CALL = 8192
USD_QUANTUM = Decimal("0.000001")


class PricingError(ValueError):
    """A catalog or usage value cannot support a safe cost bound."""


def _nonnegative_money(value: Any, label: str) -> Decimal:
    # Inspect's ModelUsage.total_cost is a float; catalog prices are strings.
    # Decimal(str(float)) preserves the reported decimal, without binary math.
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise PricingError(f"{label} must be a decimal price")
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise PricingError(f"{label} is not a decimal price") from exc
    if not price.is_finite() or price < 0:
        raise PricingError(f"{label} must be finite and nonnegative")
    return price


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PricingError(f"{label} must be a positive integer")
    return value


def _usage_int(value: Any, label: str) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PricingError(f"{label} must be a nonnegative integer")
    return value


def _price_for_tier(tier: Mapping[str, Any], key: str, *, required: bool) -> Decimal | None:
    value = tier.get(key)
    if value is None:
        if required:
            raise PricingError(f"catalog price {key} is missing")
        return None
    return _nonnegative_money(value, f"catalog price {key}")


def _catalog_data() -> dict[str, Any]:
    # Deliberately no Authorization header or environment-credential lookup.
    request = Request(CATALOG_URL, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=15) as response:
            raw = response.read(CATALOG_MAX_BYTES + 1)
    except Exception as exc:
        raise PricingError("public OpenRouter catalog could not be fetched") from exc
    if len(raw) > CATALOG_MAX_BYTES:
        raise PricingError("public OpenRouter catalog exceeds size limit")
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PricingError("public OpenRouter catalog is not JSON") from exc
    if not isinstance(parsed, dict):
        raise PricingError("public OpenRouter catalog is not an object")
    return parsed


def pricing_snapshot(
    model_id: str = MODEL_ID,
    *,
    catalog: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Read and validate one exact text model's public pricing and capabilities.

    Passing ``catalog`` supports deterministic tests and saved-catalog review.
    The normal path fetches the public catalog, without an API key.
    """
    if model_id != MODEL_ID:
        raise PricingError(f"unapproved model id: {model_id!r}")
    catalog = _catalog_data() if catalog is None else catalog
    if not isinstance(catalog, Mapping) or not isinstance(catalog.get("data"), list):
        raise PricingError("catalog is missing model data")
    matches = [item for item in catalog["data"] if isinstance(item, Mapping) and item.get("id") == model_id]
    if len(matches) != 1:
        raise PricingError("catalog must contain exactly one matching model")
    model = matches[0]

    parameters = model.get("supported_parameters")
    if not isinstance(parameters, list) or not all(isinstance(p, str) for p in parameters):
        raise PricingError("catalog supported_parameters is malformed")
    required = {"tools", "reasoning", "reasoning_effort"}
    if not required.issubset(parameters) or not {"max_tokens", "max_completion_tokens"}.intersection(parameters):
        raise PricingError("model lacks required tool/reasoning/token controls")
    architecture = model.get("architecture")
    if not isinstance(architecture, Mapping):
        raise PricingError("model architecture is missing")
    input_modalities = architecture.get("input_modalities")
    output_modalities = architecture.get("output_modalities")
    if not isinstance(input_modalities, list) or not isinstance(output_modalities, list):
        raise PricingError("model modalities are malformed")
    if "text" not in input_modalities or "text" not in output_modalities:
        raise PricingError("model does not support text input and output")
    top_provider = model.get("top_provider")
    if not isinstance(top_provider, Mapping):
        raise PricingError("model top_provider is missing")
    max_completion = _positive_int(top_provider.get("max_completion_tokens"), "max_completion_tokens")
    context_length = _positive_int(model.get("context_length"), "context_length")

    pricing = model.get("pricing")
    if not isinstance(pricing, Mapping):
        raise PricingError("model pricing is missing")
    overrides = pricing.get("overrides", [])
    if not isinstance(overrides, list) or not all(isinstance(tier, Mapping) for tier in overrides):
        raise PricingError("catalog pricing overrides are malformed")
    tiers = [pricing, *overrides]
    input_rates: list[Decimal] = []
    output_rates: list[Decimal] = []
    cache_read_rates: list[Decimal] = []
    cache_write_rates: list[Decimal] = []
    request_prices: list[Decimal] = []
    for index, tier in enumerate(tiers):
        if index:
            _positive_int(tier.get("min_prompt_tokens"), "override min_prompt_tokens")
        prompt = _price_for_tier(tier, "prompt", required=True)
        completion = _price_for_tier(tier, "completion", required=True)
        assert prompt is not None and completion is not None
        if prompt == 0 or completion == 0:
            raise PricingError("catalog prompt and completion rates must be positive")
        input_rates.append(prompt)
        output_rates.append(completion)
        cache_read_rates.append(_price_for_tier(tier, "input_cache_read", required=False) or prompt)
        cache_write_rates.append(_price_for_tier(tier, "input_cache_write", required=False) or prompt)
        request_prices.append(_price_for_tier(tier, "request", required=False) or Decimal(0))

    # A cached-token price is a category rate, but treating it as an alternate
    # input-token price protects the reservation even if provider usage fields
    # are later interpreted differently.
    highest_input = max([*input_rates, *cache_read_rates, *cache_write_rates])
    highest_output = max(output_rates)
    canonical_model = json.dumps(model, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "model_id": model_id,
        "catalog_model_sha256": sha256(canonical_model.encode("utf-8")).hexdigest(),
        "fetched_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "input_usd_per_token": str(highest_input),
        "output_usd_per_token": str(highest_output),
        "cache_read_usd_per_token": str(max(cache_read_rates)),
        "cache_write_usd_per_token": str(max(cache_write_rates)),
        "request_usd": str(max(request_prices)),
        "max_completion_tokens": max_completion,
        "context_length": context_length,
        "input_framing_tokens_per_call": INPUT_FRAMING_TOKENS_PER_CALL,
        "pricing_tiers": len(tiers),
        "source_url": CATALOG_URL,
    }


def _snapshot_rate(snapshot: Mapping[str, Any], key: str, *, positive: bool) -> Decimal:
    value = _nonnegative_money(snapshot.get(key), f"snapshot {key}")
    if positive and value == 0:
        raise PricingError(f"snapshot {key} must be positive")
    return value


def reserve_worst_case(
    snapshot: Mapping[str, Any],
    max_calls: int,
    max_input_bytes: int,
    max_output_tokens: int,
) -> Decimal:
    """Ceiling USD for bounded text calls, including hidden framing allowance.

    The caller must enforce each request's serialized UTF-8 input byte cap,
    output-token cap, and number of calls before opening the network request.
    """
    if not isinstance(snapshot, Mapping) or snapshot.get("model_id") != MODEL_ID:
        raise PricingError("missing or unapproved model pricing snapshot")
    calls = _positive_int(max_calls, "max_calls")
    input_bytes = _positive_int(max_input_bytes, "max_input_bytes")
    output_tokens = _positive_int(max_output_tokens, "max_output_tokens")
    if output_tokens > _positive_int(snapshot.get("max_completion_tokens"), "catalog max_completion_tokens"):
        raise PricingError("output token cap exceeds catalog model limit")
    framing_tokens = _positive_int(snapshot.get("input_framing_tokens_per_call"), "framing allowance")
    if input_bytes + framing_tokens + output_tokens > _positive_int(snapshot.get("context_length"), "context_length"):
        raise PricingError("requested token ceiling exceeds model context")
    input_rate = _snapshot_rate(snapshot, "input_usd_per_token", positive=True)
    output_rate = _snapshot_rate(snapshot, "output_usd_per_token", positive=True)
    cache_read_rate = _snapshot_rate(snapshot, "cache_read_usd_per_token", positive=False)
    cache_write_rate = _snapshot_rate(snapshot, "cache_write_usd_per_token", positive=False)
    request_price = _snapshot_rate(snapshot, "request_usd", positive=False)
    safest_input = max(input_rate, cache_read_rate, cache_write_rate)
    per_call = (input_bytes + framing_tokens) * safest_input + output_tokens * output_rate + request_price
    return (calls * per_call).quantize(USD_QUANTUM, rounding=ROUND_CEILING)


def _usage_value(usage: Any, key: str) -> Any:
    if isinstance(usage, Mapping):
        return usage.get(key)
    return getattr(usage, key, None)


def estimate_usage(snapshot: Mapping[str, Any], usage: Any, *, calls: int = 1) -> Decimal:
    """Conservative USD from observed Inspect ``ModelUsage`` or its dict.

    Cache and unexplained total tokens receive the highest input/output rate.
    A provider-reported total cost, when present, takes precedence if higher.
    Missing token usage fails closed, since an empty usage record cannot prove
    that a network request was free.
    """
    if not isinstance(snapshot, Mapping) or snapshot.get("model_id") != MODEL_ID:
        raise PricingError("missing or unapproved model pricing snapshot")
    if usage is None:
        raise PricingError("model usage is missing")
    input_tokens = _usage_int(_usage_value(usage, "input_tokens"), "input_tokens")
    output_tokens = _usage_int(_usage_value(usage, "output_tokens"), "output_tokens")
    cache_read = _usage_int(_usage_value(usage, "input_tokens_cache_read"), "input_tokens_cache_read")
    cache_write = _usage_int(_usage_value(usage, "input_tokens_cache_write"), "input_tokens_cache_write")
    reasoning = _usage_int(_usage_value(usage, "reasoning_tokens"), "reasoning_tokens")
    total = _usage_int(_usage_value(usage, "total_tokens"), "total_tokens")
    if not any((input_tokens, output_tokens, cache_read, cache_write, reasoning, total)):
        raise PricingError("model usage has no token counts")
    input_rate = _snapshot_rate(snapshot, "input_usd_per_token", positive=True)
    output_rate = _snapshot_rate(snapshot, "output_usd_per_token", positive=True)
    cache_read_rate = _snapshot_rate(snapshot, "cache_read_usd_per_token", positive=False)
    cache_write_rate = _snapshot_rate(snapshot, "cache_write_usd_per_token", positive=False)
    request_price = _snapshot_rate(snapshot, "request_usd", positive=False)
    call_count = _positive_int(calls, "calls")
    charged_output = max(output_tokens, reasoning)
    categorized = input_tokens + cache_read + cache_write + charged_output
    unexplained = max(0, total - categorized)
    estimated = (
        input_tokens * input_rate
        + cache_read * max(input_rate, cache_read_rate)
        + cache_write * max(input_rate, cache_write_rate)
        + charged_output * output_rate
        + unexplained * max(input_rate, output_rate)
        + call_count * request_price
    )
    provider_cost = _usage_value(usage, "total_cost")
    if provider_cost is not None:
        estimated = max(estimated, _nonnegative_money(provider_cost, "provider total_cost"))
    return estimated.quantize(USD_QUANTUM, rounding=ROUND_CEILING)
