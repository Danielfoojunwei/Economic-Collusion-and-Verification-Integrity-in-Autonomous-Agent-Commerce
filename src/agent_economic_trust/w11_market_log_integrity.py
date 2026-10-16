"""Compare W11 runtime and archived Inspect decisions across attachment pooling.

Inspect may replace a long model tool argument with an ``attachment://``
reference in its native archive. Resolving that archive expands the argument;
byte-identical source and copied archives can therefore have different object
values from the in-memory EvalLog. Only that exact expansion is permitted.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from .remote import RemoteBoundaryError


def _behavior(log: Any) -> list[dict[str, Any]]:
    if not log.samples or len(log.samples) != 1:
        raise RemoteBoundaryError("W11 native comparison requires one Inspect sample")
    selected = []
    for event in log.samples[0].events:
        if event.event == "model":
            selected.append({
                "kind": "model", "model": event.model,
                "config": event.config.model_dump(mode="json") if event.config else None,
                "tools": [tool.model_dump(mode="json") for tool in event.tools or []],
                "output": event.output.model_dump(mode="json") if event.output else None,
            })
        elif event.event == "tool":
            selected.append({
                "kind": "tool", "function": event.function,
                "arguments": event.arguments,
                "result": str(event.result),
                "error": str(event.error) if event.error else None,
            })
    return selected


def _attachment_compatible(runtime: Any, unresolved: Any, resolved: Any) -> int:
    """Return expansion count or fail on any other behavior-bearing change."""
    if unresolved == resolved:
        if runtime != resolved:
            raise RemoteBoundaryError("W11 runtime behavior differs from native archive")
        return 0
    if isinstance(unresolved, dict) and isinstance(resolved, dict) and isinstance(runtime, dict):
        if not (unresolved.keys() == resolved.keys() == runtime.keys()):
            raise RemoteBoundaryError("W11 native behavior field set changed")
        return sum(_attachment_compatible(runtime[key], unresolved[key], resolved[key])
                   for key in unresolved)
    if isinstance(unresolved, list) and isinstance(resolved, list) and isinstance(runtime, list):
        if not (len(unresolved) == len(resolved) == len(runtime)):
            raise RemoteBoundaryError("W11 native behavior sequence changed")
        return sum(_attachment_compatible(actual, before, after)
                   for actual, before, after in zip(runtime, unresolved, resolved))
    if (isinstance(unresolved, str) and unresolved.startswith("attachment://")
            and isinstance(resolved, str) and "attachment://" not in resolved
            and runtime in (unresolved, resolved)):
        return 1
    raise RemoteBoundaryError("W11 native behavior changed outside attachment resolution")


def compare_market_native_log(runtime_log: Any, source_unresolved_log: Any,
                              source_resolved_log: Any, saved_resolved_log: Any,
                              *, source_path: Path, saved_path: Path) -> dict[str, Any]:
    """Verify exact archive copy and behavior, allowing only resolved attachments.

    A caller must still perform the role, truth, payment, model and secret audits
    on ``saved_resolved_log``. This check proves the saved archive matches the
    runtime result without comparing a pooled tool argument to expanded text.
    """
    source_digest = sha256(Path(source_path).read_bytes()).hexdigest()
    if source_digest != sha256(Path(saved_path).read_bytes()).hexdigest():
        raise RemoteBoundaryError("W11 copied native archive differs from Inspect source")
    logs = (runtime_log, source_unresolved_log, source_resolved_log, saved_resolved_log)
    if any(not log.samples or len(log.samples) != 1 for log in logs):
        raise RemoteBoundaryError("W11 native comparison requires one Inspect sample")
    runtime, unresolved, resolved, saved = (log.samples[0] for log in logs)
    if (len({log.status for log in logs}) != 1
            or len({log.eval.model for log in logs}) != 1
            or not (runtime.metadata == unresolved.metadata == resolved.metadata == saved.metadata)
            or not (runtime.store == unresolved.store == resolved.store == saved.store)
            or not (runtime.scores == unresolved.scores == resolved.scores == saved.scores)
            or not (len(runtime.events) == len(unresolved.events)
                    == len(resolved.events) == len(saved.events))):
        raise RemoteBoundaryError("W11 saved native summary differs from runtime result")
    unresolved_behavior = _behavior(source_unresolved_log)
    resolved_behavior = _behavior(source_resolved_log)
    if resolved_behavior != _behavior(saved_resolved_log):
        raise RemoteBoundaryError("W11 saved native behavior differs from source archive")
    expansions = _attachment_compatible(_behavior(runtime_log),
                                        unresolved_behavior, resolved_behavior)
    return {"native_archive_sha256": source_digest,
            "attachment_expansions": expansions,
            "behavior_events": len(resolved_behavior)}


def audit_saved_attachment_resolution(unresolved_log: Any,
                                      resolved_log: Any) -> dict[str, int]:
    """Read-only archive self-check for a historical run without runtime log."""
    before, after = _behavior(unresolved_log), _behavior(resolved_log)
    expansions = _attachment_compatible(before, before, after)
    return {"attachment_expansions": expansions, "behavior_events": len(after)}
