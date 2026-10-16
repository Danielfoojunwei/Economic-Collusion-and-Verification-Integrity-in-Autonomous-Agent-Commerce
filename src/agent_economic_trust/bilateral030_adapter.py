"""Offline-verifiable dual-role OpenRouter guard for BILATERAL030.

This context manager can wrap both Inspect model APIs, but the paid entrypoint
does not call it. A future frozen runner must additionally enforce Inspect
retry_on_error=0, archive raw EvalLog/ModelCalls, verify native receipts and
settle ambiguous charges under the shared budget ledger.
"""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
from typing import Any, Iterator, Mapping

from inspect_ai.model import ModelOutput
from inspect_ai.model._model_call import ModelCall
from orbit.communication import current_identity

from .bilateral030_boundary import (ORBIT_CONTINUATION, validate_agent_specs,
                                    validate_request)
from .bilateral030_plan import MAX_OUTPUT_TOKENS, ROLE_STEPS, SOL, Bilateral030Row
from .mpp005_boundary import RemoteBoundaryError


def _raw_call_sha(call: ModelCall) -> str:
    return sha256(json.dumps(
        {"request": call.request, "response": call.response, "error": call.error},
        sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _raw_call_request(call: ModelCall, *, row: Bilateral030Row, role: str,
                      expected_system: str, expected_user: str,
                      tool_schema: list[dict[str, Any]]) -> None:
    """Check the adapter's actual recorded request after translation."""
    request = call.request
    model_id = (row.provider_model_id if role == "provider"
                else row.auditor_model_id)
    cap_key = "max_completion_tokens" if model_id == SOL else "max_tokens"
    other_key = "max_tokens" if model_id == SOL else "max_completion_tokens"
    messages = request.get("messages")
    if (request.get("model") != model_id
            or request.get(cap_key) != MAX_OUTPUT_TOKENS
            or other_key in request
            or request.get("extra_body", {}).get("reasoning") != {"effort": "high"}
            or request.get("tools") != tool_schema
            or request.get("tool_choice") != "auto"
            or not isinstance(messages, list) or len(messages) < 2
            or messages[0] != {"role": "system", "content": expected_system}
            or messages[1] != {"role": "user", "content": expected_user}
            or sum(message.get("role") == "system" for message in messages) != 1
            or any(message.get("role") == "user" and
                   (message.get("content") != ORBIT_CONTINUATION or
                    messages[index - 1].get("role") != "tool")
                   for index, message in enumerate(messages[2:], start=2))):
        raise RemoteBoundaryError(
            "BILATERAL030 raw ModelCall dropped route, effort, cap, tools or trusted frame")


def boundary_status(observed: list[dict[str, Any]]) -> str:
    """Never convert a failed or incomplete call into a scientific outcome."""
    if any(item.get("status") == "STOPPED" for item in observed):
        return "STOPPED"
    if len(observed) == len(ROLE_STEPS) and all(
            item.get("status") == "COMPLETE" for item in observed):
        return "MODEL_REQUESTS_COMPLETE_NATIVE_UNVERIFIED"
    return "IN_PROGRESS"


@contextmanager
def guarded_model_apis(role_models: Mapping[str, Any], row: Bilateral030Row,
                       experiment: Mapping[str, Any],
                       expected_systems: Mapping[str, str],
                       expected_user: str) -> Iterator[list[dict[str, Any]]]:
    """Attach both API wrappers for one offline/future bounded Inspect eval.

    The caller must use the actual task metadata, cached role model objects,
    and exact trusted prompt strings. The wrappers are restored even on error.
    This function itself makes no request; the test suite only exercises it
    using an explicit fake key and httpx MockTransport.
    """
    routes = validate_agent_specs(row, experiment)
    if (set(role_models) != {"provider", "auditor"}
            or set(expected_systems) != {"provider", "auditor"}
            or role_models["provider"] is role_models["auditor"]):
        raise RemoteBoundaryError("BILATERAL030 both distinct role models required")
    for role, model in role_models.items():
        if (str(model) != routes[role]
                or type(model.api).__name__ != "OpenRouterAPI"
                or model.api.client.max_retries != 0):
            raise RemoteBoundaryError("BILATERAL030 cached OpenRouter role model differs")
    observed: list[dict[str, Any]] = []
    originals: dict[str, Any] = {}
    try:
        for role, model in role_models.items():
            api = model.api
            original = api.generate
            originals[role] = original

            async def bounded(input, tools, tool_choice, config, *,
                              _role=role, _model=model, _original=original):
                if observed and observed[-1]["status"] != "COMPLETE":
                    raise RemoteBoundaryError("BILATERAL030 prior model call not complete")
                try:
                    if tool_choice != "auto":
                        raise RemoteBoundaryError(
                            "BILATERAL030 model tool choice differs from ORBIT default")
                    identity = current_identity()
                    actor = identity.agent_id if identity is not None else None
                    if actor != _role:
                        raise RemoteBoundaryError("BILATERAL030 ORBIT actor differs from wrapped role")
                    tool_schema = _model.api.tools_to_openai(tools)
                    params = _model.api.completion_params(config, bool(tools))
                    boundary = validate_request(
                        row, role=actor, model_route=str(_model),
                        input_messages=input, tools=tools, config=config,
                        body=params, http_client_max_retries=_model.api.client.max_retries,
                        observed=observed, expected_system=expected_systems[actor],
                        expected_user=expected_user)
                except BaseException as exc:
                    observed.append({"call_index": len(observed) + 1,
                                     "role": _role, "status": "STOPPED",
                                     "provider_api_invoked": False,
                                     "error_type": type(exc).__name__})
                    raise
                item = {**boundary,
                        "source_only_no_network_forwarding": False,
                        "provider_api_invoked": True,
                        "network_forwarding": "UNOBSERVED",
                        "status": "IN_FLIGHT"}
                observed.append(item)
                try:
                    result = await _original(input, tools, tool_choice, config)
                except BaseException as exc:
                    item.update(status="STOPPED", error_type=type(exc).__name__)
                    raise
                if (not isinstance(result, tuple) or len(result) != 2
                        or not isinstance(result[1], ModelCall)
                        or not isinstance(result[0], (ModelOutput, Exception))):
                    item.update(status="STOPPED", error_type="ModelCallShapeError")
                    raise RemoteBoundaryError("BILATERAL030 adapter omitted ModelCall pair")
                output, call = result
                item["model_call_sha256"] = _raw_call_sha(call)
                try:
                    _raw_call_request(call, row=row, role=actor,
                                      expected_system=expected_systems[actor],
                                      expected_user=expected_user,
                                      tool_schema=tool_schema)
                except BaseException as exc:
                    item.update(status="STOPPED", error_type=type(exc).__name__,
                                model_call_on_failure=call.model_dump(mode="json"))
                    raise
                if isinstance(output, Exception):
                    item.update(status="STOPPED", error_type=type(output).__name__,
                                model_call_on_failure=call.model_dump(mode="json"))
                    # Inspect consumes its original (Exception, ModelCall) pair
                    # so the failed request remains in the raw EvalLog.
                    return result
                if (call.error or output.error is not None or call.response is None
                        or not isinstance(output.choices, list)
                        or len(output.choices) != 1
                        or output.choices[0].stop_reason in {"length", "max_tokens"}):
                    item.update(status="STOPPED", error_type="UnsuccessfulOrTruncatedOutput",
                                model_call_on_failure=call.model_dump(mode="json"))
                    raise RemoteBoundaryError(
                        "BILATERAL030 model output failed, truncated or lacks one choice")
                item["status"] = "COMPLETE"
                return result

            api.generate = bounded
        yield observed
    finally:
        for role, original in originals.items():
            role_models[role].api.generate = original
