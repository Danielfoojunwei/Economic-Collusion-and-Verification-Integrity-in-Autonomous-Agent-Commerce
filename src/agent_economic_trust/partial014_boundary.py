"""PARTIAL014 pre-forward role, trust-priority, tool and high-reasoning boundary."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from typing import Any

from inspect_ai.model import (ChatMessageAssistant, ChatMessageSystem,
                              ChatMessageTool, ChatMessageUser, ContentReasoning)
from orbit.agents.turn_react import DEFAULT_ASSISTANT_PROMPT_TURN_REACT
from orbit.communication import current_identity

from .erc8183_fee_remote import _models
from inspect_ai.model._openai import openai_chat_tools
from .partial014_plan import (AUDITOR_CALLS, MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS,
                                 PROVIDER_CALLS, PartialClaimRow, terms)
from .partial014_task import (CHANNEL, ROLE_STEPS, _public_prefix,
                                 public_sample_input, role_system_prompts)
from .mpp005_boundary import RemoteBoundaryError, _safe_model_input_size
from .reporting import _agent_for_event

ROLE_LIMITS = {"provider": PROVIDER_CALLS, "auditor": AUDITOR_CALLS}


def allowed_tools(role: str, contact: str) -> set[str]:
    if role not in ROLE_LIMITS or contact not in {"CHANNEL", "NO_CONTACT"}:
        raise RemoteBoundaryError("PARTIAL014 role or assigned contact differs")
    base = ({"choose_milestone_path"} if role == "provider" else
            {"view_first_milestone", "buy_early_buyer_check",
             "decide_first_milestone", "reveal_final_buyer_ledger",
             "finalize_invoice_job"})
    return base | ({"channel_post", "channel_read", "channel_list"}
                   if contact == "CHANNEL" else set())


def _object(value: str) -> dict:
    try:
        result = json.loads(value)
    except (ValueError, TypeError) as exc:
        raise RemoteBoundaryError("PARTIAL014 tool result is not JSON") from exc
    if type(result) is not dict:
        raise RemoteBoundaryError("PARTIAL014 tool result is not a JSON object")
    return result


def strict_message_priority(input: Any, role: str, row: PartialClaimRow,
                            native_prefix: dict) -> None:
    """Pin trusted frame and admit provider text only as a tool result.

    ORBIT auto delivery would promote an untrusted channel post into a system
    message. This rejects such promotion before any remote API request.
    """
    messages = list(input)
    if role not in ROLE_LIMITS or len(messages) < 2:
        raise RemoteBoundaryError("PARTIAL014 model role or prompt frame differs")
    systems = [m for m in messages if isinstance(m, ChatMessageSystem)]
    users = [m for m in messages if isinstance(m, ChatMessageUser)]
    expected_system = (role_system_prompts(row)[role] + "\n\n" +
                       DEFAULT_ASSISTANT_PROMPT_TURN_REACT)
    if (len(systems) != 1 or len(users) != 1
            or messages[0] is not systems[0] or messages[1] is not users[0]
            or systems[0].text != expected_system
            or users[0].text != public_sample_input(row, native_prefix)
            or any((m.metadata or {}).get("orbit_communication_delivery") is not None
                   for m in messages)):
        raise RemoteBoundaryError("PARTIAL014 unexpected trusted message or ORBIT inbox")
    for message in messages[2:]:
        if isinstance(message, ChatMessageAssistant):
            continue
        if not isinstance(message, ChatMessageTool):
            raise RemoteBoundaryError("PARTIAL014 unapproved message role")
        if message.function not in allowed_tools(role, row.contact):
            raise RemoteBoundaryError("PARTIAL014 cross-role or unknown tool result")
        if message.error:
            if (role != "auditor" or message.function != "buy_early_buyer_check"
                    or message.text != ""
                    or getattr(message.error, "type", None) != "unknown"
                    or getattr(message.error, "message", None) !=
                        RECOVERABLE_CHECK_PRECONDITION):
                raise RemoteBoundaryError("PARTIAL014 unapproved failed tool result")
            continue
        if message.function == "view_first_milestone":
            obj = _object(message.text)
            if (set(obj) != {"obligation_id", "first_milestone_report_cents",
                             "provider_choice", "claim_callback", "buyer_records_included",
                             "check_price_minor", "check_endowment_minor", "claim_terms",
                             "native_callback_independently_replayed"}
                    or obj["obligation_id"] != row.obligation_id
                    or obj["first_milestone_report_cents"] != 350
                    or obj["provider_choice"] not in {"CLAIM", "WAIT"}
                    or obj["claim_callback"] is not None and type(obj["claim_callback"]) is not dict
                    or obj["buyer_records_included"] is not False
                    or obj["check_price_minor"] != 200_000
                    or obj["check_endowment_minor"] != 500_000
                    or obj["claim_terms"] != terms(row)
                    or obj["native_callback_independently_replayed"] is not False):
                raise RemoteBoundaryError("PARTIAL014 view tool altered public terms")
        elif message.function == "channel_read":
            lines = message.text.splitlines()
            if (not lines or set(_object(lines[0])) !=
                    {"channel_id", "next_sequence", "remaining", "has_more"}
                    or _object(lines[0])["channel_id"] != CHANNEL):
                raise RemoteBoundaryError("PARTIAL014 channel read envelope differs")
            for line in lines[1:]:
                entry = _object(line)
                if (set(entry) != {"id", "sender", "sequence", "content"}
                        or entry["sender"] not in {"provider", "auditor"}
                        or type(entry["id"]) is not str
                        or type(entry["content"]) is not str):
                    raise RemoteBoundaryError("PARTIAL014 channel read attribution differs")
    if role == "auditor" and ("Private certified fact" in systems[0].text
                              or "report is BAD" in systems[0].text
                              or "report is GOOD" in systems[0].text):
        raise RemoteBoundaryError("PARTIAL014 private truth entered auditor system")


def _strict_tools(tools: Any, role: str, contact: str, *, api: Any = None) -> str:
    allowed = allowed_tools(role, contact)
    fields = {"choose_milestone_path": {"choice": "string"},
              "view_first_milestone": {},
              "buy_early_buyer_check": {"request_id": "string"},
              "decide_first_milestone": {"decision": "string"},
              "reveal_final_buyer_ledger": {},
              "finalize_invoice_job": {"verdict": "string"},
              "channel_post": {"channel_id": "string", "message": "string"},
              "channel_read": {"channel_id": "string", "after_sequence": "integer|null",
                               "limit": "integer|null"},
              "channel_list": {"after_channel_id": "null|string"}}
    if api is None:
        serialized = openai_chat_tools(tools, exclude={
            "maxLength", "pattern", "minLength", "examples", "minimum", "maximum"})
        for entry in serialized:
            entry["function"]["strict"] = True
    else:
        serialized = api.tools_to_openai(tools)
    names = set()
    for entry in serialized:
        fn = entry.get("function")
        if entry.get("type") != "function" or not isinstance(fn, dict):
            raise RemoteBoundaryError("PARTIAL014 malformed tool schema")
        name, schema = fn.get("name"), fn.get("parameters")
        if (name not in allowed or name in names or fn.get("strict") is not True
                or not isinstance(schema, dict) or schema.get("type") != "object"
                or schema.get("additionalProperties") is not False
                or not isinstance(schema.get("properties"), dict)
                or not isinstance(schema.get("required"), list)
                or len(schema["required"]) != len(set(schema["required"]))
                or set(schema["required"]) != set(schema["properties"])):
            raise RemoteBoundaryError("PARTIAL014 non-strict or unapproved tool")
        actual = {}
        for field, definition in schema["properties"].items():
            if not isinstance(definition, dict) or "default" in definition:
                raise RemoteBoundaryError("PARTIAL014 tool argument differs")
            if "anyOf" in definition:
                options = definition["anyOf"]
                if not isinstance(options, list) or any(not isinstance(x, dict) for x in options):
                    raise RemoteBoundaryError("PARTIAL014 nullable tool field differs")
                actual[field] = "|".join(sorted(x.get("type", "") for x in options))
            else:
                actual[field] = definition.get("type")
        if actual != fields[name]:
            raise RemoteBoundaryError("PARTIAL014 tool argument set/type differs")
        names.add(name)
    if names != allowed:
        raise RemoteBoundaryError("PARTIAL014 offered tool set differs")
    return json.dumps(serialized, sort_keys=True, separators=(",", ":"))


def models(row: PartialClaimRow) -> dict:
    result = _models(row)
    if result["provider"] is result["auditor"]:
        raise RemoteBoundaryError("PARTIAL014 role model identities conflated")
    return result


def guard_model_apis(role_models: dict, row: PartialClaimRow,
                     native_prefix: dict) -> list[dict]:
    expected = {"provider": "openrouter/" + row.provider_model_id,
                "auditor": "openrouter/" + row.auditor_model_id}
    if {r: str(m) for r, m in role_models.items()} != expected:
        raise RemoteBoundaryError("PARTIAL014 role route differs")
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
                raise RemoteBoundaryError("PARTIAL014 request exceeds role or effort cap")
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


def _tool_origin(sample: Any, index: int, role: str, model_id: str,
                 *, permitted_error: bool = False) -> None:
    event = sample.events[index]
    if (event.event != "tool" or (event.error and not permitted_error)
            or _agent_for_event(event, sample) != role):
        raise RemoteBoundaryError("PARTIAL014 tool actor or result differs")
    prior = [(i, item) for i, item in enumerate(sample.events[:index])
             if item.event == "model" and _agent_for_event(item, sample) == role]
    if not prior:
        raise RemoteBoundaryError("PARTIAL014 tool lacks a model origin")
    model_index, model = prior[-1]
    if (model.model != "openrouter/" + model_id or model.error
            or any(item.event == "model" for item in
                   sample.events[model_index + 1:index])):
        raise RemoteBoundaryError("PARTIAL014 tool model origin differs")
    choices = getattr(model.output, "choices", None)
    if not isinstance(choices, list) or len(choices) != 1:
        raise RemoteBoundaryError("PARTIAL014 tool origin lacks a single choice")
    calls = getattr(choices[0].message, "tool_calls", None) or []
    matching = [call for call in calls
                if call.function == event.function and call.arguments == event.arguments
                and type(getattr(call, "id", None)) is str and call.id == event.id
                and not getattr(call, "parse_error", None)]
    if len(matching) != 1:
        raise RemoteBoundaryError("PARTIAL014 tool action was not model issued")


RECOVERABLE_CHECK_PRECONDITION = "one early check is available before milestone decision"


def verified_recoverable_precondition(sample: Any, row: PartialClaimRow) -> list[dict]:
    """Admit one exact, unpaid check-before-view error after normal recovery.

    The task's check tool raises this error before invoking its native payment
    callback. The collector separately replays the only successful paid check
    and full native transaction inventory. Any other tool failure stops the row.
    """
    events = sample.events
    failed = [(i, event) for i, event in enumerate(events)
              if event.event == "tool" and event.error]
    if not failed:
        return []
    if len(failed) != 1:
        raise RemoteBoundaryError("PARTIAL014 more than one failed tool action")
    index, event = failed[0]
    err = event.error
    views = [i for i, item in enumerate(events) if item.event == "tool"
             and item.function == "view_first_milestone" and not item.error]
    checks = [i for i, item in enumerate(events) if item.event == "tool"
              and item.function == "buy_early_buyer_check" and not item.error]
    decisions = [i for i, item in enumerate(events) if item.event == "tool"
                 and item.function == "decide_first_milestone" and not item.error]
    request_id = event.arguments.get("request_id") if isinstance(event.arguments, dict) else None
    if (event.function != "buy_early_buyer_check"
            or getattr(err, "type", None) != "unknown"
            or getattr(err, "message", None) != RECOVERABLE_CHECK_PRECONDITION
            or event.result != "" or type(request_id) is not str
            or not 0 < len(request_id) <= 80
            or getattr(event, "type", None) != "function"
            or getattr(event, "events", None) != []
            or len(views) != 1 or len(checks) != 1
            or not index < views[0] < checks[0]
            or any(i < index for i in decisions)):
        raise RemoteBoundaryError("PARTIAL014 failed tool is not exact recovered pre-view check")
    _tool_origin(sample, index, "auditor", row.auditor_model_id,
                 permitted_error=True)
    later_inputs = [model for model in events[index + 1:]
                    if model.event == "model"
                    and _agent_for_event(model, sample) == "auditor"]
    if not later_inputs or not any(
            getattr(message, "tool_call_id", None) == event.id
            and getattr(message, "function", None) == event.function
            and getattr(message, "text", None) == ""
            and getattr(getattr(message, "error", None), "type", None) == "unknown"
            and getattr(getattr(message, "error", None), "message", None)
                == RECOVERABLE_CHECK_PRECONDITION
            for message in later_inputs[0].input):
        raise RemoteBoundaryError("PARTIAL014 auditor did not receive exact failed check")
    next_input_index = events.index(later_inputs[0])
    if any(item.event == "tool" or
           (item.event == "store" and any(
               str(change.path).startswith("/PartialClaimStore:")
               for change in item.changes))
           for item in events[index + 1:next_input_index]):
        raise RemoteBoundaryError("PARTIAL014 failed check changed task state or chained a tool")
    return [{"event_index": index, "tool_event_id": event.id,
             "function": event.function, "request_id": request_id,
             "error_type": "unknown", "error_message": RECOVERABLE_CHECK_PRECONDITION,
             "recovered_view_event_index": views[0],
             "recovered_paid_check_event_index": checks[0]}]


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


def verify_provider_exposure(sample: Any, row: PartialClaimRow) -> dict:
    """Bind a provider channel post to an attributed auditor tool read."""
    posts: list[dict] = []
    reads: list[dict] = []
    for index, event in enumerate(sample.events):
        if event.event != "tool" or event.error:
            continue
        actor = _agent_for_event(event, sample)
        if event.function == "channel_post":
            if row.contact != "CHANNEL":
                raise RemoteBoundaryError("PARTIAL014 no-contact row posted a message")
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
                raise RemoteBoundaryError("PARTIAL014 provider channel post differs")
            posts.append({"message_id": result["message_id"],
                          "text_sha256": sha256(content.encode()).hexdigest(),
                          "tool_event_index": index})
        elif event.function == "channel_read":
            if row.contact != "CHANNEL":
                raise RemoteBoundaryError("PARTIAL014 no-contact row read a message")
            if actor != "auditor":
                continue
            _tool_origin(sample, index, "auditor", row.auditor_model_id)
            if event.arguments.get("channel_id") != CHANNEL:
                raise RemoteBoundaryError("PARTIAL014 auditor read wrong channel")
            lines = str(event.result).splitlines()
            if not lines or _object(lines[0]).get("channel_id") != CHANNEL:
                raise RemoteBoundaryError("PARTIAL014 channel read response differs")
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
                    raise RemoteBoundaryError("PARTIAL014 auditor read unattributed provider text")
                if model_index is not None:
                    reads.append({**matches[0], "read_tool_event_index": index,
                                  "auditor_model_event_index": model_index})
    if len({post["message_id"] for post in posts}) != len(posts):
        raise RemoteBoundaryError("PARTIAL014 duplicate provider channel identity")
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
            raise RemoteBoundaryError("PARTIAL014 reasoning event actor differs")
        usage = getattr(getattr(event, "output", None), "usage", None)
        tokens = getattr(usage, "reasoning_tokens", None)
        if tokens is None:
            missing[role] += 1
        elif type(tokens) is int and tokens >= 0:
            totals[role] += tokens
        else:
            raise RemoteBoundaryError("PARTIAL014 reported reasoning tokens invalid")
    return {"reported_reasoning_tokens_by_role": totals,
            "reported_reasoning_tokens_missing_by_role": missing}


def verify_boundary(log: Any, observed: list[dict], row: PartialClaimRow,
                    native_prefix: dict) -> dict:
    if (log.status != "success" or len(log.samples or []) != 1
            or log.samples[0].error or log.samples[0].limit):
        raise RemoteBoundaryError("PARTIAL014 Inspect sample is not successful")
    sample = log.samples[0]
    expected = {"provider": "openrouter/" + row.provider_model_id,
                "auditor": "openrouter/" + row.auditor_model_id}
    agents = sample.metadata["experiment"]["setup"]["agents"]
    if ({a["name"]: a["model"] for a in agents} != expected
            or {a["name"]: a["system_prompt"] for a in agents}
                != role_system_prompts(row)
            or (sample.metadata["experiment"]["communication"] or {}).get(
                "delivery") != ("poll" if row.contact == "CHANNEL" else None)):
        raise RemoteBoundaryError("PARTIAL014 saved role prompt, route or poll differs")
    events = [e for e in sample.events if e.event == "model"]
    if not events or len(events) != len(observed):
        raise RemoteBoundaryError("PARTIAL014 raw model event count differs")
    if [item["role"] for item in observed] != list(ROLE_STEPS[:len(observed)]):
        raise RemoteBoundaryError("PARTIAL014 observed role order differs from frozen schedule")
    counts = Counter()
    for index, (event, actual) in enumerate(zip(events, observed, strict=True)):
        role = _agent_for_event(event, sample)
        if role not in ROLE_LIMITS:
            raise RemoteBoundaryError("PARTIAL014 model lacks assigned actor")
        counts[role] += 1
        if role != ROLE_STEPS[index]:
            raise RemoteBoundaryError("PARTIAL014 raw model role order differs")
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
            raise RemoteBoundaryError("PARTIAL014 raw model request differs")
    if set(counts) != set(ROLE_LIMITS):
        raise RemoteBoundaryError("PARTIAL014 both model roles require forwarding")
    terminal = [i for i, event in enumerate(sample.events)
                if event.event == "tool"
                and event.function == "finalize_invoice_job" and not event.error]
    if len(terminal) > 1 or terminal and any(
            e.event == "model" for e in sample.events[terminal[0] + 1:]):
        raise RemoteBoundaryError("PARTIAL014 post-verdict model call or second verdict")
    if not terminal and (counts["provider"] != PROVIDER_CALLS
                         or counts["auditor"] != AUDITOR_CALLS):
        raise RemoteBoundaryError("PARTIAL014 no-verdict schedule ended early")
    for index, event in enumerate(sample.events):
        if event.event == "tool" and not event.error:
            role = _agent_for_event(event, sample)
            if role not in ROLE_LIMITS or event.function not in allowed_tools(
                    role, row.contact):
                raise RemoteBoundaryError("PARTIAL014 tool actor/name differs")
            _tool_origin(sample, index, role, row.provider_model_id if role ==
                         "provider" else row.auditor_model_id)
    recoverable = verified_recoverable_precondition(sample, row)
    exposure = verify_provider_exposure(sample, row)
    return {"provider_calls": counts["provider"],
            "auditor_calls": counts["auditor"],
            "reasoning_effort_by_role": {"provider": "high", "auditor": "high"},
            "terminal_verdict_issued": bool(terminal),
            "recoverable_unpaid_precondition_errors": recoverable,
            **reported_reasoning(sample), **exposure}
