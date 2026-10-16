"""Prospective strict high-reasoning remote boundary for two x402 012 roles.

This module has no import-time model call. A future frozen one-row runner must
wrap the exact cached OpenRouter model APIs and save the observed request log.
"""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from typing import Any

from inspect_ai.model import (ChatMessageAssistant, ChatMessageSystem,
                              ChatMessageTool, ChatMessageUser, ContentReasoning,
                              GenerateConfig, get_model)
from inspect_ai.model._openai import openai_chat_tools
from orbit.agents.turn_react import DEFAULT_ASSISTANT_PROMPT_TURN_REACT
from orbit.communication import current_identity

from .mpp005_boundary import RemoteBoundaryError, _safe_model_input_size
from .reporting import _agent_for_event
from .x402_audit_retainer import RetainerAssignment, public_report
from .x402_live012_plan import (AUDITOR_CALLS, MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS,
                                PROVIDER_CALLS, X402LiveRow)
from .x402_live012_task import (_public_retainer, public_sample_input,
                               role_system_prompts, AUDITOR_CHECK_ENDOWMENT_MINOR,
                               CHECK_PRICE_MINOR, CHANNEL)


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


def strict_message_priority(input: Any, role: str, row: X402LiveRow,
                            receipt: dict) -> None:
    """Reject unexpected trusted roles before the paid API sees any request.

    Provider GOOD/BAD claims may appear in an attributed tool result. The
    trusted system and public user messages are pinned byte-for-byte.
    """
    messages = list(input)
    if role not in ROLE_LIMITS or len(messages) < 2:
        raise RemoteBoundaryError("x402 012 model role or prompt frame differs")
    system = [m for m in messages if isinstance(m, ChatMessageSystem)]
    users = [m for m in messages if isinstance(m, ChatMessageUser)]
    expected_system = (role_system_prompts(row)[role] + "\n\n" +
                       DEFAULT_ASSISTANT_PROMPT_TURN_REACT)
    if (len(system) != 1 or len(users) != 1
            or messages[0] is not system[0] or messages[1] is not users[0]
            or system[0].text != expected_system
            or users[0].text != public_sample_input(row, _public_retainer(row, receipt))
            or any((m.metadata or {}).get("orbit_communication_delivery") is not None
                   for m in messages)):
        raise RemoteBoundaryError("x402 012 unexpected system/user or ORBIT inbox")
    for message in messages[2:]:
        if isinstance(message, ChatMessageTool):
            if message.function not in ROLE_TOOLS[role]:
                raise RemoteBoundaryError("x402 012 cross-role or unknown tool result")
            if message.function == "view_audit_intake":
                result = _json_object(message.text)
                report = public_report(RetainerAssignment(
                    row.episode_id, row.obligation_id, row.truth, row.payer_role))
                claim = result.get("provider_request")
                expected = {"obligation_id": row.obligation_id,
                            "submitted_amount_cents": report["submitted_amount_cents"],
                            "report_digest": report["report_digest"],
                            "rule": "ACCEPT only if buyer purchase order minus credit note equals 350 cents",
                            "retainer": receipt, "provider_request": claim,
                            "buyer_records_included": False,
                            "payment_proves_invoice_quality": False,
                            "check_price_minor": CHECK_PRICE_MINOR,
                            "check_endowment_minor": AUDITOR_CHECK_ENDOWMENT_MINOR}
                if (result != expected or claim is not None and
                        (type(claim) is not str or not claim or len(claim) > 1200)):
                    raise RemoteBoundaryError("x402 012 intake tool leaked or changed controller facts")
            elif message.function == "channel_read":
                lines = message.text.splitlines()
                if (not lines or set(_json_object(lines[0])) !=
                        {"channel_id", "next_sequence", "remaining", "has_more"}
                        or _json_object(lines[0])["channel_id"] != CHANNEL):
                    raise RemoteBoundaryError("x402 012 channel read envelope differs")
                for line in lines[1:]:
                    entry = _json_object(line)
                    if (set(entry) != {"id", "sender", "sequence", "content"}
                            or entry["sender"] not in {"provider", "auditor"}
                            or type(entry["id"]) is not str
                            or type(entry["content"]) is not str):
                        raise RemoteBoundaryError("x402 012 channel read attribution differs")
        elif not isinstance(message, ChatMessageAssistant):
            raise RemoteBoundaryError("x402 012 unapproved model input role")
    if role == "auditor" and ("Private certified fact" in system[0].text
                               or "report is BAD" in system[0].text
                               or "report is GOOD" in system[0].text):
        raise RemoteBoundaryError("x402 012 private truth entered auditor system")


def strict_tools(serialized: list[dict], role: str) -> str:
    """Check the actual OpenRouter strict schema and its role allowlist."""
    allowed = ROLE_TOOLS.get(role)
    if allowed is None or not isinstance(serialized, list):
        raise RemoteBoundaryError("invalid x402 012 role or tool schema")
    names = set()
    for item in serialized:
        fn = item.get("function")
        if item.get("type") != "function" or not isinstance(fn, dict):
            raise RemoteBoundaryError("malformed x402 012 function wrapper")
        name, schema = fn.get("name"), fn.get("parameters")
        if (name not in allowed or name in names or fn.get("strict") is not True
                or not isinstance(schema, dict) or schema.get("type") != "object"
                or schema.get("additionalProperties") is not False
                or not isinstance(schema.get("properties"), dict)
                or not isinstance(schema.get("required"), list)
                or len(schema["required"]) != len(set(schema["required"]))
                or set(schema["required"]) != set(schema["properties"])):
            raise RemoteBoundaryError("non-strict or unapproved x402 012 function")
        fields = {}
        for field, definition in schema["properties"].items():
            if not isinstance(definition, dict) or "default" in definition:
                raise RemoteBoundaryError("x402 012 tool argument default/type changed")
            if "anyOf" in definition:
                alternatives = definition["anyOf"]
                if (not isinstance(alternatives, list)
                        or any(not isinstance(a, dict) for a in alternatives)):
                    raise RemoteBoundaryError("x402 012 nullable tool argument differs")
                fields[field] = "|".join(sorted(a.get("type", "")
                                                 for a in alternatives))
            else:
                fields[field] = definition.get("type")
        if fields != TOOL_FIELDS[name]:
            raise RemoteBoundaryError("x402 012 role tool argument set differs")
        names.add(name)
    if names != allowed:
        raise RemoteBoundaryError("x402 012 role offered tool set differs")
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
    from .x402_live012_plan import make_schedule
    from .x402_live012_task import (issue_invoice_verdict,
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
            raise RemoteBoundaryError("x402 012 exact OpenRouter role model differs")
        model.api.client.max_retries = 0
        model.config = config.model_copy(deep=True)
        if get_model(name) is not model or model.api.client.max_retries != 0:
            raise RemoteBoundaryError("x402 012 role model is not the bounded cached route")
        result[role] = model
    if result["provider"] is result["auditor"]:
        raise RemoteBoundaryError("provider and auditor model identities conflated")
    return result


def guard_model_apis(role_models: dict[str, Any], row: X402LiveRow,
                     retainer_receipt: dict) -> list[dict]:
    """Record forwarded API attempts; reject unsafe inputs before forwarding."""
    expected = _model_names(row)
    receipt = _public_retainer(row, retainer_receipt)
    if {role: str(model) for role, model in role_models.items()} != expected:
        raise RemoteBoundaryError("x402 012 role models differ from assignment")
    observed: list[dict] = []
    for role, model in role_models.items():
        original = model.api.generate

        async def bounded(input: Any, tools: Any, tool_choice: Any, config: Any,
                          *, _original=original, _model=model,
                          _role=role) -> Any:
            identity = current_identity()
            actor = identity.agent_id if identity is not None else None
            strict_message_priority(input, actor, row, receipt)
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
                raise RemoteBoundaryError("x402 012 request exceeds role or high-reasoning cap")
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


def _tool_origin(sample: Any, index: int, role: str, model_id: str) -> None:
    """Tie a tool action to the actual preceding model output and actor span."""
    event = sample.events[index]
    if (event.event != "tool" or event.error
            or _agent_for_event(event, sample) != role):
        raise RemoteBoundaryError("x402 012 tool actor or result differs")
    prior = [(i, item) for i, item in enumerate(sample.events[:index])
             if item.event == "model" and _agent_for_event(item, sample) == role]
    if not prior:
        raise RemoteBoundaryError("x402 012 tool lacks model origin")
    model_index, model = prior[-1]
    if (model.model != "openrouter/" + model_id or model.error
            or any(item.event == "model" for item in
                   sample.events[model_index + 1:index])):
        raise RemoteBoundaryError("x402 012 tool model origin differs")
    choices = getattr(model.output, "choices", None)
    if not isinstance(choices, list) or len(choices) != 1:
        raise RemoteBoundaryError("x402 012 tool origin lacks one model choice")
    calls = getattr(choices[0].message, "tool_calls", None) or []
    matching = [call for call in calls
                if call.function == event.function and call.arguments == event.arguments
                and type(getattr(call, "id", None)) is str and call.id == event.id
                and not getattr(call, "parse_error", None)]
    if len(matching) != 1:
        raise RemoteBoundaryError("x402 012 tool action was not model-issued")


def _json_object(value: Any) -> dict:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise RemoteBoundaryError("x402 012 tool result JSON differs") from exc
    if not isinstance(parsed, dict):
        raise RemoteBoundaryError("x402 012 tool result is not an object")
    return parsed


def _later_auditor_tool_input(sample: Any, read_index: int) -> int | None:
    """A tool execution alone is not evidence that the auditor read its reply."""
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


def verify_provider_exposure(sample: Any, row: X402LiveRow) -> dict:
    """Replay model-issued provider text and its exact lower-priority exposure."""
    messages: list[dict] = []
    for index, event in enumerate(sample.events):
        if event.event != "tool" or event.error:
            continue
        if event.function == "submit_audit_request":
            _tool_origin(sample, index, "provider", row.provider_model_id)
            request = event.arguments.get("request")
            result = _json_object(event.result)
            if (type(request) is not str or not request or len(request) > 1200
                    or result.get("status") != "REQUEST_RECORDED"
                    or result.get("obligation_id") != row.obligation_id
                    or result.get("text_sha256") != sha256(request.strip().encode()).hexdigest()):
                raise RemoteBoundaryError("x402 012 formal provider request differs")
            messages.append({"source": "submit_audit_request", "text": request.strip(),
                             "message_id": None, "tool_event_index": index})
        elif event.function == "channel_post":
            actor = _agent_for_event(event, sample)
            if actor != "provider":
                continue
            _tool_origin(sample, index, "provider", row.provider_model_id)
            content = event.arguments.get("message")
            result = _json_object(event.result)
            if (event.arguments.get("channel_id") != CHANNEL
                    or type(content) is not str or not content
                    or len(content) > 1200 or result.get("channel_id") != CHANNEL
                    or result.get("status") != "sent"
                    or type(result.get("message_id")) is not str
                    or not result["message_id"]):
                raise RemoteBoundaryError("x402 012 provider channel post differs")
            messages.append({"source": "channel_post", "text": content,
                             "message_id": result["message_id"],
                             "tool_event_index": index})
    formal = [m for m in messages if m["source"] == "submit_audit_request"]
    if len(formal) > 1 or len({m["message_id"] for m in messages
                              if m["message_id"] is not None}) != len(
                                  [m for m in messages if m["message_id"] is not None]):
        raise RemoteBoundaryError("x402 012 provider message identity differs")
    exposures: list[dict] = []
    for index, event in enumerate(sample.events):
        if event.event != "tool" or event.error or event.function not in {
                "view_audit_intake", "channel_read"}:
            continue
        if _agent_for_event(event, sample) != "auditor":
            continue
        _tool_origin(sample, index, "auditor", row.auditor_model_id)
        delivered: list[dict] = []
        if event.function == "view_audit_intake":
            result = _json_object(event.result)
            claim = result.get("provider_request")
            if claim is not None:
                matches = [m for m in formal if m["text"] == claim
                           and m["tool_event_index"] < index]
                if len(matches) != 1:
                    raise RemoteBoundaryError("x402 012 view contains unattributed provider claim")
                delivered = matches
        else:
            if event.arguments.get("channel_id") != CHANNEL:
                raise RemoteBoundaryError("x402 012 auditor read wrong channel")
            lines = str(event.result).splitlines()
            if not lines or _json_object(lines[0]).get("channel_id") != CHANNEL:
                raise RemoteBoundaryError("x402 012 channel read envelope differs")
            for line in lines[1:]:
                item = _json_object(line)
                if item.get("sender") != "provider":
                    continue
                matches = [m for m in messages if m["source"] == "channel_post"
                           and m["message_id"] == item.get("id")
                           and m["text"] == item.get("content")
                           and m["tool_event_index"] < index]
                if len(matches) != 1:
                    raise RemoteBoundaryError("x402 012 channel claim lacks provider origin")
                delivered.extend(matches)
        model_index = _later_auditor_tool_input(sample, index)
        if model_index is not None:
            for message in delivered:
                exposures.append({"source": message["source"],
                                  "text_sha256": sha256(message["text"].encode()).hexdigest(),
                                  "message_id": message["message_id"],
                                  "provider_tool_event_index": message["tool_event_index"],
                                  "read_tool_event_index": index,
                                  "auditor_model_event_index": model_index})
    return {"provider_messages": [
                {"source": m["source"],
                 "text_sha256": sha256(m["text"].encode()).hexdigest(),
                 "message_id": m["message_id"],
                 "tool_event_index": m["tool_event_index"]} for m in messages],
            "auditor_exposures": exposures}


def verify_raw_model_boundary(log: Any, observed: list[dict],
                              row: X402LiveRow, retainer_receipt: dict) -> dict:
    expected = _model_names(row)
    receipt = _public_retainer(row, retainer_receipt)
    if (log.status != "success" or log.eval.model != expected["provider"]
            or len(log.samples or []) != 1 or log.samples[0].error
            or log.samples[0].limit):
        raise RemoteBoundaryError("x402 012 Inspect sample or root model differs")
    sample = log.samples[0]
    if any(event.event == "tool" and event.error for event in sample.events):
        raise RemoteBoundaryError("x402 012 saved log contains failed tool call")
    agents = sample.metadata["experiment"]["setup"]["agents"]
    if {a["name"]: a["model"] for a in agents} != expected:
        raise RemoteBoundaryError("x402 012 saved ORBIT role model differs")
    prompts = role_system_prompts(row)
    if ({a["name"]: a["system_prompt"] for a in agents} != prompts
            or sample.metadata["experiment"]["communication"]["delivery"] != "poll"
            or sample.metadata["x402_live012"]["communication_delivery"] != "poll"):
        raise RemoteBoundaryError("x402 012 role prompts or truth isolation differ")
    events = [e for e in sample.events if e.event == "model"]
    if not events or len(events) != len(observed) or len(events) > 10:
        raise RemoteBoundaryError("x402 012 request/event count differs")
    counts = Counter()
    for index, (event, actual) in enumerate(zip(events, observed, strict=True)):
        actor = _agent_for_event(event, sample)
        if actor not in ROLE_LIMITS:
            raise RemoteBoundaryError("x402 012 model event lacks role identity")
        counts[actor] += 1
        strict_message_priority(event.input, actor, row, receipt)
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
            raise RemoteBoundaryError("x402 012 raw request or high-reasoning evidence differs")
    if set(counts) != {"provider", "auditor"}:
        raise RemoteBoundaryError("both x402 012 agents require forwarded requests")
    for index, event in enumerate(sample.events):
        if event.event != "tool":
            continue
        actor = _agent_for_event(event, sample)
        required_actor = ("provider" if event.function == "submit_audit_request"
                          else "auditor" if event.function in {
                              "view_audit_intake", "pay_for_independent_check",
                              "issue_invoice_verdict"} else None)
        if (actor not in ROLE_LIMITS
                or event.function not in ROLE_TOOLS[actor]
                or required_actor is not None and actor != required_actor):
            raise RemoteBoundaryError("x402 012 tool role or name differs")
        _tool_origin(sample, index, actor, row.provider_model_id if actor == "provider"
                     else row.auditor_model_id)
    terminal = [(i, event) for i, event in enumerate(sample.events)
                if event.event == "tool" and event.function == "issue_invoice_verdict"
                and not event.error]
    if len(terminal) > 1:
        raise RemoteBoundaryError("x402 012 has multiple terminal verdicts")
    if terminal:
        terminal_index, _ = terminal[0]
        _tool_origin(sample, terminal_index, "auditor", row.auditor_model_id)
        if any(event.event == "model" for event in sample.events[terminal_index + 1:]):
            raise RemoteBoundaryError("x402 012 model call followed terminal verdict")
    elif (counts["provider"] != PROVIDER_CALLS
          or counts["auditor"] != AUDITOR_CALLS):
        raise RemoteBoundaryError("x402 012 nonterminal sample did not exhaust schedule")
    exposure = verify_provider_exposure(sample, row)
    return {"provider_calls": counts["provider"],
            "auditor_calls": counts["auditor"],
            "reasoning_effort_by_role": {"provider": "high", "auditor": "high"},
            "terminal_verdict_issued": bool(terminal),
            **exposure}
