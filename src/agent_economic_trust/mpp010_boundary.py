"""Raw role/model boundary and verified compatibility replay for MPP010."""
from __future__ import annotations

import asyncio
from collections import Counter
from copy import deepcopy
from typing import Any

from inspect_ai.model import ChatMessageSystem, ContentReasoning
from inspect_ai.model._openai import openai_chat_tools
from orbit.communication import current_identity

from .mpp005_boundary import (_safe_model_input_size, RemoteBoundaryError,
    account_usage_delta_usd, account_usage_usd, assert_no_key, file_sha, write_json)
from .mpp010_plan import (AUDITOR_CALLS, MAX_CALLS_PER_EPISODE, MAX_INPUT_BYTES,
    MAX_OUTPUT_TOKENS, PROVIDER_CALLS, digest)
from .mpp010_native_service import inspect_native_service_log
from .mpp010_orbit import AUDITOR_TOOLS, PROVIDER_TOOLS
from .open_mpp_meeting import commitment
from .mpp010_task import PROVIDER_NOTICE
from .reporting import _agent_for_event


REQUEST_TIMEOUT_SECONDS = 180
ROLE_LIMITS = {"provider": PROVIDER_CALLS, "auditor": AUDITOR_CALLS}
ROLE_TOOLS = {"provider": PROVIDER_TOOLS, "auditor": AUDITOR_TOOLS}


def verify_strict_tool_schemas(serialized: list[dict], actor: str) -> str:
    """Reject invalid strict OpenAI-compatible schemas before model inference.

    This receives the exact objects returned by the active OpenRouter API's
    tools_to_openai conversion. Optional Python defaults are invalid here:
    strict tool schemas require every declared property in `required`.
    """
    expected = ROLE_TOOLS.get(actor)
    if expected is None or not isinstance(serialized, list):
        raise RemoteBoundaryError("MPP010 invalid tool role or serialized tool set")
    seen = set()
    for entry in serialized:
        if entry.get("type") != "function" or not isinstance(entry.get("function"), dict):
            raise RemoteBoundaryError("MPP010 malformed strict function wrapper")
        function = entry["function"]
        name = function.get("name")
        schema = function.get("parameters")
        if (name not in expected or name in seen or function.get("strict") is not True
                or not isinstance(schema, dict) or schema.get("type") != "object"
                or schema.get("additionalProperties") is not False
                or not isinstance(schema.get("properties"), dict)
                or not isinstance(schema.get("required"), list)):
            raise RemoteBoundaryError("MPP010 invalid strict function schema")
        seen.add(name)
        properties = schema["properties"]
        required = schema["required"]
        if (len(required) != len(set(required)) or set(required) != set(properties)
                or any(not isinstance(prop, dict) or "default" in prop
                       or prop.get("type") not in {"string", "integer"}
                       for prop in properties.values())):
            raise RemoteBoundaryError("MPP010 strict tool properties are not all required")
        expected_properties = {
            "market_view": {}, "market_accept": {}, "market_check": {},
            "select_mpp_flow": {"flow": "string"},
            "market_propose": {"fee_atomic": "integer", "acceptance_bonus_atomic": "integer",
                               "message": "string"},
            "market_decide": {"verdict": "string", "message": "string"},
        }[name]
        if {key: value["type"] for key, value in properties.items()} != expected_properties:
            raise RemoteBoundaryError("MPP010 strict tool fields changed")
    if seen != expected:
        raise RemoteBoundaryError("MPP010 offered tool set differs from assigned role")
    return digest(serialized)


def expected_serialized_tools(tools: list[Any]) -> list[dict]:
    """Mirror Inspect's OpenRouter conversion for archived ToolInfo events."""
    serialized = openai_chat_tools(tools, exclude={
        "maxLength", "pattern", "minLength", "examples", "minimum", "maximum"})
    for entry in serialized:
        entry["function"]["strict"] = True
    return serialized


def _expected_models(row) -> dict[str, str]:
    return {"provider": "openrouter/" + row.provider_model_id,
            "auditor": "openrouter/" + row.auditor_model_id}


def verify_provider_notice_exposure(sample, event, actor: str, expected_notice: str) -> None:
    """Allow provider-authored disclosure while excluding controller prompt leaks."""
    systems = "\n".join(message.text for message in event.input
                        if isinstance(message, ChatMessageSystem))
    if ((expected_notice in systems) != (actor == "provider")
            or actor == "auditor" and any(notice in systems for notice in PROVIDER_NOTICE.values())):
        raise RemoteBoundaryError("MPP010 provider notice system-prompt isolation differs")
    if actor == "auditor" and expected_notice in "\n".join(message.text for message in event.input):
        position = next((i for i, prior in enumerate(sample.events) if prior is event), None)
        if position is None or not any(
                prior.event == "tool" and prior.function == "market_propose" and not prior.error
                and _agent_for_event(prior, sample) == "provider"
                and expected_notice in prior.arguments.get("message", "")
                for prior in sample.events[:position]):
            raise RemoteBoundaryError("MPP010 auditor notice exposure lacks prior provider tool disclosure")


def guard_model_apis(models: dict[str, Any], row) -> list[dict]:
    """Wrap each unique cached model before ORBIT resolves AgentSpec.model."""
    expected = _expected_models(row)
    if {role: str(models[role]) for role in ROLE_LIMITS} != expected:
        raise RemoteBoundaryError("cached provider/auditor model differs from assignment")
    observed: list[dict] = []
    wrapped: set[int] = set()
    model_apis = {str(model): model.api for model in models.values()}
    for role, model in models.items():
        if id(model) in wrapped:
            continue
        wrapped.add(id(model))
        original = model.api.generate

        async def bounded(input: Any, tools: Any, tool_choice: Any, config: Any,
                          *, _original=original, _model_name=str(model)) -> Any:
            identity = current_identity()
            actor = identity.agent_id if identity is not None else None
            size = _safe_model_input_size(input, tools)
            serialized_tools = model_apis[_model_name].tools_to_openai(tools)
            tool_schemas_sha256 = verify_strict_tool_schemas(serialized_tools, actor)
            reasoning_history = any(isinstance(part, ContentReasoning)
                                    for message in input for part in
                                    (message.content if isinstance(message.content, list) else []))
            if (actor not in ROLE_LIMITS or expected[actor] != _model_name
                    or model_apis[_model_name].client.max_retries != 0
                    or len(observed) >= MAX_CALLS_PER_EPISODE
                    or sum(item["role"] == actor for item in observed) >= ROLE_LIMITS[actor]
                    or size > MAX_INPUT_BYTES or reasoning_history
                    or config.reasoning_effort != "high" or config.reasoning_history != "none"
                    or config.max_tokens != MAX_OUTPUT_TOKENS or config.max_retries != 0):
                raise RemoteBoundaryError("MPP010 actual provider request violates assigned role or cap")
            item = {"call_index": len(observed) + 1, "role": actor, "model": _model_name,
                    "serialized_input_bytes": size, "tool_schemas_sha256": tool_schemas_sha256,
                    "provider_api_invoked": True,
                    "network_forwarding": "UNOBSERVED", "http_client_max_retries": 0,
                    "completed": False}
            observed.append(item)
            result = await _original(input, tools, tool_choice, config)
            item["completed"] = True
            return result
        model.api.generate = bounded
    return observed


def verify_raw_model_boundary(log: Any, observed: list[dict], row) -> dict:
    """Check every raw model event before replacing any ID for legacy replay."""
    expected = _expected_models(row)
    if (log.status != "success" or log.eval.model != expected["provider"]
            or len(log.samples or []) != 1 or log.samples[0].error):
        raise RemoteBoundaryError("MPP010 raw Inspect sample/model differs")
    sample = log.samples[0]
    if any(event.event == "tool" and event.error for event in sample.events):
        raise RemoteBoundaryError("MPP010 failed tool event; preserve stopped row and halt")
    agents = sample.metadata["experiment"]["setup"]["agents"]
    if {a["name"]: a["model"] for a in agents} != expected:
        raise RemoteBoundaryError("MPP010 raw ORBIT role-model assignment differs")
    expected_notice = PROVIDER_NOTICE[row.truth]
    if (expected_notice not in agents[0]["system_prompt"]
            or not agents[0]["system_prompt"].endswith(
                "Always supply a message string in market_propose; use an empty string if you have no message.")
            or not agents[1]["system_prompt"].endswith(
                "Always supply a message string in market_decide; use an empty string if you have no message.")
            or any(notice in agents[1]["system_prompt"] for notice in PROVIDER_NOTICE.values())):
        raise RemoteBoundaryError("MPP010 provider notice source or auditor isolation differs")
    events = [event for event in sample.events if event.event == "model"]
    if not events or len(events) != len(observed) or len(events) > MAX_CALLS_PER_EPISODE:
        raise RemoteBoundaryError("MPP010 model events or actual request count differ")
    counts = Counter()
    for index, (event, actual) in enumerate(zip(events, observed, strict=True)):
        actor = _agent_for_event(event, sample)
        counts[actor] += 1
        config = event.config
        verify_provider_notice_exposure(sample, event, actor, expected_notice)
        schema_digest = verify_strict_tool_schemas(expected_serialized_tools(event.tools), actor)
        if (actor not in ROLE_LIMITS or counts[actor] > ROLE_LIMITS[actor]
                or event.model != expected[actor] or event.error or event.cache is not None
                or event.retries not in (None, 0) or config is None
                or config.reasoning_effort != "high" or config.reasoning_history != "none"
                or config.max_tokens != MAX_OUTPUT_TOKENS or config.max_retries != 0
                or actual != {"call_index": index + 1, "role": actor,
                    "model": expected[actor],
                    "serialized_input_bytes": _safe_model_input_size(event.input, event.tools),
                    "tool_schemas_sha256": schema_digest,
                    "provider_api_invoked": True, "network_forwarding": "UNOBSERVED",
                    "http_client_max_retries": 0, "completed": True}
                or actual["serialized_input_bytes"] > MAX_INPUT_BYTES
                or any(isinstance(part, ContentReasoning) for message in event.input
                       for part in (message.content if isinstance(message.content, list) else []))):
            raise RemoteBoundaryError("MPP010 raw event violates role, model or reasoning boundary")
    if not all(counts[role] for role in ROLE_LIMITS):
        raise RemoteBoundaryError("MPP010 both roles require real model events")
    return {"provider_calls": counts["provider"], "auditor_calls": counts["auditor"],
            "raw_model_events_sha256": digest([event.model_dump(mode="json") for event in events])}


def normalize_for_native(log: Any, row) -> tuple[Any, str]:
    """Make an in-memory compatibility copy only after raw role verification.

    The MPP005 native verifier is exact about action order/receipts but expects
    one event.model string. Its only compatibility change here is that string.
    The original .eval archive remains untouched and is the sole saved log.
    """
    normalized = log.model_copy(deep=True)
    default = _expected_models(row)["provider"]
    for event in normalized.samples[0].events:
        if event.event == "model":
            event.model = default
    return normalized, digest(normalized.model_dump(mode="json"))


def inspect_mixed_native_log(log: Any, *, service: Any, row: Any,
                             observed: list[dict]) -> tuple[dict, dict]:
    raw = verify_raw_model_boundary(log, observed, row)
    normalized, normalized_sha = normalize_for_native(log, row)
    decision = asyncio.run(inspect_native_service_log(normalized, service=service,
        quality=row.truth, condition="OPEN", expected_model=_expected_models(row)["provider"],
        require_real_model=True))
    provenance = {"provider": row.provider_model_id, "auditor": row.auditor_model_id,
                  "raw_model_events_sha256": raw["raw_model_events_sha256"],
                  "normalization": "IN_MEMORY_MODEL_ID_ONLY_AFTER_RAW_ROLE_VERIFICATION",
                  "normalized_log_sha256": normalized_sha}
    decision = {key: value for key, value in decision.items() if key != "decision_sha256"}
    decision["model_provenance"] = {
        "expected_models_by_role": _expected_models(row),
        "raw_model_events_sha256": raw["raw_model_events_sha256"],
        "raw_actions_audited": True, "reasoning_effort": "high", "reasoning_effort_by_role": {
            "provider": "high", "auditor": "high"}}
    decision["decision_sha256"] = commitment(decision)
    return decision, {**raw, **provenance}
