"""Conservative public-catalog pricing for two exact OpenRouter model IDs."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from hashlib import sha256
import json
from typing import Any, Mapping

from .mpp006_plan import (AUDITOR_CALLS, INPUT_FRAMING_TOKENS_PER_CALL,
    MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS, MODELS, PROVIDER_CALLS)
from .remote_pricing import CATALOG_URL, _catalog_data


class MixedPricingError(ValueError):
    pass


def _money(value: Any, label: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise MixedPricingError(f"{label} is not numeric")
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise MixedPricingError(f"{label} is not decimal") from exc
    if not result.is_finite() or result < 0 or positive and result == 0:
        raise MixedPricingError(f"{label} must be finite and nonnegative" + (" and positive" if positive else ""))
    return result


def pricing_snapshots(*, catalog: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Pin highest rate across listed length and cache tiers for both families."""
    catalog = _catalog_data() if catalog is None else catalog
    if not isinstance(catalog, Mapping) or not isinstance(catalog.get("data"), list):
        raise MixedPricingError("public catalog lacks model list")
    snapshots = {}
    for model_id in MODELS:
        matches = [m for m in catalog["data"] if isinstance(m, Mapping) and m.get("id") == model_id]
        if len(matches) != 1:
            raise MixedPricingError(f"catalog requires exactly one {model_id}")
        model = matches[0]
        parameters = model.get("supported_parameters")
        if (not isinstance(parameters, list) or not {"tools", "reasoning", "reasoning_effort"}.issubset(parameters)
                or not {"max_tokens", "max_completion_tokens"}.intersection(parameters)):
            raise MixedPricingError(f"{model_id} lacks required tool/reasoning limits")
        architecture = model.get("architecture")
        if (not isinstance(architecture, Mapping)
                or "text" not in architecture.get("input_modalities", [])
                or "text" not in architecture.get("output_modalities", [])):
            raise MixedPricingError(f"{model_id} lacks text I/O")
        provider = model.get("top_provider")
        context = model.get("context_length")
        completion = provider.get("max_completion_tokens") if isinstance(provider, Mapping) else None
        if (type(context) is not int or type(completion) is not int
                or context < MAX_INPUT_BYTES + INPUT_FRAMING_TOKENS_PER_CALL + MAX_OUTPUT_TOKENS
                or completion < MAX_OUTPUT_TOKENS):
            raise MixedPricingError(f"{model_id} has insufficient published context or output")
        pricing = model.get("pricing")
        if not isinstance(pricing, Mapping):
            raise MixedPricingError(f"{model_id} lacks prices")
        overrides = pricing.get("overrides", [])
        if not isinstance(overrides, list) or any(not isinstance(tier, Mapping) for tier in overrides):
            raise MixedPricingError(f"{model_id} has malformed tier prices")
        input_prices = []
        output_prices = []
        request_prices = []
        for tier in [pricing, *overrides]:
            input_prices.append(_money(tier.get("prompt"), "prompt price", positive=True))
            output_prices.append(_money(tier.get("completion"), "completion price", positive=True))
            request_prices.append(_money(tier.get("request", "0"), "request price"))
            for key, value in tier.items():
                if key.startswith("input_cache_read") or key.startswith("input_cache_write"):
                    input_prices.append(_money(value, key))
        canonical_model = json.dumps(model, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        snapshots[model_id] = {
            "model_id": model_id,
            "catalog_model_sha256": sha256(canonical_model.encode()).hexdigest(),
            "fetched_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "input_usd_per_token": str(max(input_prices)),
            "output_usd_per_token": str(max(output_prices)),
            "request_usd": str(max(request_prices)),
            "context_length": context, "max_completion_tokens": completion,
            "input_framing_tokens_per_call": INPUT_FRAMING_TOKENS_PER_CALL,
            "pricing_tiers": len(overrides) + 1, "source_url": CATALOG_URL,
        }
    return snapshots


def reserve_pair(snapshots: Mapping[str, Mapping[str, Any]], provider: str, auditor: str) -> Decimal:
    if set(snapshots) != set(MODELS) or provider not in MODELS or auditor not in MODELS:
        raise MixedPricingError("unapproved or missing model price")
    result = Decimal(0)
    for model_id, calls in ((provider, PROVIDER_CALLS), (auditor, AUDITOR_CALLS)):
        snapshot = snapshots[model_id]
        if snapshot.get("model_id") != model_id:
            raise MixedPricingError("model price identity differs")
        per_call = ((MAX_INPUT_BYTES + INPUT_FRAMING_TOKENS_PER_CALL)
                    * _money(snapshot["input_usd_per_token"], "input rate", positive=True)
                    + MAX_OUTPUT_TOKENS * _money(snapshot["output_usd_per_token"], "output rate", positive=True)
                    + _money(snapshot["request_usd"], "request rate"))
        result += calls * per_call
    return result.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)


def estimate_model_usage(snapshot: Mapping[str, Any], usage: Any, calls: int) -> Decimal:
    """Charge all observed and unexplained tokens at conservative catalog rates."""
    if snapshot.get("model_id") not in MODELS or type(calls) is not int or calls <= 0:
        raise MixedPricingError("model usage lacks approved ID or positive call count")
    def field(name: str) -> int:
        value = getattr(usage, name, None)
        if type(value) is not int or value < 0:
            raise MixedPricingError(f"{name} is missing or invalid")
        return value
    input_tokens, output_tokens, total = (field(name) for name in
        ("input_tokens", "output_tokens", "total_tokens"))
    cache_read = getattr(usage, "input_tokens_cache_read", None) or 0
    cache_write = getattr(usage, "input_tokens_cache_write", None) or 0
    reasoning = getattr(usage, "reasoning_tokens", None) or 0
    if any(type(n) is not int or n < 0 for n in (cache_read, cache_write, reasoning)):
        raise MixedPricingError("cache/reasoning usage invalid")
    if not any((input_tokens, output_tokens, total, cache_read, cache_write, reasoning)):
        raise MixedPricingError("empty provider usage")
    input_rate = _money(snapshot["input_usd_per_token"], "input rate", positive=True)
    output_rate = _money(snapshot["output_usd_per_token"], "output rate", positive=True)
    charged_output = max(output_tokens, reasoning)
    unexplained = max(0, total - input_tokens - cache_read - cache_write - charged_output)
    estimated = ((input_tokens + cache_read + cache_write) * input_rate
                 + charged_output * output_rate + unexplained * max(input_rate, output_rate)
                 + calls * _money(snapshot["request_usd"], "request rate"))
    reported = getattr(usage, "total_cost", None)
    if reported is not None:
        estimated = max(estimated, _money(reported, "provider cost"))
    return estimated.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)
