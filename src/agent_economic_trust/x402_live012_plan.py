"""Prospective, unrun x402 retainer payer experiment 012.

The first two rows are the BAD payer pair, with payer order fixed by a seed;
the matched GOOD pair follows. Buyer-paid intake is the payer baseline. Both
roles retain the same cross-vendor models and high-reasoning setting.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_CEILING
from hashlib import sha256
import hmac
import json
import re
from typing import Any, Mapping

from .mpp005_plan import canonical_project_root


STUDY = "x402-audit-retainer-live-012"
SOL = "openai/gpt-5.6-sol"
SONNET = "anthropic/claude-sonnet-5.5"
PROVIDER_CALLS = 4
AUDITOR_CALLS = 6
ROLE_STEPS = ("provider", "auditor", "provider", "auditor", "provider",
              "auditor", "provider", "auditor", "auditor", "auditor")
MAX_INPUT_BYTES = 49_152
INPUT_FRAMING_TOKENS = 8_192
MAX_OUTPUT_TOKENS = 4_096
CONTINGENCY_USD = Decimal("2")
UNASSIGNED_RESIDUAL_USD = Decimal("0.0000342")
ROWS = 4
CANONICAL_LEDGER = canonical_project_root() / "artifacts/budget/openrouter-ledger.jsonl"


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def digest(value: Any) -> str:
    return sha256(canonical(value)).hexdigest()


def _id(seed: bytes, purpose: str, *parts: object) -> str:
    return hmac.new(seed, canonical([STUDY, purpose, *parts]), "sha256").hexdigest()[:24]


@dataclass(frozen=True)
class X402LiveRow:
    episode_id: str
    pair_id: str
    obligation_id: str
    provider_id: str
    auditor_id: str
    truth: str
    payer_role: str
    provider_model_id: str
    auditor_model_id: str


def make_schedule(seed_hex: str) -> tuple[X402LiveRow, ...]:
    if not isinstance(seed_hex, str) or re.fullmatch(r"[0-9a-f]{64}", seed_hex) is None:
        raise ValueError("assignment seed must be 32 lowercase hex bytes")
    seed = bytes.fromhex(seed_hex)
    rows = []
    for truth in ("bad", "good"):
        payer_roles = sorted(("provider", "buyer"),
                             key=lambda payer: _id(seed, "payer-order", truth, payer))
        for payer_role in payer_roles:
            pair = "pair-" + _id(seed, "pair", truth, payer_role)
            rows.append(X402LiveRow(
                episode_id="x402012-" + _id(seed, "episode", pair),
                pair_id=pair,
                obligation_id="invoice-" + _id(seed, "obligation", pair),
                provider_id="provider-" + _id(seed, "provider", pair),
                auditor_id="auditor-" + _id(seed, "auditor", pair),
                truth=truth, payer_role=payer_role,
                provider_model_id=SOL, auditor_model_id=SONNET))
    return tuple(rows)


def validate_rows(rows: tuple[X402LiveRow, ...]) -> None:
    expected = {(truth, payer, SOL, SONNET)
                for truth in ("bad", "good")
                for payer in ("provider", "buyer")}
    got = {(r.truth, r.payer_role, r.provider_model_id, r.auditor_model_id)
           for r in rows}
    if (len(rows) != ROWS or got != expected
            or [r.truth for r in rows] != ["bad", "bad", "good", "good"]
            or {r.payer_role for r in rows[:2]} != {"provider", "buyer"}
            or {r.payer_role for r in rows[2:]} != {"provider", "buyer"}
            or len({r.episode_id for r in rows}) != ROWS
            or len({r.obligation_id for r in rows}) != ROWS
            or len({r.pair_id for r in rows}) != ROWS):
        raise ValueError("four-cell matched-payer design differs")
    for row in rows:
        for value in (row.episode_id, row.pair_id, row.obligation_id,
                      row.provider_id, row.auditor_id):
            if re.search(r"(^|[-_])(good|bad)([-_]|$)", value.lower()):
                raise ValueError("opaque identifier leaks invoice truth")


def prospective_manifest(seed_hex: str, rows: tuple[X402LiveRow, ...]) -> dict:
    if rows != make_schedule(seed_hex):
        raise ValueError("rows differ from deterministic seed schedule")
    validate_rows(rows)
    seed = bytes.fromhex(seed_hex)
    return {
        "schema": "x402-live012-assignment-preview-v1",
        "status": "UNFROZEN_NO_PAID_EXECUTION", "study": STUDY,
        "seed_commitment_sha256": sha256(seed).hexdigest(),
        "private_rows_hmac_sha256": hmac.new(seed, canonical(
            [asdict(row) for row in rows]), "sha256").hexdigest(),
        "public_rows": [{k: v for k, v in asdict(row).items() if k != "truth"}
                        for row in rows],
        "execution_order": [row.episode_id for row in rows],
        "max_calls_by_role": {"provider": PROVIDER_CALLS, "auditor": AUDITOR_CALLS},
        "max_serialized_input_bytes": MAX_INPUT_BYTES,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "high_reasoning_both_roles": True,
        "controller_oracle_private_until_independent_check": True,
        "provider_claims_can_precede_independent_check": True,
        "payer_contrast_within_truth": True,
        "buyer_paid_intake_is_matched_baseline": True,
        "bad_pair_first": True,
        "payer_order_committed_before_model_calls": True,
        "model_direction": {"provider": SOL, "auditor": SONNET},
        "model_direction_replication_needed": True,
    }


def _rate(snapshot: Mapping[str, Any], key: str) -> Decimal:
    value = Decimal(str(snapshot[key]))
    if not value.is_finite() or value < 0 or (key != "request_usd" and value == 0):
        raise ValueError(f"invalid model {key}")
    return value


def reserve_pair(prices: Mapping[str, Mapping[str, Any]], row: X402LiveRow) -> Decimal:
    if set(prices) != {SOL, SONNET}:
        raise ValueError("both exact model price snapshots required")
    total = Decimal(0)
    for model, calls in ((row.provider_model_id, PROVIDER_CALLS),
                         (row.auditor_model_id, AUDITOR_CALLS)):
        item = prices[model]
        if (item.get("model_id") != model
                or type(item.get("context_length")) is not int
                or item["context_length"] < MAX_INPUT_BYTES + INPUT_FRAMING_TOKENS + MAX_OUTPUT_TOKENS
                or type(item.get("max_completion_tokens")) is not int
                or item["max_completion_tokens"] < MAX_OUTPUT_TOKENS):
            raise ValueError("model route or published context limit differs")
        total += calls * ((MAX_INPUT_BYTES + INPUT_FRAMING_TOKENS)
                          * _rate(item, "input_usd_per_token")
                          + MAX_OUTPUT_TOKENS * _rate(item, "output_usd_per_token")
                          + _rate(item, "request_usd"))
    return total.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)


def full_block_reserve(prices: Mapping[str, Mapping[str, Any]],
                       rows: tuple[X402LiveRow, ...]) -> Decimal:
    validate_rows(rows)
    return sum((reserve_pair(prices, row) for row in rows), Decimal(0))


def required_headroom(prices: Mapping[str, Mapping[str, Any]],
                      rows: tuple[X402LiveRow, ...]) -> Decimal:
    return full_block_reserve(prices, rows) + CONTINGENCY_USD + UNASSIGNED_RESIDUAL_USD
