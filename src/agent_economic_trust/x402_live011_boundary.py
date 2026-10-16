"""Prospective strict high-reasoning remote boundary for two x402 011 roles.

This module has no import-time model call. A future frozen one-row runner must
wrap the exact cached OpenRouter model APIs and save the observed request log.
"""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from typing import Any

from inspect_ai.model import ChatMessageSystem, ContentReasoning, GenerateConfig, get_model
from inspect_ai.model._openai import openai_chat_tools
from orbit.communication import current_identity

from .mpp005_boundary import RemoteBoundaryError, _safe_model_input_size
from .reporting import _agent_for_event
from .x402_live011_plan import (AUDITOR_CALLS, MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS,
                                PROVIDER_CALLS, X402LiveRow)


ROLE_LIMITS = {"provider": PROVIDER_CALLS, "auditor": AUDITOR_CALLS}
ROLE_TOOLS = {
    "provider": {"submit_audit_request", "channel_post", "channel_read", "channel_list"},
    "auditor": {"view_audit_intake", "pay_for_independent_check",
                "issue_invoice_verdict", "channel_post", "channel_read", "channel_list"},
}
TOOL_FIELDS = {
    "submit_audit_request": {"request": "string"},
    "view_audit_intake": {},
    "pay_for_independent_check": {"request_id": "string"},
    "issue_invoice_verdict": {"verdict": "string", "check_request_id": "string"},
    "channel_post": {"channel_id": "string", "message": "string"},
    "channel_read": {"channel_id": "string", "after_sequence": "integer|null",
                     "limit": "integer|null"},
    "channel_list": {"after_channel_id": "null|string"},
}


def _model_names(row: X402LiveRow) -> dict[str, str]:
    return {"provider": "openrouter/" + row.provider_model_id,
            "auditor": "openrouter/" + row.auditor_model_id}


def strict_tools(serialized: list[dict], role: str) -> str:
    """Check the actual OpenRouter strict schema and its role allowlist."""
    allowed = ROLE_TOOLS.get(role)
    if allowed is None or not isinstance(serialized, list):
        raise RemoteBoundaryError("invalid x402 011 role or tool schema")
    names = set()
    for item in serialized:
        fn = item.get("function")
        if item.get("type") != "function" or not isinstance(fn, dict):
            raise RemoteBoundaryError("malformed x402 011 function wrapper")
        name, schema = fn.get("name"), fn.get("parameters")
        if (name not in allowed or name in names or fn.get("strict") is not True
                or not isinstance(schema, dict) or schema.get("type") != "object"
                or schema.get("additionalProperties") is not False
                or not isinstance(schema.get("properties"), dict)
                or not isinstance(schema.get("required"), list)
                or len(schema["required"]) != len(set(schema["required"]))
                or set(schema["required"]) != set(schema["properties"])):
            raise RemoteBoundaryError("non-strict or unapproved x402 011 function")
        fields = {}
        for field, definition in schema["properties"].items():
            if not isinstance(definition, dict) or "default" in definition:
                raise RemoteBoundaryError("x402 011 tool argument default/type changed")
            if "anyOf" in definition:
                alternatives = definition["anyOf"]
                if (not isinstance(alternatives, list)
                        or any(not isinstance(a, dict) for a in alternatives)):
                    raise RemoteBoundaryError("x402 011 nullable tool argument differs")
                fields[field] = "|".join(sorted(a.get("type", "")
                                                 for a in alternatives))
            else:
                fields[field] = definition.get("type")
        if fields != TOOL_FIELDS[name]:
            raise RemoteBoundaryError("x402 011 role tool argument set differs")
        names.add(name)
    if names != allowed:
        raise RemoteBoundaryError("x402 011 role offered tool set differs")
    return sha256(json.dumps(serialized, sort_keys=True,
                             separators=(",", ":")).encode()).hexdigest()


def expected_serialized_tools(tools: list[Any]) -> list[dict]:
    serialized = openai_chat_tools(tools, exclude={
        "maxLength", "pattern", "minLength", "examples", "minimum", "maximum"})
    for entry in serialized:
        entry["function"]["strict"] = True
    return serialized


def offline_real_tool_schema_control() -> dict:
    """Serialize actual ORBIT/Inspect role tools without creating a model."""
    from inspect_ai.tool import ToolDef, ToolInfo
    from orbit.communication import configured_channel_tools
    from .x402_audit_retainer import (AUDITOR_WALLET, FEE_MINOR, SERVICE_ID,
                                      RetainerAssignment, digest, intake_body)
    from .x402_live011_plan import make_schedule
    from .x402_live011_task import (issue_invoice_verdict,
        pay_for_independent_check, submit_audit_request, view_audit_intake)

    row = make_schedule("00" * 32)[0]  # schema test vector, not a live assignment
    assignment = RetainerAssignment(row.episode_id, row.obligation_id,
                                    row.truth, row.payer_role)
    receipt = {"status": "AUDIT_INTAKE_PAID", "service_id": SERVICE_ID,
               "obligation_id": row.obligation_id, "payer_role": row.payer_role,
               "payee_role": "auditor", "payee": AUDITOR_WALLET,
               "amount_minor_units": FEE_MINOR,
               "transaction_hash": "0x" + "a" * 64,
               "body_sha256": digest(intake_body(assignment)),
               "transaction_tier": "NATIVE_LOCAL_PROTOCOL",
               "proves_invoice_quality": False, "audit_verdict": None}
    results = {}
    for role in ("provider", "auditor"):
        tools = ([submit_audit_request(role, row)] if role == "provider" else [
            view_audit_intake(role, row, receipt),
            pay_for_independent_check(role, row, lambda *_: {}),
            issue_invoice_verdict(role, row, lambda *_: {})])
        tools += configured_channel_tools(role)
        definitions = [item if isinstance(item, ToolDef) else ToolDef(item)
                       for item in tools]
        info = [ToolInfo(name=d.name, description=d.description,
                         parameters=d.parameters, options=d.options)
                for d in definitions]
        serialized = expected_serialized_tools(info)
        results[role] = {"tools": [d.name for d in definitions],
                         "strict_schema_sha256": strict_tools(serialized, role)}
    return {"status": "PASS", "paid_model_calls": 0,
            "roles": results, "synthetic_receipt_not_payment_evidence": True}


def models(row: X402LiveRow) -> dict[str, Any]:
    """Construct explicit role models with high reasoning and no SDK retry."""
    names = _model_names(row)
    config = GenerateConfig(reasoning_effort="high", reasoning_history="none",
                            max_tokens=MAX_OUTPUT_TOKENS, max_retries=0,
                            timeout=180, max_connections=1, cache=False)
    result = {}
    for role, name in names.items():
        model = get_model(name)
        if type(model.api).__name__ != "OpenRouterAPI" or str(model) != name:
            raise RemoteBoundaryError("x402 011 exact OpenRouter role model differs")
        model.api.client.max_retries = 0
        model.config = config.model_copy(deep=True)
        if get_model(name) is not model or model.api.client.max_retries != 0:
            raise RemoteBoundaryError("x402 011 role model is not the bounded cached route")
        result[role] = model
    if result["provider"] is result["auditor"]:
        raise RemoteBoundaryError("provider and auditor model identities conflated")
    return result


def guard_model_apis(role_models: dict[str, Any], row: X402LiveRow) -> list[dict]:
    """Save one item per attempted request, including calls that raise."""
    expected = _model_names(row)
    if {role: str(model) for role, model in role_models.items()} != expected:
        raise RemoteBoundaryError("x402 011 role models differ from assignment")
    observed: list[dict] = []
    for role, model in role_models.items():
        original = model.api.generate

        async def bounded(input: Any, tools: Any, tool_choice: Any, config: Any,
                          *, _original=original, _model=model,
                          _role=role) -> Any:
            identity = current_identity()
            actor = identity.agent_id if identity is not None else None
            size = _safe_model_input_size(input, tools)
            schema_sha = strict_tools(_model.api.tools_to_openai(tools), actor)
            has_reasoning_history = any(isinstance(part, ContentReasoning)
                                        for message in input for part in
                                        (message.content if isinstance(message.content, list)
                                         else []))
            if (actor != _role or str(_model) != expected[actor]
                    or len(observed) >= PROVIDER_CALLS + AUDITOR_CALLS
                    or sum(item["role"] == actor for item in observed)
                       >= ROLE_LIMITS[actor]
                    or size > MAX_INPUT_BYTES or has_reasoning_history
                    or _model.api.client.max_retries != 0
                    or config.reasoning_effort != "high"
                    or config.reasoning_history != "none"
                    or config.max_tokens != MAX_OUTPUT_TOKENS
                    or config.max_retries != 0):
                raise RemoteBoundaryError("x402 011 request exceeds role or high-reasoning cap")
            item = {"call_index": len(observed) + 1, "role": actor,
                    "model": expected[actor], "serialized_input_bytes": size,
                    "tool_schema_sha256": schema_sha,
                    "provider_api_invoked": True,
                    "network_forwarding": "UNOBSERVED",
                    "http_client_max_retries": 0, "completed": False}
            observed.append(item)
            result = await _original(input, tools, tool_choice, config)
            item["completed"] = True
            return result
        model.api.generate = bounded
    return observed


def verify_raw_model_boundary(log: Any, observed: list[dict],
                              row: X402LiveRow) -> dict:
    expected = _model_names(row)
    if (log.status != "success" or log.eval.model != expected["provider"]
            or len(log.samples or []) != 1 or log.samples[0].error):
        raise RemoteBoundaryError("x402 011 Inspect sample or root model differs")
    sample = log.samples[0]
    if any(event.event == "tool" and event.error for event in sample.events):
        raise RemoteBoundaryError("x402 011 saved log contains failed tool call")
    agents = sample.metadata["experiment"]["setup"]["agents"]
    if {a["name"]: a["model"] for a in agents} != expected:
        raise RemoteBoundaryError("x402 011 saved ORBIT role model differs")
    if (f"{row.truth.upper()}" not in agents[0]["system_prompt"]
            or "Private certified fact" in agents[1]["system_prompt"]
            or "buyer-only purchase order" not in agents[1]["system_prompt"]):
        raise RemoteBoundaryError("x402 011 role prompts or truth isolation differ")
    events = [e for e in sample.events if e.event == "model"]
    if not events or len(events) != len(observed) or len(events) > 10:
        raise RemoteBoundaryError("x402 011 request/event count differs")
    counts = Counter()
    for index, (event, actual) in enumerate(zip(events, observed, strict=True)):
        actor = _agent_for_event(event, sample)
        if actor not in ROLE_LIMITS:
            raise RemoteBoundaryError("x402 011 model event lacks role identity")
        counts[actor] += 1
        serialized = expected_serialized_tools(event.tools)
        schema_sha = strict_tools(serialized, actor)
        config = event.config
        system = "\n".join(message.text for message in event.input
                           if isinstance(message, ChatMessageSystem))
        if (actor == "auditor" and ("Private certified fact" in system
                                     or "report is BAD" in system
                                     or "report is GOOD" in system)):
            raise RemoteBoundaryError("provider private truth entered auditor system prompt")
        wanted = {"call_index": index + 1, "role": actor,
                  "model": expected[actor],
                  "serialized_input_bytes": _safe_model_input_size(event.input,
                                                                    event.tools),
                  "tool_schema_sha256": schema_sha,
                  "provider_api_invoked": True,
                  "network_forwarding": "UNOBSERVED",
                  "http_client_max_retries": 0, "completed": True}
        if (actual != wanted or counts[actor] > ROLE_LIMITS[actor]
                or actual["serialized_input_bytes"] > MAX_INPUT_BYTES
                or event.model != expected[actor] or event.error
                or event.cache is not None or event.retries not in (None, 0)
                or config is None or config.reasoning_effort != "high"
                or config.reasoning_history != "none"
                or config.max_tokens != MAX_OUTPUT_TOKENS
                or config.max_retries != 0):
            raise RemoteBoundaryError("x402 011 raw request or high-reasoning evidence differs")
    if set(counts) != {"provider", "auditor"}:
        raise RemoteBoundaryError("both x402 011 agents require forwarded requests")
    return {"provider_calls": counts["provider"],
            "auditor_calls": counts["auditor"],
            "reasoning_effort_by_role": {"provider": "high", "auditor": "high"}}
