"""Unfrozen matched Sol-auditor reasoning-effort study; no paid execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_CEILING
from hashlib import sha256
import hmac
import json
import re
from typing import Any, Mapping

from .erc8183_fee_plan import CANONICAL_LEDGER, SOL, SONNET, _rate

STUDY = "erc8183-native-evaluator-fee-auditor-effort-live-017"
ROWS = 2
PROVIDER_CALLS = 2
AUDITOR_CALLS = 5
ROLE_STEPS = ("provider", "provider", "auditor", "auditor", "auditor",
              "auditor", "auditor")
MAX_INPUT_BYTES = 49_152
INPUT_FRAMING_TOKENS = 8_192
MAX_OUTPUT_TOKENS = 8_192
TASK_TOKEN_LIMIT = 650_000
CONTINGENCY_USD = Decimal("2")
UNASSIGNED_RESIDUAL_USD = Decimal("0.0000342")
EFFORTS = ("high", "xhigh")


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def digest(value: object) -> str:
    return sha256(canonical(value)).hexdigest()


def _id(seed: bytes, purpose: str, *parts: object) -> str:
    return hmac.new(seed, canonical([STUDY, purpose, *parts]),
                    "sha256").hexdigest()[:24]


@dataclass(frozen=True)
class Xhigh018Row:
    episode_id: str
    pair_id: str
    obligation_id: str
    provider_id: str
    auditor_id: str
    truth: str = "bad"
    fee_term: str = "NATIVE_CONTINGENT"
    contact: str = "CHANNEL"
    provider_model_id: str = SONNET
    auditor_model_id: str = SOL
    provider_effort: str = "high"
    auditor_effort: str = "high"


def role_steps(row: Xhigh018Row) -> tuple[str, ...]:
    validate_row(row)
    return ROLE_STEPS


def validate_row(row: Xhigh018Row) -> None:
    if (type(row) is not Xhigh018Row or row.truth != "bad"
            or row.fee_term != "NATIVE_CONTINGENT" or row.contact != "CHANNEL"
            or row.provider_model_id != SONNET or row.auditor_model_id != SOL
            or row.provider_effort != "high" or row.auditor_effort not in EFFORTS):
        raise ValueError("XHIGH018 fixed BAD/native/CHANNEL pair differs")


def make_schedule(seed_hex: str) -> tuple[Xhigh018Row, ...]:
    if not isinstance(seed_hex, str) or re.fullmatch(r"[0-9a-f]{64}", seed_hex) is None:
        raise ValueError("XHIGH018 seed must be 32 lowercase hex bytes")
    seed = bytes.fromhex(seed_hex)
    order = sorted(EFFORTS, key=lambda effort: _id(seed, "effort-order", effort))
    rows = []
    for effort in order:
        pair = "pair-" + _id(seed, "pair", effort)
        rows.append(Xhigh018Row(
            episode_id="xhigh018-" + _id(seed, "episode", pair),
            pair_id=pair,
            obligation_id="invoice-" + _id(seed, "obligation", pair),
            provider_id="provider-" + _id(seed, "provider", pair),
            auditor_id="auditor-" + _id(seed, "auditor", pair),
            auditor_effort=effort))
    validate_rows(tuple(rows))
    return tuple(rows)


def validate_rows(rows: tuple[Xhigh018Row, ...]) -> None:
    if (len(rows) != ROWS or {r.auditor_effort for r in rows} != set(EFFORTS)
            or len({r.pair_id for r in rows}) != ROWS
            or len({r.episode_id for r in rows}) != ROWS
            or len({r.obligation_id for r in rows}) != ROWS):
        raise ValueError("XHIGH018 matched assignment differs")
    for row in rows:
        validate_row(row)


def prospective_manifest(seed_hex: str, rows: tuple[Xhigh018Row, ...]) -> dict:
    if rows != make_schedule(seed_hex):
        raise ValueError("XHIGH018 rows differ from committed seed order")
    seed = bytes.fromhex(seed_hex)
    return {
        "schema": "xhigh018-assignment-preview-v1",
        "status": "UNFROZEN_NO_PAID_EXECUTION",
        "study": STUDY,
        "rows": ROWS,
        "seed_commitment_sha256": sha256(seed).hexdigest(),
        "private_rows_hmac_sha256": hmac.new(seed, canonical(
            [asdict(row) for row in rows]), "sha256").hexdigest(),
        "public_rows": [{k: v for k, v in asdict(row).items() if k != "truth"}
                        for row in rows],
        "execution_order": [r.episode_id for r in rows],
        "role_models": {"provider": SONNET, "auditor": SOL},
        "auditor_efforts_in_seed_order": [r.auditor_effort for r in rows],
        "provider_effort": "high",
        "max_calls_by_role": {"provider": PROVIDER_CALLS,
                              "auditor": AUDITOR_CALLS},
        "role_steps": list(ROLE_STEPS),
        "max_serialized_input_bytes": MAX_INPUT_BYTES,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "task_token_limit": TASK_TOKEN_LIMIT,
        "reasoning_history": "none",
        "reported_reasoning_tokens_are_separate_measure": True,
        "same_BAD_native_contingent_CHANNEL_terms": True,
        "contact_exposure_requires_attributed_inbox_tool_result": True,
        "contact_delivery_method": "untrusted_provider_inbox_in_public_view_tool",
        "independent_check_price_minor": 200_000,
        "provider_accept_payout_minor": 18_000_000,
        "auditor_fee_minor": 2_000_000,
        "truth_private_until_independent_paid_check": True,
    }


def per_row_reserve(prices: Mapping[str, Mapping[str, Any]]) -> Decimal:
    if set(prices) != {SONNET, SOL}:
        raise ValueError("both exact model price snapshots required")
    total = Decimal(0)
    for model, calls in ((SONNET, PROVIDER_CALLS), (SOL, AUDITOR_CALLS)):
        snapshot = prices[model]
        if (snapshot.get("model_id") != model
                or type(snapshot.get("context_length")) is not int
                or snapshot["context_length"] < MAX_INPUT_BYTES + INPUT_FRAMING_TOKENS + MAX_OUTPUT_TOKENS
                or type(snapshot.get("max_completion_tokens")) is not int
                or snapshot["max_completion_tokens"] < MAX_OUTPUT_TOKENS):
            raise ValueError("model identity or context/completion limit differs")
        total += calls * (
            (MAX_INPUT_BYTES + INPUT_FRAMING_TOKENS) * _rate(snapshot, "input_usd_per_token")
            + MAX_OUTPUT_TOKENS * _rate(snapshot, "output_usd_per_token")
            + _rate(snapshot, "request_usd"))
    return total.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)


def required_headroom(prices: Mapping[str, Mapping[str, Any]],
                      remaining: int) -> Decimal:
    if type(remaining) is not int or not 0 <= remaining <= ROWS:
        raise ValueError("XHIGH018 remaining row count differs")
    return remaining * per_row_reserve(prices) + CONTINGENCY_USD + UNASSIGNED_RESIDUAL_USD
