"""Fail-closed comparison of assigned message with normalized model requests.

The caller must independently extract *actual serialized* predecision model
requests. Constructing these records from planned prompts is not exposure.
"""
from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping, Sequence


def message_hash(message: str) -> str:
    if not isinstance(message, str) or not message:
        raise ValueError("nonempty exact provider message required")
    return sha256(message.encode("utf-8")).hexdigest()


def audit_exposure(
    requests: Sequence[Mapping[str, Any]], *, provider_message: str,
    contact_assigned: bool, decision_call_index: int,
) -> dict[str, Any]:
    """Find the exact accepted-offer message in a predecision tool input.

    `requests` is the auditor's serialized sequence of model-call envelopes.
    Each envelope has `messages` with role/content. A tool content is JSON and
    may contain `accepted_offer.provider_message`. The exact value, not a
    substring or a provider-side log, establishes exposure.
    """
    if type(contact_assigned) is not bool or type(decision_call_index) is not int:
        raise ValueError("contact and decision index require explicit types")
    if not 0 <= decision_call_index < len(requests):
        raise ValueError("decision call index outside serialized requests")
    target = message_hash(provider_message)
    exposed_at: list[int] = []
    misplaced_at: list[int] = []
    for call_index, request in enumerate(requests):
        messages = request.get("messages")
        if not isinstance(messages, list):
            raise ValueError("actual request messages are required")
        for message in messages:
            if not isinstance(message, dict) or message.get("role") not in {
                "system", "developer", "user", "assistant", "tool"
            } or not isinstance(message.get("content"), str):
                raise ValueError("malformed serialized request message")
            content = message["content"]
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                payload = None
            offer = payload.get("accepted_offer") if isinstance(payload, dict) else None
            exact = (isinstance(offer, dict) and
                     offer.get("provider_message") == provider_message)
            if exact:
                if message["role"] == "tool" and call_index <= decision_call_index:
                    exposed_at.append(call_index)
                else:
                    misplaced_at.append(call_index)
            elif (target == sha256(content.encode("utf-8")).hexdigest()
                  or provider_message in content):
                misplaced_at.append(call_index)
    if misplaced_at:
        raise ValueError("provider text appears outside the accepted-offer tool field")
    if contact_assigned != bool(exposed_at):
        raise ValueError("actual exposure differs from assigned contact")
    return {"exposed": bool(exposed_at), "message_sha256": target,
            "predecision_call_indices": sorted(set(exposed_at))}
