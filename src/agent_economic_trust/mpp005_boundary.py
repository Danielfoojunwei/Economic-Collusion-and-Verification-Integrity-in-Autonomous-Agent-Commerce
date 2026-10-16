"""MPP005-only remote request and evidence boundary.

Keeping these small controls local makes the frozen source closure independent
of the earlier invoice experiments.
"""
from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
import zipfile

from inspect_ai.model import ContentReasoning

from .mpp005_plan import canonical


REQUEST_TIMEOUT_SECONDS = 180


class RemoteBoundaryError(RuntimeError):
    """A local spend, model request, or evidence boundary stopped execution."""


def account_usage_usd() -> Decimal:
    credential = os.environ.get("OPENROUTER_API_KEY")
    if not credential:
        raise RemoteBoundaryError("OpenRouter account credential is missing")
    request = Request("https://openrouter.ai/api/v1/auth/key",
        headers={"Authorization": f"Bearer {credential}", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=15) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("oversized account response")
        parsed = json.loads(raw, parse_float=Decimal)
        amount = parsed["data"]["usage"]
        if isinstance(amount, bool) or not isinstance(amount, (str, int, float, Decimal)):
            raise ValueError("account usage is not numeric")
        value = Decimal(str(amount))
        if not value.is_finite() or value < 0:
            raise ValueError("account usage is invalid")
        return value
    except Exception as exc:
        raise RemoteBoundaryError("OpenRouter account usage is unavailable") from exc


def account_usage_delta_usd(before: Decimal, after: Decimal) -> Decimal:
    if after < before:
        raise RemoteBoundaryError("OpenRouter account usage counter decreased")
    return after - before


def _safe_model_input_size(input: Any, tools: Any) -> int:
    def encode(value: Any) -> Any:
        return value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    return len(json.dumps({"input": [encode(value) for value in input],
        "tools": [encode(value) for value in tools]}, default=str,
        ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _usage_for(log: Any, model_id: str) -> Any:
    if not log.samples or len(log.samples) != 1:
        raise RemoteBoundaryError("one Inspect sample with usage is required")
    usage = log.samples[0].model_usage
    if not usage or len(usage) != 1:
        raise RemoteBoundaryError("provider usage is absent or ambiguous")
    name, value = next(iter(usage.items()))
    if not name.endswith(model_id):
        raise RemoteBoundaryError("provider usage model differs from approved ID")
    if value.total_tokens <= 0 or value.output_tokens < 0 or value.input_tokens < 0:
        raise RemoteBoundaryError("provider token accounting is incomplete")
    return value


def file_sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("evidence must be a regular file")
    return sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    raw = canonical(value) + b"\n"
    secret = os.environ.get("OPENROUTER_API_KEY", "")
    if secret and secret.encode() in raw:
        raise RemoteBoundaryError("credential detected in saved record")
    with path.open("xb") as handle:
        os.chmod(path, 0o600)
        handle.write(raw)


def assert_no_key(path: Path) -> None:
    secret = os.environ.get("OPENROUTER_API_KEY", "")
    if not secret:
        return
    needle = secret.encode()
    if needle in path.read_bytes():
        raise RemoteBoundaryError("credential detected in evidence")
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            if any(needle in archive.read(name) for name in archive.namelist()):
                raise RemoteBoundaryError("credential detected inside Inspect archive")


def guard_api(model: Any, plan: Any) -> list[dict]:
    """Enforce bounds on every actual forwarded OpenRouter request."""
    observed: list[dict] = []
    original = model.api.generate

    async def bounded(input: Any, tools: Any, tool_choice: Any, config: Any) -> Any:
        size = _safe_model_input_size(input, tools)
        reasoning = any(isinstance(part, ContentReasoning)
                        for message in input for part in
                        (message.content if isinstance(message.content, list) else []))
        if (len(observed) >= plan.max_calls or size > plan.max_input_bytes or reasoning
                or config.reasoning_effort != "high" or config.reasoning_history != "none"
                or config.max_tokens != plan.max_output_tokens or config.max_retries != 0):
            raise RemoteBoundaryError("MPP005 actual provider input exceeded frozen controls")
        item = {"call_index": len(observed) + 1, "serialized_input_bytes": size,
                "provider_api_invoked": True, "network_forwarding": "UNOBSERVED", "completed": False}
        observed.append(item)
        result = await original(input, tools, tool_choice, config)
        item["completed"] = True
        return result
    model.api.generate = bounded
    return observed


def verify_model_boundary(log: Any, observed: list[dict], plan: Any) -> None:
    config = log.eval.model_generate_config
    if (log.eval.model != f"openrouter/{plan.model_id}" or config is None
            or config.reasoning_effort != "high" or config.reasoning_history != "none"
            or config.max_retries != 0 or config.max_tokens != plan.max_output_tokens
            or not log.samples or len(log.samples) != 1):
        raise RemoteBoundaryError("saved Inspect model/config differs")
    events = [event for event in log.samples[0].events if event.event == "model"]
    if not events or len(events) != len(observed) or len(events) > plan.max_calls:
        raise RemoteBoundaryError("saved model events differ from actual calls")
    for index, (event, actual) in enumerate(zip(events, observed, strict=True)):
        config = event.config
        if (event.model != f"openrouter/{plan.model_id}" or event.error or event.cache is not None
                or event.retries not in (None, 0) or config.reasoning_effort != "high"
                or config.reasoning_history != "none" or config.max_retries != 0
                or config.max_tokens != plan.max_output_tokens
                or actual != {"call_index": index + 1,
                    "serialized_input_bytes": _safe_model_input_size(event.input, event.tools),
                    "provider_api_invoked": True, "network_forwarding": "UNOBSERVED", "completed": True}
                or actual["serialized_input_bytes"] > plan.max_input_bytes
                or any(isinstance(part, ContentReasoning) for message in event.input
                       for part in (message.content if isinstance(message.content, list) else []))):
            raise RemoteBoundaryError("saved model request violates frozen boundary")
