"""Pure proposed remote-request boundary for the unfrozen BILATERAL030 plan.

The future paid runner must attach this check directly to both cached model
APIs and independently verify the saved raw ModelCalls. This module alone does
not attach an API wrapper or authorize a hosted request.
"""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence

from inspect_ai.model import (ChatMessageAssistant, ChatMessageSystem,
                              ChatMessageTool, ChatMessageUser,
                              ContentReasoning, GenerateConfig)

from .bilateral030_plan import (AUDITOR_CALLS, MAX_INPUT_BYTES,
                                MAX_OUTPUT_TOKENS, PROVIDER_CALLS, ROLE_STEPS,
                                SOL, SONNET, Bilateral030Row, validate_row)
from .mpp005_boundary import RemoteBoundaryError, _safe_model_input_size


ROLE_LIMITS = {"provider": PROVIDER_CALLS, "auditor": AUDITOR_CALLS}
PROVIDER_TOOLS = {"choose_claim_offer", "post_auditor_note"}
AUDITOR_TOOLS = {"view_claim_inbox", "buy_buyer_check", "decide_early"}
ORBIT_CONTINUATION = "Please continue with your next action."
_PRIVATE_ORACLE = re.compile(
    r"\b(?:BAD|GOOD|FAIL|PASS)\b|(?:purchase[ _-]?order|credit[ _-]?note)"
    r"\s*(?:is|=|:)\s*(?:300|350|400|50)\b|"
    r"\b(?:private certification|protected oracle|controller[- ]private)\b",
    re.I,
)


def expected_routes(row: Bilateral030Row) -> dict[str, str]:
    validate_row(row)
    if row.provider_model_id == row.auditor_model_id:
        raise RemoteBoundaryError("BILATERAL030 two roles share a route")
    return {"provider": "openrouter/" + row.provider_model_id,
            "auditor": "openrouter/" + row.auditor_model_id}


def validate_agent_specs(row: Bilateral030Row,
                         experiment: Mapping[str, Any]) -> dict[str, str]:
    """Inspect the explicit ORBIT per-agent routes before any eval call.

    Inspect's top-level ``eval(model=...)`` cannot replace an AgentSpec route.
    The future runner must call this on the actual task metadata and separately
    assert the cached provider/auditor model objects are distinct.
    """
    routes = expected_routes(row)
    try:
        agents = experiment["setup"]["agents"]
        actual = {agent["name"]: agent["model"] for agent in agents}
    except (KeyError, TypeError) as exc:
        raise RemoteBoundaryError("BILATERAL030 ORBIT agent routes absent") from exc
    if (not isinstance(agents, list) or len(agents) != 2
            or [agent["name"] for agent in agents] != ["provider", "auditor"]
            or actual != routes):
        raise RemoteBoundaryError("BILATERAL030 explicit ORBIT AgentSpec routes differ")
    return routes


def _tool_json(tools: Sequence[Any]) -> bytes:
    data = [tool.model_dump(mode="json") if hasattr(tool, "model_dump") else tool
            for tool in tools]
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str).encode()


def _trusted_frame(input_messages: Sequence[Any], *, role: str,
                   expected_system: str, expected_user: str) -> None:
    if (len(input_messages) < 2
            or not isinstance(input_messages[0], ChatMessageSystem)
            or not isinstance(input_messages[1], ChatMessageUser)
            or input_messages[0].text != expected_system
            or input_messages[1].text != expected_user):
        raise RemoteBoundaryError("BILATERAL030 trusted prompt frame differs")
    if (sum(isinstance(msg, ChatMessageSystem) for msg in input_messages) != 1
            or any((msg.metadata or {}).get("orbit_communication_delivery") is not None
                   for msg in input_messages)):
        raise RemoteBoundaryError("BILATERAL030 untrusted delivery entered trusted prompt")
    if role == "auditor" and _PRIVATE_ORACLE.search(
            expected_system + "\n" + expected_user):
        raise RemoteBoundaryError("BILATERAL030 private truth reached auditor trusted prompt")
    allowed = PROVIDER_TOOLS if role == "provider" else AUDITOR_TOOLS
    for index, message in enumerate(input_messages[2:], start=2):
        # ORBIT turn_react emits this fixed continuation after tool feedback
        # when the same actor resumes in another scheduled activation.
        if (isinstance(message, ChatMessageUser)
                and message.text == ORBIT_CONTINUATION
                and isinstance(input_messages[index - 1], ChatMessageTool)):
            continue
        if isinstance(message, ChatMessageAssistant):
            continue
        if (not isinstance(message, ChatMessageTool)
                or message.function not in allowed or message.error):
            raise RemoteBoundaryError("BILATERAL030 cross-role or failed tool feedback")


def validate_request(row: Bilateral030Row, *, role: str, model_route: str,
                     input_messages: Sequence[Any], tools: Sequence[Any],
                     config: GenerateConfig, body: Mapping[str, Any],
                     http_client_max_retries: int, observed: Sequence[Mapping[str, Any]],
                     expected_system: str, expected_user: str) -> dict[str, Any]:
    """Validate one prospective request without forwarding it.

    All values must be taken from the actual model API boundary in a future
    implementation. A caller-supplied stand-in cannot prove a real request.
    """
    routes = expected_routes(row)
    if role not in ROLE_LIMITS or model_route != routes[role]:
        raise RemoteBoundaryError("BILATERAL030 assigned role route differs")
    index = len(observed)
    if (index >= len(ROLE_STEPS)
            or [item.get("role") for item in observed] != list(ROLE_STEPS[:index])
            or ROLE_STEPS[index] != role
            or sum(item["role"] == role for item in observed) >= ROLE_LIMITS[role]):
        raise RemoteBoundaryError("BILATERAL030 five-call role schedule exceeded")
    _trusted_frame(input_messages, role=role,
                   expected_system=expected_system, expected_user=expected_user)
    if (model_route == "openrouter/" + SONNET
            and isinstance(input_messages[-1], ChatMessageAssistant)):
        raise RemoteBoundaryError("BILATERAL030 Sonnet assistant-only prefill prevented")
    if (any(isinstance(part, ContentReasoning)
            for message in input_messages for part in
            (message.content if isinstance(message.content, list) else []))):
        raise RemoteBoundaryError("BILATERAL030 reasoning history entered later request")
    tool_names = {getattr(tool, "name", None) for tool in tools}
    allowed = PROVIDER_TOOLS if role == "provider" else AUDITOR_TOOLS
    if (tool_names != allowed or None in tool_names
            or len(tool_names) != len(tools)):
        raise RemoteBoundaryError("BILATERAL030 incomplete, unapproved or duplicate offered tool")
    size = _safe_model_input_size(input_messages, tools)
    if size > MAX_INPUT_BYTES:
        raise RemoteBoundaryError("BILATERAL030 serialized input byte cap exceeded")
    if (type(http_client_max_retries) is not int or http_client_max_retries != 0
            or config.reasoning_effort != "high"
            or config.reasoning_history != "none"
            or config.max_tokens != MAX_OUTPUT_TOKENS
            or config.max_retries != 0):
        raise RemoteBoundaryError("BILATERAL030 retry, reasoning or output cap differs")
    model_id = routes[role].removeprefix("openrouter/")
    cap_key = "max_completion_tokens" if model_id == SOL else "max_tokens"
    wrong_cap_key = "max_tokens" if cap_key == "max_completion_tokens" else "max_completion_tokens"
    if (body.get("model") != model_id
            or body.get(cap_key) != MAX_OUTPUT_TOKENS
            or wrong_cap_key in body
            or body.get("extra_body", {}).get("reasoning") != {"effort": "high"}):
        raise RemoteBoundaryError("BILATERAL030 outbound OpenRouter body drops route, effort or cap")
    return {"call_index": index + 1, "role": role, "model": model_route,
            "serialized_input_bytes": size,
            "tool_info_sha256": sha256(_tool_json(tools)).hexdigest(),
            "reasoning_effort_requested": "high",
            "reasoning_history": "none",
            "max_output_tokens_requested": MAX_OUTPUT_TOKENS,
            "http_client_max_retries": 0,
            "source_only_no_network_forwarding": True}
