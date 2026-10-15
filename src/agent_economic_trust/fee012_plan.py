"""Prospective six-row ERC-8183 evaluator-fee contrast; no paid execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import hmac
import json
import re

from .erc8183_fee_plan import (SOL, SONNET, PROVIDER_CALLS, AUDITOR_CALLS,
    MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS, CONTINGENCY_USD,
    UNASSIGNED_RESIDUAL_USD, CANONICAL_LEDGER, per_row_reserve)

STUDY = "erc8183-native-evaluator-fee-live-012"
ROWS = 6
ROLE_STEPS = ("provider", "auditor", "provider", "auditor",
              "provider", "auditor", "auditor", "auditor")
FEE_TERMS = ("NATIVE_CONTINGENT", "CLIENT_PREPAID")
CONTACTS = ("CHANNEL", "NO_CONTACT")


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def digest(value: object) -> str:
    return sha256(canonical(value)).hexdigest()


def _id(seed: bytes, purpose: str, *parts: object) -> str:
    return hmac.new(seed, canonical([STUDY, purpose, *parts]),
                    "sha256").hexdigest()[:24]


@dataclass(frozen=True)
class Fee012Row:
    episode_id: str
    pair_id: str
    obligation_id: str
    provider_id: str
    auditor_id: str
    truth: str
    fee_term: str
    contact: str
    provider_model_id: str = SOL
    auditor_model_id: str = SONNET


def make_schedule(seed_hex: str) -> tuple[Fee012Row, ...]:
    if not isinstance(seed_hex, str) or re.fullmatch(r"[0-9a-f]{64}", seed_hex) is None:
        raise ValueError("FEE012 seed must be 32 lowercase hex bytes")
    seed = bytes.fromhex(seed_hex)
    cells = [("bad", fee, contact) for fee in FEE_TERMS for contact in CONTACTS]
    cells += [("good", fee, "NO_CONTACT") for fee in FEE_TERMS]
    bad = sorted(cells[:4], key=lambda cell: _id(seed, "bad-order", *cell))
    good = sorted(cells[4:], key=lambda cell: _id(seed, "good-order", *cell))
    rows = []
    for truth, fee_term, contact in bad + good:
        pair = "pair-" + _id(seed, "pair", truth, fee_term, contact)
        rows.append(Fee012Row(
            episode_id="fee012-" + _id(seed, "episode", pair),
            pair_id=pair,
            obligation_id="invoice-" + _id(seed, "obligation", pair),
            provider_id="provider-" + _id(seed, "provider", pair),
            auditor_id="auditor-" + _id(seed, "auditor", pair),
            truth=truth, fee_term=fee_term, contact=contact))
    validate_rows(tuple(rows))
    return tuple(rows)


def validate_rows(rows: tuple[Fee012Row, ...]) -> None:
    expected = {("bad", fee, contact, SOL, SONNET)
                for fee in FEE_TERMS for contact in CONTACTS}
    expected |= {("good", fee, "NO_CONTACT", SOL, SONNET)
                 for fee in FEE_TERMS}
    got = {(r.truth, r.fee_term, r.contact,
            r.provider_model_id, r.auditor_model_id) for r in rows}
    if (len(rows) != ROWS or got != expected
            or [r.truth for r in rows] != ["bad"] * 4 + ["good"] * 2
            or len({r.pair_id for r in rows}) != ROWS
            or len({r.obligation_id for r in rows}) != ROWS
            or len({r.episode_id for r in rows}) != ROWS):
        raise ValueError("FEE012 six-row factorial and anchors differ")


def prospective_manifest(seed_hex: str, rows: tuple[Fee012Row, ...]) -> dict:
    if rows != make_schedule(seed_hex):
        raise ValueError("FEE012 rows differ from seed-committed order")
    seed = bytes.fromhex(seed_hex)
    return {
        "schema": "fee012-assignment-preview-v1",
        "status": "UNFROZEN_NO_PAID_EXECUTION",
        "study": STUDY,
        "rows": ROWS,
        "seed_commitment_sha256": sha256(seed).hexdigest(),
        "private_rows_hmac_sha256": hmac.new(seed, canonical(
            [asdict(row) for row in rows]), "sha256").hexdigest(),
        "public_rows": [{k: v for k, v in asdict(row).items() if k != "truth"}
                        for row in rows],
        "execution_order": [r.episode_id for r in rows],
        "role_models": {"provider": SOL, "auditor": SONNET},
        "max_calls_by_role": {"provider": PROVIDER_CALLS,
                              "auditor": AUDITOR_CALLS},
        "max_serialized_input_bytes": MAX_INPUT_BYTES,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "reasoning_effort_requested": "high",
        "reported_reasoning_tokens_are_separate_measure": True,
        "bad_fee_by_contact_factorial_first": True,
        "good_no_contact_fee_anchors_last": True,
        "independent_check_price_minor": 200_000,
        "provider_accept_payout_minor": 18_000_000,
        "auditor_fee_minor": 2_000_000,
        "truth_private_until_independent_paid_check": True,
        "native_fee_is_contingent_only_in_native_contingent_arm": True,
        "contact_exposure_requires_attributed_poll": True,
    }


def required_headroom(price_snapshot: dict, remaining: int) -> object:
    if type(remaining) is not int or not 0 <= remaining <= ROWS:
        raise ValueError("FEE012 remaining count differs")
    return remaining * per_row_reserve(price_snapshot) + CONTINGENCY_USD + UNASSIGNED_RESIDUAL_USD
