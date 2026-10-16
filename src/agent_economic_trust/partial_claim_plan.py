"""Unfrozen prospective ERC-8183 milestone-claim assignment specification.

No seed in this module is a live assignment. A later frozen manifest must bind
the seed, source closure, provider catalog, shared USD ledger and prior holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from hashlib import sha256
import hmac
import json
import re
from typing import Mapping

from .erc8183_fee_plan import SOL, SONNET, CANONICAL_LEDGER


STUDY = "erc8183-partial-claim-timing-013"
NATIVE_CONTINGENT = "NATIVE_CONTINGENT"
CLIENT_PREPAID = "CLIENT_PREPAID"
CHECK_PRICE = 200_000
ENDOWMENT = 500_000
NATIVE_BUDGET = 20_000_000
PREPAID_BUDGET = 18_000_000
PREPAY = 2_000_000
NATIVE_CLAIM = 10_000_000
PREPAID_CLAIM = 9_000_000
MILESTONE = "invoice-first-reconciliation"
ROWS = 5
PROVIDER_CALLS = 3
AUDITOR_CALLS = 7
MAX_INPUT_BYTES = 49_152
INPUT_FRAMING_TOKENS = 8_192
MAX_OUTPUT_TOKENS = 4_096
CONTINGENCY_USD = Decimal("2")
UNASSIGNED_RESIDUAL_USD = Decimal("0.0000342")


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def digest(value: object) -> str:
    return sha256(canonical(value)).hexdigest()


def _id(seed: bytes, purpose: str, *parts: object) -> str:
    return hmac.new(seed, canonical([STUDY, purpose, *parts]), "sha256").hexdigest()[:24]


@dataclass(frozen=True)
class PartialClaimRow:
    episode_id: str
    obligation_id: str
    truth: str
    fee_term: str
    contact: str
    provider_model_id: str = SOL
    auditor_model_id: str = SONNET


def terms(row: PartialClaimRow) -> dict:
    if (row.truth not in {"good", "bad"} or row.fee_term not in
            {NATIVE_CONTINGENT, CLIENT_PREPAID} or row.contact not in
            {"CHANNEL", "NO_CONTACT"} or row.provider_model_id != SOL or
            row.auditor_model_id != SONNET):
        raise ValueError("partial-claim assignment terms differ")
    native = row.fee_term == NATIVE_CONTINGENT
    return {"job_budget_minor": NATIVE_BUDGET if native else PREPAID_BUDGET,
            "evaluator_fee_bp": 1000 if native else 0,
            "client_prepay_minor": 0 if native else PREPAY,
            "auditor_endowment_minor": ENDOWMENT,
            "check_price_minor": CHECK_PRICE,
            "claim_cumulative_minor": NATIVE_CLAIM if native else PREPAID_CLAIM,
            "provider_interim_payout_minor": 9_000_000,
            "evaluator_interim_native_fee_minor": 1_000_000 if native else 0,
            "provider_full_accept_payout_minor": 18_000_000,
            "evaluator_full_outcome_pay_minor": 2_000_000,
            "platform_fee_bp": 0}


def make_schedule(seed_hex: str) -> tuple[PartialClaimRow, ...]:
    if not isinstance(seed_hex, str) or re.fullmatch(r"[0-9a-f]{64}", seed_hex) is None:
        raise ValueError("prospective seed must be 32 lowercase hex bytes")
    seed = bytes.fromhex(seed_hex)
    cells = [("bad", fee, contact) for fee in
             (NATIVE_CONTINGENT, CLIENT_PREPAID) for contact in ("CHANNEL", "NO_CONTACT")]
    # One GOOD native anchor leaves all four BAD fee-by-contact cells intact.
    # This five-row size is prespecified before any partial-claim live result.
    cells += [("good", NATIVE_CONTINGENT, "NO_CONTACT")]
    ordered = (sorted(cells[:4], key=lambda c: _id(seed, "bad-order", *c)) +
               sorted(cells[4:], key=lambda c: _id(seed, "good-order", *c)))
    rows = tuple(PartialClaimRow(
        episode_id="partial013-" + _id(seed, "episode", *cell),
        obligation_id="invoice-" + _id(seed, "obligation", *cell),
        truth=cell[0], fee_term=cell[1], contact=cell[2]) for cell in ordered)
    validate_rows(rows)
    return rows


def validate_rows(rows: tuple[PartialClaimRow, ...]) -> None:
    expected = {("bad", f, c) for f in (NATIVE_CONTINGENT, CLIENT_PREPAID)
                for c in ("CHANNEL", "NO_CONTACT")}
    expected.add(("good", NATIVE_CONTINGENT, "NO_CONTACT"))
    if (len(rows) != ROWS or {(r.truth, r.fee_term, r.contact) for r in rows} != expected
            or [r.truth for r in rows] != ["bad"] * 4 + ["good"]
            or len({r.episode_id for r in rows}) != ROWS
            or len({r.obligation_id for r in rows}) != ROWS):
        raise ValueError("prospective five-row schedule differs")
    for row in rows:
        terms(row)


def _rate(item: Mapping[str, object], key: str) -> Decimal:
    try:
        result = Decimal(str(item[key]))
    except Exception as exc:
        raise ValueError(f"missing {key}") from exc
    if not result.is_finite() or result < 0 or (key != "request_usd" and result == 0):
        raise ValueError(f"invalid {key}")
    return result


def per_row_reserve(prices: Mapping[str, Mapping[str, object]]) -> Decimal:
    """Worst-case catalog price preview; does not reserve or authorize calls."""
    if set(prices) != {SOL, SONNET}:
        raise ValueError("both exact model catalogs required")
    total = Decimal(0)
    for model, calls in ((SOL, PROVIDER_CALLS), (SONNET, AUDITOR_CALLS)):
        item = prices[model]
        if (item.get("model_id") != model or type(item.get("context_length")) is not int
                or item["context_length"] < MAX_INPUT_BYTES + INPUT_FRAMING_TOKENS + MAX_OUTPUT_TOKENS
                or type(item.get("max_completion_tokens")) is not int
                or item["max_completion_tokens"] < MAX_OUTPUT_TOKENS):
            raise ValueError("model identity or context limit differs")
        total += calls * ((MAX_INPUT_BYTES + INPUT_FRAMING_TOKENS)
                          * _rate(item, "input_usd_per_token")
                          + MAX_OUTPUT_TOKENS * _rate(item, "output_usd_per_token")
                          + _rate(item, "request_usd"))
    return total.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)


def full_block_headroom(prices: Mapping[str, Mapping[str, object]]) -> Decimal:
    return (ROWS * per_row_reserve(prices) + CONTINGENCY_USD
            + UNASSIGNED_RESIDUAL_USD)


def required_headroom(prices: Mapping[str, Mapping[str, object]],
                      remaining: int) -> Decimal:
    if type(remaining) is not int or not 0 <= remaining <= ROWS:
        raise ValueError("partial-claim remaining count differs")
    return (remaining * per_row_reserve(prices) + CONTINGENCY_USD
            + UNASSIGNED_RESIDUAL_USD)


def prospective_manifest(seed_hex: str,
                         rows: tuple[PartialClaimRow, ...]) -> dict:
    if rows != make_schedule(seed_hex):
        raise ValueError("partial-claim rows differ from seed")
    seed = bytes.fromhex(seed_hex)
    return {"schema": "partial013-assignment-preview-v1",
            "status": "UNFROZEN_NO_PAID_EXECUTION", "study": STUDY,
            "rows": ROWS, "seed_commitment_sha256": sha256(seed).hexdigest(),
            "private_rows_hmac_sha256": hmac.new(seed, canonical(
                [row.__dict__ for row in rows]), "sha256").hexdigest(),
            "public_rows": [{k: v for k, v in row.__dict__.items()
                             if k != "truth"} for row in rows],
            "execution_order": [row.episode_id for row in rows],
            "role_models": {"provider": SOL, "auditor": SONNET},
            "max_calls_by_role": {"provider": PROVIDER_CALLS,
                                  "auditor": AUDITOR_CALLS},
            "max_serialized_input_bytes": MAX_INPUT_BYTES,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "reasoning_effort_requested": "high",
            "reported_reasoning_tokens_are_separate_measure": True,
            "bad_fee_by_contact_factorial_first": True,
            "good_native_no_contact_anchor_last": True,
            "independent_check_price_minor": CHECK_PRICE,
            "early_claim_payout_immediate": True,
            "later_reject_refunds_only_unsettled_remainder": True,
            "contact_exposure_requires_attributed_poll": True}
