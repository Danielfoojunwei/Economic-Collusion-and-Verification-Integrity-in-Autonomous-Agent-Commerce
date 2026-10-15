"""Blocked, reproducible W11 intervention assignments; no agents are run here.

The market is the randomization unit. Each market has disjoint identities,
which prevents a relationship treatment in one market from spilling into a
control market through a reused agent identity. Intervention task order is
identical across arms within a block. This schedule makes access restrictions
explicit; the later runtime must actually enforce and log them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from random import Random
from typing import Sequence


ARMS = (
    "REPEAT_DIRECT",
    "REPEAT_NO_DIRECT",
    "TURNOVER_DIRECT",
    "TURNOVER_NO_DIRECT",
    "CROSSOVER_NO_DIRECT",
)
DIRECT_CHANNEL_TOOLS = frozenset({"channel_post", "channel_read", "channel_list"})
NO_DIRECT_FORBIDDEN_TOOLS = DIRECT_CHANNEL_TOOLS | frozenset({
    "secret_channel", "post_message", "read_messages", "list_boards", "handoff",
})


@dataclass(frozen=True)
class MarketAssignment:
    market_id: str
    block_id: str
    arm: str
    phase: str
    round_index: int
    task_id: str
    episode_id: str
    provider_id: str
    verifier_id: str
    pair_id: str
    communication_mode: str
    provider_visible_prior_episode_ids: tuple[str, ...]
    verifier_visible_prior_episode_ids: tuple[str, ...]
    randomization_unit: str = "market"


def build_market_schedule(
    *, seed: int, task_ids: Sequence[str], blocks: int = 1,
    baseline_rounds: int = 2, intervention_rounds: int = 2,
) -> tuple[MarketAssignment, ...]:
    """Assign five matched arms per block, then schedule baseline and follow-up.

    A turnover auditor is a new identity with no prior pair history. Crossover
    swaps the original roles; it is a mechanism probe, not a clean effect of
    financial dependence. Direct/no-direct access is specified per round.
    """
    if type(seed) is not int or type(blocks) is not int or blocks < 1:
        raise ValueError("seed must be an integer and blocks must be positive")
    if type(baseline_rounds) is not int or baseline_rounds < 1:
        raise ValueError("baseline_rounds must be positive")
    if type(intervention_rounds) is not int or intervention_rounds < 1:
        raise ValueError("intervention_rounds must be positive")
    rounds = baseline_rounds + intervention_rounds
    if len(task_ids) != rounds or any(not isinstance(x, str) or not x for x in task_ids):
        raise ValueError("one nonempty frozen task ID is required per round")
    if len(set(task_ids)) != rounds:
        raise ValueError("round task IDs must be distinct")
    rng = Random(seed)
    schedule: list[MarketAssignment] = []
    for block in range(blocks):
        arms = list(ARMS)
        rng.shuffle(arms)
        block_id = f"block-{block:03d}"
        for slot, arm in enumerate(arms):
            market_id = f"{block_id}-market-{slot:02d}"
            original_provider = f"{market_id}-provider-A"
            original_verifier = f"{market_id}-verifier-A"
            fresh_verifier = f"{market_id}-verifier-B"
            identity_history: dict[str, list[str]] = {
                original_provider: [], original_verifier: [], fresh_verifier: [],
            }
            for round_index, task_id in enumerate(task_ids):
                baseline = round_index < baseline_rounds
                if baseline or arm.startswith("REPEAT_"):
                    provider, verifier = original_provider, original_verifier
                elif arm.startswith("TURNOVER_"):
                    provider, verifier = original_provider, fresh_verifier
                else:
                    provider, verifier = original_verifier, original_provider
                direct = baseline or arm in {"REPEAT_DIRECT", "TURNOVER_DIRECT"}
                episode_id = f"{market_id}-round-{round_index:02d}"
                schedule.append(MarketAssignment(
                    market_id=market_id, block_id=block_id, arm=arm,
                    phase="BASELINE" if baseline else "INTERVENTION",
                    round_index=round_index, task_id=task_id, episode_id=episode_id,
                    provider_id=provider, verifier_id=verifier,
                    pair_id="|".join(sorted((provider, verifier))),
                    communication_mode="DIRECT" if direct else "NONE",
                    provider_visible_prior_episode_ids=tuple(identity_history[provider]),
                    verifier_visible_prior_episode_ids=tuple(identity_history[verifier]),
                ))
                identity_history[provider].append(episode_id)
                identity_history[verifier].append(episode_id)
    return tuple(schedule)


def schedule_sha256(schedule: Sequence[MarketAssignment]) -> str:
    """Stable hash for a frozen assignment manifest; not a signature."""
    payload = [asdict(row) for row in schedule]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(canonical.encode()).hexdigest()


def assert_native_channel_adherence(
    assignment: MarketAssignment, sample: object, *,
    provider_agent_name: str, verifier_agent_name: str,
) -> dict[str, int]:
    """Verify actual Inspect tool grants/calls against a communication arm.

    A no-channel prompt is insufficient: ORBIT may still offer its default
    channel tools. Call this on the saved native Inspect sample, not only on a
    condensed event export. The runtime must grant or remove tools accordingly.
    """
    if getattr(sample, "id", None) != assignment.task_id:
        raise ValueError("native sample task does not match assignment")
    if not provider_agent_name or not verifier_agent_name or provider_agent_name == verifier_agent_name:
        raise ValueError("distinct native agent span names are required")
    events = getattr(sample, "events", None)
    if not isinstance(events, (list, tuple)):
        raise ValueError("native Inspect events are missing")
    spans = {event.id: event for event in events if getattr(event, "event", None) == "span_begin"}

    def agent_name(event: object) -> str | None:
        span_id = getattr(event, "span_id", None)
        visited: set[str] = set()
        while span_id is not None and span_id not in visited:
            visited.add(span_id)
            span = spans.get(span_id)
            if span is None:
                return None
            if getattr(span, "type", None) == "agent":
                return getattr(span, "name", None)
            span_id = getattr(span, "parent_id", None)
        return None

    roles = {provider_agent_name: "provider", verifier_agent_name: "verifier"}
    model_counts = {"provider": 0, "verifier": 0}
    channel_calls = 0
    for event in events:
        kind = getattr(event, "event", None)
        if kind not in {"model", "tool"}:
            continue
        actor = agent_name(event)
        if actor not in roles:
            raise ValueError("model/tool event lacks an assigned agent span")
        if kind == "model":
            model_counts[roles[actor]] += 1
            offered = {tool.name for tool in getattr(event, "tools", ())}
            if assignment.communication_mode == "NONE" and offered & NO_DIRECT_FORBIDDEN_TOOLS:
                raise ValueError("no-channel model was offered a channel capability")
            if assignment.communication_mode == "DIRECT" and not DIRECT_CHANNEL_TOOLS.issubset(offered):
                raise ValueError("direct-channel model lacks an expected channel capability")
        elif getattr(event, "function", None) in NO_DIRECT_FORBIDDEN_TOOLS:
            channel_calls += 1
            if assignment.communication_mode == "NONE":
                raise ValueError("no-channel arm executed a channel tool")
    if not all(model_counts.values()):
        raise ValueError("both assigned roles need native model events")
    return {"provider_model_events": model_counts["provider"],
            "verifier_model_events": model_counts["verifier"],
            "channel_tool_calls": channel_calls}
