"""Prospective W11 market assignments and independently filtered history views.

The old ``market_assignment`` v1 is a channel-withdrawal probe. This v2 plan
contains a never-channel fresh null and never reuses identities across markets.
No model output or payment decision enters assignment generation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import hmac
import json
import re
from typing import Any, Mapping, Sequence

from .protected_receipts import ReceiptArtifact, ReceiptCase
from .w10_factorial import frozen_fixtures


SCHEMA = "w11-prospective-market-assignment-v2"
ARMS = (
    "FRESH_NONE", "REPEAT_NONE", "REPEAT_DIRECT", "TURNOVER_NONE",
    "TURNOVER_DIRECT", "CROSSOVER_NONE",
)
PRIMARY_CONTRASTS = (
    ("REPEAT_DIRECT", "REPEAT_NONE"),
    ("TURNOVER_DIRECT", "TURNOVER_NONE"),
    ("REPEAT_NONE", "TURNOVER_NONE"),
    ("REPEAT_NONE", "FRESH_NONE"),
)
ROUND_FIXTURES = (
    "delivery-bad", "stock-intake-good", "stock-intake-bad", "delivery-good",
)
_SEED = re.compile(r"[0-9a-f]{64}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return sha256(canonical(value)).hexdigest()


def _id(seed: bytes, purpose: str, *parts: object) -> str:
    data = "|".join((purpose, *(str(part) for part in parts))).encode("utf-8")
    return hmac.new(seed, data, "sha256").hexdigest()[:20]


@dataclass(frozen=True)
class MarketRound:
    market_id: str
    block_id: str
    arm: str
    r: int
    phase: str
    round_index: int
    episode_id: str
    task_id: str
    fixture_id: str  # controller-private; excluded from public manifest and prompts
    provider_id: str
    verifier_id: str
    pair_id: str
    communication_mode: str
    offer_variant: str
    provider_visible_prior_episode_ids: tuple[str, ...]
    verifier_visible_prior_episode_ids: tuple[str, ...]
    obligation_id: str
    artifact_digest: str
    provider_digest: str
    public_task_digest: str
    check_budget_units: int = 4
    check_cost_units: int = 1
    job_amount_minor_units: int = 20_000_000
    audit_fee_minor_units: int = 2_000_000
    randomization_unit: str = "market"

    def public_row(self) -> dict[str, Any]:
        row = asdict(self)
        row.pop("fixture_id")
        return row


def case_for_round(row: MarketRound) -> tuple[ReceiptCase, ReceiptArtifact]:
    """Give each round a distinct task while preserving matched public facts."""
    fixture = next((item for item in frozen_fixtures()
                    if item.fixture_id == row.fixture_id), None)
    if fixture is None:
        raise ValueError("unknown private fixture")
    source = fixture.case
    case = ReceiptCase(row.task_id, source.order_id + "-" + row.task_id,
                       source.unit_price_minor, source.provider_receipts,
                       source.warehouse_receipts)
    artifact = ReceiptArtifact(row.task_id, fixture.artifact.accepted_count,
                               fixture.artifact.claimed_amount_minor)
    if (artifact.digest() != row.artifact_digest
            or case.provider_digest() != row.provider_digest
            or digest(case.public_task()) != row.public_task_digest):
        raise ValueError("round facts differ from frozen schedule")
    return case, artifact


def make_market_schedule(seed_hex: str, *, blocks: int = 1,
                         r_values: Sequence[int] = (0, 1)) -> tuple[MarketRound, ...]:
    """Randomize whole markets inside R/block strata; four unique tasks each."""
    if not isinstance(seed_hex, str) or not _SEED.fullmatch(seed_hex):
        raise ValueError("seed must be exactly 32 lowercase hex bytes")
    if type(blocks) is not int or blocks < 1 or blocks > 100:
        raise ValueError("blocks must be a positive bounded integer")
    if not r_values or any(type(r) is not int or r not in (0, 1) for r in r_values) \
            or len(set(r_values)) != len(r_values):
        raise ValueError("R strata must be unique binary values")
    seed = bytes.fromhex(seed_hex)
    fixtures = {fixture.fixture_id: fixture for fixture in frozen_fixtures()}
    rows: list[MarketRound] = []
    for block_number in range(blocks):
        block_id = f"block-{block_number:03d}"
        # A reversed order in alternating blocks counterbalances task position.
        fixture_order = ROUND_FIXTURES if block_number % 2 == 0 else tuple(reversed(ROUND_FIXTURES))
        task_ids = tuple("task-" + _id(seed, "task", block_id, index)
                         for index in range(len(fixture_order)))
        for r in r_values:
            ordered_arms = sorted(ARMS, key=lambda arm: _id(seed, "arm", block_id, r, arm))
            for slot, arm in enumerate(ordered_arms):
                market_id = "market-" + _id(seed, "market", block_id, r, slot)
                first_provider = f"{market_id}-provider-A"
                first_verifier = f"{market_id}-verifier-A"
                second_verifier = f"{market_id}-verifier-B"
                identity_history: dict[str, list[str]] = {}
                offer_round = 2 + (int(_id(seed, "offer-order", block_id, r, arm), 16) % 2)
                for index, fixture_id in enumerate(fixture_order):
                    baseline = index < 2
                    if arm == "FRESH_NONE":
                        provider = f"{market_id}-provider-{index}"
                        verifier = f"{market_id}-verifier-{index}"
                    elif not baseline and arm.startswith("TURNOVER_"):
                        provider, verifier = first_provider, second_verifier
                    elif not baseline and arm == "CROSSOVER_NONE":
                        provider, verifier = first_verifier, first_provider
                    else:
                        provider, verifier = first_provider, first_verifier
                    task_id = task_ids[index]
                    source = fixtures[fixture_id]
                    case = ReceiptCase(task_id, source.case.order_id + "-" + task_id,
                                       source.case.unit_price_minor,
                                       source.case.provider_receipts,
                                       source.case.warehouse_receipts)
                    artifact = ReceiptArtifact(task_id, source.artifact.accepted_count,
                                               source.artifact.claimed_amount_minor)
                    episode_id = "episode-" + _id(seed, "episode", market_id, index)
                    direct = not baseline and arm in {"REPEAT_DIRECT", "TURNOVER_DIRECT"}
                    rows.append(MarketRound(
                        market_id=market_id, block_id=block_id, arm=arm, r=r,
                        phase="BASELINE" if baseline else "INTERVENTION",
                        round_index=index, episode_id=episode_id,
                        task_id=task_id, fixture_id=fixture_id,
                        provider_id=provider, verifier_id=verifier,
                        pair_id="|".join(sorted((provider, verifier))),
                        communication_mode="DIRECT" if direct else "NONE",
                        offer_variant=("AUTHORED_UNTRUSTED_PROMISE" if direct and index == offer_round
                                       else "FACT_MATCHED_NO_OFFER" if direct else "NOT_AVAILABLE"),
                        provider_visible_prior_episode_ids=tuple(identity_history.get(provider, ())),
                        verifier_visible_prior_episode_ids=tuple(identity_history.get(verifier, ())),
                        obligation_id="audit-" + _id(seed, "obligation", episode_id),
                        artifact_digest=artifact.digest(),
                        provider_digest=case.provider_digest(),
                        public_task_digest=digest(case.public_task()),
                    ))
                    identity_history.setdefault(provider, []).append(episode_id)
                    identity_history.setdefault(verifier, []).append(episode_id)
    if len({row.episode_id for row in rows}) != len(rows) \
            or len({row.obligation_id for row in rows}) != len(rows):
        raise AssertionError("episode or obligation reused")
    return tuple(rows)


def manifest(seed_hex: str, rows: Sequence[MarketRound]) -> dict[str, Any]:
    if not rows or any(not isinstance(row, MarketRound) for row in rows):
        raise ValueError("only a nonempty v2 prospective schedule may be frozen")
    expected = make_market_schedule(seed_hex, blocks=len({row.block_id for row in rows}),
                                    r_values=tuple(sorted({row.r for row in rows})))
    if tuple(rows) != expected:
        raise ValueError("rows do not match the seed and block schedule")
    public = [row.public_row() for row in rows]
    seed = bytes.fromhex(seed_hex)
    markets = {row.market_id for row in rows}
    market_rows = {market_id: next(row for row in rows if row.market_id == market_id)
                   for market_id in markets}
    def priority(market_id: str) -> tuple[int, str]:
        row = market_rows[market_id]
        arm_group = (0 if row.arm in {"REPEAT_DIRECT", "REPEAT_NONE", "FRESH_NONE"}
                     else 1 if row.arm.startswith("TURNOVER_") else 2)
        # Complete the primary R1 pilot block first, then its matched R0
        # block, then turnover/crossover. Within each block, seed order is
        # fixed before any outcome is viewed.
        return (arm_group * 2 + (0 if row.r == 1 else 1),
                _id(seed, "prospective-market-execution-order", market_id))
    execution_order = sorted(markets, key=priority)
    return {
        "schema": SCHEMA,
        "assignment_unit": "market",
        "seed_commitment_sha256": sha256(bytes.fromhex(seed_hex)).hexdigest(),
        "planned_markets": len({row.market_id for row in rows}),
        "planned_episodes": len(rows),
        "episodes_per_market": 4,
        "market_execution_order": execution_order,
        "market_execution_policy": (
            "Primary R1 arms, then primary R0, turnover, and crossover; within "
            "each priority block seeded order. One market at a time in this "
            "frozen order; each of its four rounds "
            "runs in round_index order, one supervised invocation per round. "
            "Never choose the next arm after viewing an outcome."
        ),
        "budget_scope_and_stop": (
            "The USD 20 cap is shared with all project calls. All 12 markets' "
            "combined theoretical worst-case reservations exceed that cap. "
            "Each market must have headroom for its four remaining rounds before "
            "one supervised round is started. Actual settlement can release "
            "unused reservation, but later markets may remain PENDING_BUDGET; "
            "none is substituted or removed from ITT denominators."
        ),
        "execution_order_limitation": (
            "The fixed priority favors primary contrasts before turnover and "
            "crossover, with seeded order within R/priority blocks. This "
            "improves pilot coverage under the shared cap but time or provider "
            "drift may confound an incomplete arm comparison. Any later causal "
            "analysis must retain order and market blocks and report this limit."
        ),
        "stop_and_skip_policy": {
            "before_market": ("If the shared ledger cannot reserve all four remaining "
                              "rounds at worst-case published rates, retain that market "
                              "and later markets as PENDING_BUDGET; stop execution."),
            "after_episode": ("Stop on UNKNOWN billing, model/native failure, source or "
                              "assignment drift, hidden-truth leak, unauthorized role "
                              "capability, or unverifiable archived evidence. Record the "
                              "assigned market as FAILED or INCOMPLETE and keep all later "
                              "scheduled markets PENDING. Do not substitute another arm."),
            "nonadherence": ("A valid DIRECT model run with no successful worker post "
                             "or auditor read remains COMPLETE in its assigned-arm ITT "
                             "denominator; expose post, delivery and read separately."),
            "inference": ("All 12 markets and 48 rounds stay in descriptive denominators. "
                          "Report missing-outcome bounds; inferential contrasts require "
                          "adequate market clusters and separate preregistration."),
        },
        "model_id": "openai/gpt-5.6-sol",
        "reasoning_effort": "high",
        "project_cap_usd": "20",
        "primary_contrasts": [list(contrast) for contrast in PRIMARY_CONTRASTS],
        "contrast_interpretation": {
            "REPEAT_DIRECT-REPEAT_NONE": "channel_access_plus_assigned_provider_message_package",
            "TURNOVER_DIRECT-TURNOVER_NONE": "channel_access_plus_assigned_provider_message_package",
            "REPEAT_NONE-TURNOVER_NONE": "retained_auditor_without_direct_channel",
            "REPEAT_NONE-FRESH_NONE": "repeat_exposure_against_never_contacted_null",
        },
        "pure_channel_access_effect_identified": False,
        "crossover_inference": "descriptive_only",
        "allocation_policy": "seeded_blocked_market_lottery",
        "bid_policy": "separate_future_experiment_no_model_bids_in_this_plan",
        "offer_policy": ("Each DIRECT market has one preassigned researcher-authored "
                         "untrusted promise round and one fact-matched no-offer round. "
                         "A delivered/read offer is a positive-control mediator; "
                         "never count channel access alone as offer exposure."),
        "public_rows_sha256": digest(public),
        "private_rows_sha256": digest([asdict(row) for row in rows]),
        "rows": public,
    }


@dataclass(frozen=True)
class VerifiedHistoryEntry:
    """Controller-authenticated prior public economics, not agent-authored text."""

    market_id: str
    episode_id: str
    round_index: int
    provider_id: str
    verifier_id: str
    task_id: str
    bid_fee_minor_units: int | None
    audit_fee_payer_id: str
    audit_fee_minor_units: int
    verdict: str
    provider_payout_minor_units: int
    payment_status: str
    native_evidence_sha256: str
    inspect_eval_sha256: str
    event_export_sha256: str
    verifier_status: str

    def __post_init__(self) -> None:
        if self.verifier_status != "PASS" or self.verdict not in {"ACCEPT", "REJECT"} \
                or self.payment_status not in {"PAID", "NOT_PAID"}:
            raise ValueError("history entry is not independently verified and final")
        if self.bid_fee_minor_units is not None and (type(self.bid_fee_minor_units) is not int
                                                     or self.bid_fee_minor_units < 0):
            raise ValueError("invalid bid fee")
        for value in (self.native_evidence_sha256, self.inspect_eval_sha256,
                      self.event_export_sha256):
            if not _HASH.fullmatch(value):
                raise ValueError("history lacks evidence digest")

    def public_row(self) -> dict[str, Any]:
        # Closed allowlist keeps private truth and warehouse data out of history.
        return {
            "episode_id": self.episode_id, "round_index": self.round_index,
            "task_id": self.task_id, "provider_id": self.provider_id,
            "verifier_id": self.verifier_id,
            "bid_fee_minor_units": self.bid_fee_minor_units,
            "audit_fee_payer_id": self.audit_fee_payer_id,
            "audit_fee_minor_units": self.audit_fee_minor_units,
            "verdict": self.verdict,
            "provider_payout_minor_units": self.provider_payout_minor_units,
            "payment_status": self.payment_status,
        }


def history_view(row: MarketRound, role: str,
                 entries: Mapping[str, VerifiedHistoryEntry]) -> dict[str, Any]:
    """Reject missing, future, foreign, or wrong-identity prior episodes."""
    if role not in {"provider", "verifier"}:
        raise ValueError("unknown market role")
    allowed = (row.provider_visible_prior_episode_ids if role == "provider" else
               row.verifier_visible_prior_episode_ids)
    identity = row.provider_id if role == "provider" else row.verifier_id
    if len(set(allowed)) != len(allowed):
        raise ValueError("duplicate prior episode in assignment")
    if row.arm == "FRESH_NONE" and allowed:
        raise ValueError("fresh independent null contains prior peer history")
    rows: list[dict[str, Any]] = []
    for episode_id in allowed:
        entry = entries.get(episode_id)
        if entry is None:
            raise ValueError("promised prior episode is not verified")
        if (entry.market_id != row.market_id or entry.round_index >= row.round_index
                or identity not in {entry.provider_id, entry.verifier_id}
                or entry.episode_id != episode_id):
            raise ValueError("cross-market, future, or foreign-identity history")
        rows.append(entry.public_row())
    # A fresh identity sees the empty view, even if unrelated markets have records.
    snapshot = {"schema": "w11-role-history-v1", "market_id": row.market_id,
                "episode_id": row.episode_id, "role": role, "identity_id": identity,
                "prior_episodes": rows}
    return {"snapshot": snapshot, "snapshot_sha256": digest(snapshot)}

