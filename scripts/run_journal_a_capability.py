#!/usr/bin/env python3
"""Bounded, zero-price benign tool-call preflight; excludes all result cohorts."""
from __future__ import annotations

import argparse
from collections.abc import Mapping
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agent_economic_trust.free_collusion_probe import (
    OpenRouterTransport, canonical, utc_now, _money,
)

PLAN = ROOT / "journal_A_v1/CAPABILITY_PILOT_PLAN.json"
TOOL_NAMES = {"provider": "submit_booking", "auditor": "audit_decision"}


def zero_price_snapshot(catalog: dict, model_id: str) -> dict:
    if not model_id.endswith(":free") or not isinstance(catalog.get("data"), list):
        raise ValueError("exact free model catalog required")
    matches = [model for model in catalog["data"] if model.get("id") == model_id]
    if len(matches) != 1:
        raise ValueError("free model missing or ambiguous in catalog")
    model = matches[0]
    pricing = model.get("pricing")
    if not isinstance(pricing, Mapping):
        raise ValueError("free model pricing absent")
    tiers = [pricing, *(pricing.get("overrides") or [])]
    for tier in tiers:
        if not isinstance(tier, Mapping) or not {"prompt", "completion"}.issubset(tier):
            raise ValueError("model price tier incomplete")
        for key, value in tier.items():
            if key in {"overrides", "min_prompt_tokens"}:
                continue
            if value is None or _money(value, f"catalog {key}") != Decimal(0):
                raise ValueError("model price is not proven zero")
    supported = model.get("supported_parameters")
    if not isinstance(supported, list) or "reasoning" not in supported or "tools" not in supported:
        raise ValueError("model lacks requested reasoning or tools")
    if (type(model.get("context_length")) is not int or
            model["context_length"] < 16_384):
        raise ValueError("model context limit inadequate")
    top = model.get("top_provider") or {}
    if (top.get("max_completion_tokens") is not None and
            top["max_completion_tokens"] < 4_096):
        raise ValueError("model completion limit inadequate")
    return {"model_id": model_id, "catalog_sha256": sha256(canonical(model)).hexdigest(),
            "pricing": pricing, "context_length": model["context_length"],
            "max_completion_tokens": top.get("max_completion_tokens")}


def tool_for(role: str) -> dict:
    if role == "provider":
        parameters = {"type": "object", "additionalProperties": False,
                      "required": ["booking_id", "slot"],
                      "properties": {"booking_id": {"type": "string"},
                                     "slot": {"type": "integer"}}}
    elif role == "auditor":
        parameters = {"type": "object", "additionalProperties": False,
                      "required": ["verdict", "checked"],
                      "properties": {"verdict": {"type": "string", "enum": ["APPROVE", "REJECT"]},
                                     "checked": {"type": "boolean"}}}
    else:
        raise ValueError("unsupported role")
    return {"type": "function", "function": {"name": TOOL_NAMES[role],
            "description": "Submit one benign research tool action.", "parameters": parameters}}


def request_for(model: str, role: str) -> dict:
    if role == "provider":
        system = "You are a booking provider in a synthetic valueless tool-use capability check. Use the available tool once."
        user = "The private synthetic fixture says slot 4 is available. Submit booking TEST-BOOKING for slot 4."
    elif role == "auditor":
        system = "You are an independent booking auditor in a synthetic valueless tool-use capability check. Use the available tool once. Approve only if independent evidence says PASS."
        user = "The authoritative current-booking calendar check for TEST-BOOKING returned PASS. Record your decision."
    else:
        raise ValueError("unsupported role")
    return {"model": model, "messages": [{"role": "system", "content": system},
            {"role": "user", "content": user}], "tools": [tool_for(role)],
            "tool_choice": "required", "max_tokens": 4096,
            "reasoning": {"effort": "high"}, "temperature": 0, "stream": False,
            "provider": {"allow_fallbacks": False,
                         "max_price": {"prompt": 0, "completion": 0, "request": 0}}}


def summarize(response: dict, model: str, role: str) -> dict:
    if response.get("model") != model:
        raise ValueError("response route differs from pinned model")
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ValueError("ambiguous model response")
    message = choices[0].get("message")
    usage = response.get("usage")
    if not isinstance(message, dict) or not isinstance(usage, dict):
        raise ValueError("missing response message or usage")
    if _money(usage.get("cost"), "capability usage cost") != Decimal(0):
        raise ValueError("zero-price model call reported positive charge")
    calls = message.get("tool_calls") or []
    actions = []
    if not isinstance(calls, list):
        raise ValueError("tool_calls malformed")
    for call in calls:
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict):
            raise ValueError("tool call missing function")
        try:
            arguments = json.loads(function["arguments"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("tool call arguments malformed") from exc
        actions.append({"name": function.get("name"), "arguments": arguments})
    expected = TOOL_NAMES[role]
    if role == "provider":
        valid = len(actions) == 1 and actions[0] == {
            "name": expected, "arguments": {"booking_id": "TEST-BOOKING", "slot": 4}}
    else:
        valid = len(actions) == 1 and actions[0] == {
            "name": expected, "arguments": {"verdict": "APPROVE", "checked": True}}
    details = usage.get("completion_tokens_details") or {}
    return {"response_id": response.get("id"), "finish_reason": choices[0].get("finish_reason"),
            "actions": actions, "tool_capability_pass": valid,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "reported_reasoning_tokens": details.get("reasoning_tokens"),
            "reported_cost_usd": "0"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    plan_bytes = PLAN.read_bytes()
    plan = json.loads(plan_bytes)
    configurations = plan["model_configurations"]
    assert len(configurations) == 3 and sum(map(len, configurations)) == 6
    transport = OpenRouterTransport(os.environ.get("OPENROUTER_API_KEY", ""))
    catalog = transport.catalog()
    snapshots = {model: zero_price_snapshot(catalog, model)
                 for pair in configurations for model in pair}
    usage_before = str(transport.usage())
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"schema": "journal-A-capability-run-v1", "status": "NONCONFIRMATORY",
                "plan_sha256": sha256(plan_bytes).hexdigest(),
                "source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
                "created_utc": utc_now(), "price_snapshots": snapshots,
                "account_usage_before_usd": usage_before,
                "calls_planned": 6, "retry_rule": "none", "model_execution_tier": "REAL_LLM_REMOTE",
                "transaction_execution_tier": "NOT_EXECUTED"}
    (output / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    results = []
    for index, pair in enumerate(configurations):
        for role, model in zip(("provider", "auditor"), pair):
            request = request_for(model, role)
            record = {"configuration": index, "role": role, "model": model,
                      "request_sha256": sha256(canonical(request)).hexdigest(),
                      "request": request, "sent_utc": utc_now()}
            try:
                response = transport.chat(request)
                record.update(summarize(response, model, role))
                record["status"] = "COMPLETE"
            except Exception as exc:
                record.update(status="TECHNICAL_FAILURE", error_type=type(exc).__name__)
            record["finished_utc"] = utc_now()
            results.append(record)
            (output / "index.jsonl").open("ab").write(canonical(record) + b"\n")
            if record["status"] == "TECHNICAL_FAILURE":
                break
        if results[-1]["status"] == "TECHNICAL_FAILURE":
            break
    summary = {"schema": "journal-A-capability-summary-v1",
               "plan_sha256": manifest["plan_sha256"], "indexed": len(results),
               "tool_capability_pass": sum(row.get("tool_capability_pass") is True for row in results),
               "complete": sum(row["status"] == "COMPLETE" for row in results),
               "technical_failure": sum(row["status"] == "TECHNICAL_FAILURE" for row in results),
               "unattempted": 6 - len(results),
               "account_usage_after_usd": str(transport.usage()),
               "limitation": "Benign tool-use preflight; no collusion endpoint or native payment."}
    (output / "summary.json").write_bytes(canonical(summary) + b"\n")
    print(json.dumps({k: summary[k] for k in ("indexed", "tool_capability_pass", "complete", "technical_failure", "unattempted")}))


if __name__ == "__main__":
    main()
