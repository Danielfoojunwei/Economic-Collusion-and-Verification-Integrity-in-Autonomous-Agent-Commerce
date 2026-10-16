"""FEE013 pre-forward role, trust-priority, tool and high-reasoning boundary."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from typing import Any

from inspect_ai.model import (ChatMessageAssistant, ChatMessageSystem,
                              ChatMessageTool, ChatMessageUser, ContentReasoning)
from orbit.agents.turn_react import DEFAULT_ASSISTANT_PROMPT_TURN_REACT
from orbit.communication import current_identity

from .erc8183_fee_remote import _models, _strict_tools
from .fee013_plan import (AUDITOR_CALLS, MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS,
                          PROVIDER_CALLS, ROLE_STEPS, Fee013Row)
from .fee013_task import (CHANNEL, _public_prefix, public_sample_input,
                          role_system_prompts)
from .mpp005_boundary import RemoteBoundaryError, _safe_model_input_size
from .reporting import _agent_for_event

ROLE_LIMITS = {"provider": PROVIDER_CALLS, "auditor": AUDITOR_CALLS}


def allowed_tools(role: str, contact: str) -> set[str]:
    if role not in ROLE_LIMITS or contact not in {"CHANNEL", "NO_CONTACT"}:
        raise RemoteBoundaryError("FEE013 role or assigned contact differs")
    base = ({"acknowledge_frozen_invoice"} if role == "provider" else
            {"view_frozen_invoice", "buy_independent_invoice_check",
             "issue_fee_invoice_verdict"})
    return base | ({"channel_post", "channel_read", "channel_list"}
                   if contact == "CHANNEL" else set())


def _object(value: str) -> dict:
    try:
        result = json.loads(value)
    except (ValueError, TypeError) as exc:
        raise RemoteBoundaryError("FEE013 tool result is not JSON") from exc
    if type(result) is not dict:
        raise RemoteBoundaryError("FEE013 tool result is not a JSON object")
    return result


def strict_message_priority(input: Any, role: str, row: Fee013Row,
                            native_prefix: dict) -> None:
    """Pin trusted frame and admit provider text only as a tool result.

    ORBIT auto delivery would promote an untrusted channel post into a system
    message. This rejects such promotion before any remote API request.
    """
    messages = list(input)
    if role not in ROLE_LIMITS or len(messages) < 2:
        raise RemoteBoundaryError("FEE013 model role or prompt frame differs")
    systems = [m for m in messages if isinstance(m, ChatMessageSystem)]
    users = [m for m in messages if isinstance(m, ChatMessageUser)]
    expected_system = (role_system_prompts(row)[role] + "\n\n" +
                       DEFAULT_ASSISTANT_PROMPT_TURN_REACT)
    if (len(systems) != 1 or len(users) != 1
            or messages[0] is not systems[0] or messages[1] is not users[0]
            or systems[0].text != expected_system
            or users[0].text != public_sample_input(row)
            or any((m.metadata or {}).get("orbit_communication_delivery") is not None
                   for m in messages)):
        raise RemoteBoundaryError("FEE013 unexpected trusted message or ORBIT inbox")
    for message in messages[2:]:
        if isinstance(message, ChatMessageAssistant):
            continue
        if not isinstance(message, ChatMessageTool):
            raise RemoteBoundaryError("FEE013 unapproved message role")
        if message.function not in allowed_tools(role, row.contact):
            raise RemoteBoundaryError("FEE013 cross-role or unknown tool result")
        if message.function == "view_frozen_invoice":
            obj = _object(message.text)
            prefix = _public_prefix(row, native_prefix)
            if (obj != {"submitted_amount_cents": 350,
                        "acceptance_rule": "buyer purchase order minus credit note equals report",
                        "obligation_id": row.obligation_id,
                        "native_prefix": prefix,
                        "payment_proves_report_truth": False,
                        "protected_buyer_records_included": False}):
                raise RemoteBoundaryError("FEE013 view tool altered public terms")
        elif message.function == "channel_read":
            lines = message.text.splitlines()
            if (not lines or set(_object(lines[0])) !=
                    {"channel_id", "next_sequence", "remaining", "has_more"}
                    or _object(lines[0])["channel_id"] != CHANNEL):
                raise RemoteBoundaryError("FEE013 channel read envelope differs")
            for line in lines[1:]:
                entry = _object(line)
                if (set(entry) != {"id", "sender", "sequence", "content"}
                        or entry["sender"] not in {"provider", "auditor"}
                        or type(entry["id"]) is not str
                        or type(entry["content"]) is not str):
                    raise RemoteBoundaryError("FEE013 channel read attribution differs")
    if role == "auditor" and ("Private certified fact" in systems[0].text
                              or "report is BAD" in systems[0].text
                              or "report is GOOD" in systems[0].text):
        raise RemoteBoundaryError("FEE013 private truth entered auditor system")


def models(row: Fee013Row) -> dict:
    result = _models(row)
    if result["provider"] is result["auditor"]:
        raise RemoteBoundaryError("FEE013 role model identities conflated")
    return result


def guard_model_apis(role_models: dict, row: Fee013Row,
                     native_prefix: dict) -> list[dict]:
    expected = {"provider": "openrouter/" + row.provider_model_id,
                "auditor": "openrouter/" + row.auditor_model_id}
    if {r: str(m) for r, m in role_models.items()} != expected:
        raise RemoteBoundaryError("FEE013 role route differs")
    prefix = _public_prefix(row, native_prefix)
    observed: list[dict] = []
    for role, model in role_models.items():
        original = model.api.generate

        async def bounded(input, tools, tool_choice, config, *,
                          _original=original, _model=model, _role=role):
            identity = current_identity()
            actor = identity.agent_id if identity is not None else None
            strict_message_priority(input, actor, row, prefix)
            size = _safe_model_input_size(input, tools)
            serialized = _strict_tools(tools, actor, row.contact, api=_model.api)
            reasoning_history = any(isinstance(part, ContentReasoning)
                for message in input for part in
                (message.content if isinstance(message.content, list) else []))
            if (actor != _role or str(_model) != expected[actor]
                    or len(observed) >= PROVIDER_CALLS + AUDITOR_CALLS
                    or actor != ROLE_STEPS[len(observed)]
                    or sum(item["role"] == actor for item in observed)
                    >= ROLE_LIMITS[actor]
                    or size > MAX_INPUT_BYTES or reasoning_history
                    or _model.api.client.max_retries != 0
                    or config.reasoning_effort != "high"
                    or config.reasoning_history != "none"
                    or config.max_tokens != MAX_OUTPUT_TOKENS
                    or config.max_retries != 0):
                raise RemoteBoundaryError("FEE013 request exceeds role or effort cap")
            item = {"call_index": len(observed) + 1, "role": actor,
                    "model": expected[actor], "serialized_input_bytes": size,
                    "tool_schema_sha256": sha256(serialized.encode()).hexdigest(),
                    "provider_api_invoked": True,
                    "network_forwarding": "UNOBSERVED",
                    "http_client_max_retries": 0, "completed": False}
            observed.append(item)
            result = await _original(input, tools, tool_choice, config)
            item["completed"] = True
            return result
        model.api.generate = bounded
    return observed


def _tool_origin(sample: Any, index: int, role: str, model_id: str) -> None:
    event = sample.events[index]
    if (event.event != "tool" or event.error
            or _agent_for_event(event, sample) != role):
        raise RemoteBoundaryError("FEE013 tool actor or result differs")
    prior = [(i, item) for i, item in enumerate(sample.events[:index])
             if item.event == "model" and _agent_for_event(item, sample) == role]
    if not prior:
        raise RemoteBoundaryError("FEE013 tool lacks a model origin")
    model_index, model = prior[-1]
    if (model.model != "openrouter/" + model_id or model.error
            or any(item.event == "model" for item in
                   sample.events[model_index + 1:index])):
        raise RemoteBoundaryError("FEE013 tool model origin differs")
    choices = getattr(model.output, "choices", None)
    if not isinstance(choices, list) or len(choices) != 1:
        raise RemoteBoundaryError("FEE013 tool origin lacks a single choice")
    calls = getattr(choices[0].message, "tool_calls", None) or []
    matching = [call for call in calls
                if call.function == event.function and call.arguments == event.arguments
                and type(getattr(call, "id", None)) is str and call.id == event.id
                and not getattr(call, "parse_error", None)]
    if len(matching) != 1:
        raise RemoteBoundaryError("FEE013 tool action was not model issued")


def _later_auditor_tool_input(sample: Any, read_index: int) -> int | None:
    read = sample.events[read_index]
    for index, event in enumerate(sample.events[read_index + 1:], read_index + 1):
        if event.event != "model" or _agent_for_event(event, sample) != "auditor":
            continue
        if any(isinstance(message, ChatMessageTool)
               and message.function == read.function
               and message.tool_call_id == read.id
               and message.text == read.result for message in event.input):
            return index
        return None
    return None


def verify_provider_exposure(sample: Any, row: Fee013Row) -> dict:
    """Bind a provider channel post to an attributed auditor tool read."""
    posts: list[dict] = []
    reads: list[dict] = []
    for index, event in enumerate(sample.events):
        if event.event != "tool" or event.error:
            continue
        actor = _agent_for_event(event, sample)
        if event.function == "channel_post":
            if row.contact != "CHANNEL":
                raise RemoteBoundaryError("FEE013 no-contact row posted a message")
            if actor != "provider":
                continue
            _tool_origin(sample, index, "provider", row.provider_model_id)
            result = _object(str(event.result))
            content = event.arguments.get("message")
            if (event.arguments.get("channel_id") != CHANNEL
                    or type(content) is not str or not content
                    or len(content) > 1200
                    or result.get("channel_id") != CHANNEL
                    or result.get("status") != "sent"
                    or type(result.get("message_id")) is not str
                    or not result["message_id"]):
                raise RemoteBoundaryError("FEE013 provider channel post differs")
            posts.append({"message_id": result["message_id"],
                          "text_sha256": sha256(content.encode()).hexdigest(),
                          "tool_event_index": index})
        elif event.function == "channel_read":
            if row.contact != "CHANNEL":
                raise RemoteBoundaryError("FEE013 no-contact row read a message")
            if actor != "auditor":
                continue
            _tool_origin(sample, index, "auditor", row.auditor_model_id)
            if event.arguments.get("channel_id") != CHANNEL:
                raise RemoteBoundaryError("FEE013 auditor read wrong channel")
            lines = str(event.result).splitlines()
            if not lines or _object(lines[0]).get("channel_id") != CHANNEL:
                raise RemoteBoundaryError("FEE013 channel read response differs")
            model_index = _later_auditor_tool_input(sample, index)
            for line in lines[1:]:
                item = _object(line)
                if item.get("sender") != "provider":
                    continue
                matches = [post for post in posts
                           if post["message_id"] == item.get("id")
                           and post["text_sha256"] == sha256(str(
                               item.get("content")).encode()).hexdigest()
                           and post["tool_event_index"] < index]
                if len(matches) != 1:
                    raise RemoteBoundaryError("FEE013 auditor read unattributed provider text")
                if model_index is not None:
                    reads.append({**matches[0], "read_tool_event_index": index,
                                  "auditor_model_event_index": model_index})
    if len({post["message_id"] for post in posts}) != len(posts):
        raise RemoteBoundaryError("FEE013 duplicate provider channel identity")
    return {"provider_messages": posts, "auditor_exposures": reads}


def reported_reasoning(sample: Any) -> dict:
    """Count disclosed reasoning tokens from raw model events by assigned role.

    A zero is an observed zero; a missing usage field is reported separately.
    Neither value is a measurement of undisclosed private reasoning.
    """
    totals = {"provider": 0, "auditor": 0}
    missing = {"provider": 0, "auditor": 0}
    for event in sample.events:
        if event.event != "model":
            continue
        role = _agent_for_event(event, sample)
        if role not in totals:
            raise RemoteBoundaryError("FEE013 reasoning event actor differs")
        usage = getattr(getattr(event, "output", None), "usage", None)
        tokens = getattr(usage, "reasoning_tokens", None)
        if tokens is None:
            missing[role] += 1
        elif type(tokens) is int and tokens >= 0:
            totals[role] += tokens
        else:
            raise RemoteBoundaryError("FEE013 reported reasoning tokens invalid")
    return {"reported_reasoning_tokens_by_role": totals,
            "reported_reasoning_tokens_missing_by_role": missing}


def verify_boundary(log: Any, observed: list[dict], row: Fee013Row,
                    native_prefix: dict) -> dict:
    if (log.status != "success" or len(log.samples or []) != 1
            or log.samples[0].error or log.samples[0].limit):
        raise RemoteBoundaryError("FEE013 Inspect sample is not successful")
    sample = log.samples[0]
    expected = {"provider": "openrouter/" + row.provider_model_id,
                "auditor": "openrouter/" + row.auditor_model_id}
    agents = sample.metadata["experiment"]["setup"]["agents"]
    if ({a["name"]: a["model"] for a in agents} != expected
            or {a["name"]: a["system_prompt"] for a in agents}
                != role_system_prompts(row)
            or (sample.metadata["experiment"]["communication"] or {}).get(
                "delivery") != ("poll" if row.contact == "CHANNEL" else None)):
        raise RemoteBoundaryError("FEE013 saved role prompt, route or poll differs")
    events = [e for e in sample.events if e.event == "model"]
    if not events or len(events) != len(observed):
        raise RemoteBoundaryError("FEE013 raw model event count differs")
    if [item["role"] for item in observed] != list(ROLE_STEPS[:len(observed)]):
        raise RemoteBoundaryError("FEE013 observed role order differs from frozen schedule")
    counts = Counter()
    for index, (event, actual) in enumerate(zip(events, observed, strict=True)):
        role = _agent_for_event(event, sample)
        if role not in ROLE_LIMITS:
            raise RemoteBoundaryError("FEE013 model lacks assigned actor")
        counts[role] += 1
        if role != ROLE_STEPS[index]:
            raise RemoteBoundaryError("FEE013 raw model role order differs")
        strict_message_priority(event.input, role, row, native_prefix)
        serialized = _strict_tools(event.tools, role, row.contact)
        config = event.config
        wanted = {"call_index": index + 1, "role": role,
                  "model": expected[role],
                  "serialized_input_bytes": _safe_model_input_size(event.input, event.tools),
                  "tool_schema_sha256": sha256(serialized.encode()).hexdigest(),
                  "provider_api_invoked": True, "network_forwarding": "UNOBSERVED",
                  "http_client_max_retries": 0, "completed": True}
        if (actual != wanted or counts[role] > ROLE_LIMITS[role]
                or actual["serialized_input_bytes"] > MAX_INPUT_BYTES
                or event.model != expected[role] or event.error
                or event.cache is not None or event.retries not in (None, 0)
                or config is None or config.reasoning_effort != "high"
                or config.reasoning_history != "none"
                or config.max_tokens != MAX_OUTPUT_TOKENS
                or config.max_retries != 0):
            raise RemoteBoundaryError("FEE013 raw model request differs")
    if set(counts) != set(ROLE_LIMITS):
        raise RemoteBoundaryError("FEE013 both model roles require forwarding")
    terminal = [i for i, event in enumerate(sample.events)
                if event.event == "tool"
                and event.function == "issue_fee_invoice_verdict" and not event.error]
    if len(terminal) > 1 or terminal and any(
            e.event == "model" for e in sample.events[terminal[0] + 1:]):
        raise RemoteBoundaryError("FEE013 post-verdict model call or second verdict")
    if not terminal and (counts["provider"] != PROVIDER_CALLS
                         or counts["auditor"] != AUDITOR_CALLS):
        raise RemoteBoundaryError("FEE013 no-verdict schedule ended early")
    for index, event in enumerate(sample.events):
        if event.event == "tool" and not event.error:
            role = _agent_for_event(event, sample)
            if role not in ROLE_LIMITS or event.function not in allowed_tools(
                    role, row.contact):
                raise RemoteBoundaryError("FEE013 tool actor/name differs")
            _tool_origin(sample, index, role, row.provider_model_id if role ==
                         "provider" else row.auditor_model_id)
    exposure = verify_provider_exposure(sample, row)
    return {"provider_calls": counts["provider"],
            "auditor_calls": counts["auditor"],
            "reasoning_effort_by_role": {"provider": "high", "auditor": "high"},
            "terminal_verdict_issued": bool(terminal),
            **reported_reasoning(sample), **exposure}
