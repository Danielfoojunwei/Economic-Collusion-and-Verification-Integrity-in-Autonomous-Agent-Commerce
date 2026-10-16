"""Adapt unscorable content-only completions to the zero-price text sanitizer.

The existing sanitizer still validates the exact route, usage, and cost. Only
the content field is normalized when the exact-route, single-choice message
envelope is present. Billing and malformed envelopes retain their stop rules.
"""

from __future__ import annotations

from typing import Any, Mapping

from . import free_collusion_probe as free


def _empty_unscorable_content(raw: Any, model_id: Any) -> Any:
    if not isinstance(raw, Mapping) or raw.get("model") != model_id or "error" in raw:
        return raw
    choices = raw.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], Mapping):
        return raw
    choice = choices[0]
    message = choice.get("message")
    if "error" in choice or not isinstance(message, Mapping) or "error" in message:
        return raw
    try:
        free._content(message.get("content"))
    except free.ProbeError:
        return {**raw, "choices": [{**choice, "message": {**message, "content": None}}]}
    else:
        return raw


def _has_api_error(raw: Any) -> bool:
    if not isinstance(raw, Mapping):
        return False
    if "error" in raw:
        return True
    choices = raw.get("choices")
    if not isinstance(choices, list):
        return False
    return any(isinstance(choice, Mapping) and (
        "error" in choice or (isinstance(choice.get("message"), Mapping)
                              and "error" in choice["message"])) for choice in choices)


class EmptyUnscorableContentTransport:
    """Preserve the transport's single POST and normalize only unscorable content."""

    def __init__(self, transport: Any):
        self._transport = transport

    def catalog(self) -> Any:
        return self._transport.catalog()

    def usage(self) -> Any:
        return self._transport.usage()

    def chat(self, request: Mapping[str, Any]) -> Any:
        raw = self._transport.chat(request)
        if _has_api_error(raw):
            raise free.ProbeError("model response contains API error")
        return _empty_unscorable_content(raw, request["model"])
