"""Unfrozen eight-cell ERC-8183 evaluator-fee pilot assignment and budget preview.

This module performs no assignment freeze, ledger mutation, model call or
payment. A paid runner would need its own independent readiness/source gate.
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


STUDY = "erc8183-native-evaluator-fee-live-010"
SOL = "openai/gpt-5.6-sol"
SONNET = "anthropic/claude-sonnet-5.5"
PROVIDER_CALLS = 3
AUDITOR_CALLS = 5
MAX_INPUT_BYTES = 49_152
INPUT_FRAMING_TOKENS = 8_192
MAX_OUTPUT_TOKENS = 4_096
CONTINGENCY_USD = Decimal("2")
UNASSIGNED_RESIDUAL_USD = Decimal("0.0000342")
ROWS = 8
TRUTHS = ("good", "bad")
FEE_TERMS = ("NATIVE_CONTINGENT", "CLIENT_PREPAID")
CONTACTS = ("CHANNEL", "NO_CONTACT")
CANONICAL_LEDGER = canonical_project_root() / "artifacts/budget/openrouter-ledger.jsonl"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def _id(seed: bytes, purpose: str, *parts: object) -> str:
    return hmac.new(seed, _canonical([STUDY, purpose, *parts]), "sha256").hexdigest()[:24]


@dataclass(frozen=True)
class FeeRow:
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


def make_schedule(seed_hex: str) -> tuple[FeeRow, ...]:
    if not isinstance(seed_hex, str) or re.fullmatch(r"[0-9a-f]{64}", seed_hex) is None:
        raise ValueError("seed must be 32 lowercase hex bytes")
    seed = bytes.fromhex(seed_hex)
    rows = []
    for truth in TRUTHS:
        for fee_term in FEE_TERMS:
            for contact in CONTACTS:
                pair = "pair-" + _id(seed, "pair", truth, fee_term, contact)
                rows.append(FeeRow(
                    episode_id="fee010-" + _id(seed, "episode", pair),
                    pair_id=pair,
                    obligation_id="invoice-" + _id(seed, "obligation", pair),
                    provider_id="provider-" + _id(seed, "provider", pair),
                    auditor_id="auditor-" + _id(seed, "auditor", pair),
                    truth=truth, fee_term=fee_term, contact=contact,
                ))
    if len(rows) != ROWS or len({r.pair_id for r in rows}) != ROWS:
        raise AssertionError("eight independent provider-auditor pairs required")
    return tuple(sorted(rows, key=lambda row: _id(seed, "execution_order", row.episode_id)))


def prospective_manifest(seed_hex: str, rows: tuple[FeeRow, ...]) -> dict[str, Any]:
    """Calculate an unfrozen proposal; callers must not present this as approval."""
    if rows != make_schedule(seed_hex):
        raise ValueError("rows differ from the seed-derived schedule")
    seed = bytes.fromhex(seed_hex)
    public = [{k: v for k, v in asdict(row).items() if k != "truth"} for row in rows]
    return {
        "schema": "erc8183-fee-design-assignment-preview-v1",
        "status": "UNFROZEN_NO_PAID_EXECUTION",
        "study": STUDY, "rows": ROWS,
        "seed_commitment_sha256": sha256(seed).hexdigest(),
        "private_rows_hmac_sha256": hmac.new(seed, _canonical(
            [asdict(row) for row in rows]), "sha256").hexdigest(),
        "public_rows": public,
        "execution_order": [row.episode_id for row in rows],
        "role_models": {"provider": SOL, "auditor": SONNET},
        "max_calls_by_role": {"provider": PROVIDER_CALLS, "auditor": AUDITOR_CALLS},
        "max_serialized_input_bytes": MAX_INPUT_BYTES,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "high_reasoning_both_roles": True,
        "truth_condition_private_until_paid_check": True,
    }


def _rate(snapshot: Mapping[str, Any], key: str) -> Decimal:
    try:
        amount = Decimal(str(snapshot[key]))
    except Exception as exc:
        raise ValueError(f"missing or invalid {key}") from exc
    if not amount.is_finite() or amount < 0 or key != "request_usd" and amount == 0:
        raise ValueError(f"invalid {key}")
    return amount


def per_row_reserve(prices: Mapping[str, Mapping[str, Any]]) -> Decimal:
    """Price all possible calls at the catalog's highest captured tier."""
    if set(prices) != {SOL, SONNET}:
        raise ValueError("both exact model price snapshots required")
    total = Decimal(0)
    for model, calls in ((SOL, PROVIDER_CALLS), (SONNET, AUDITOR_CALLS)):
        snapshot = prices[model]
        if (snapshot.get("model_id") != model
                or type(snapshot.get("context_length")) is not int
                or snapshot["context_length"] < MAX_INPUT_BYTES + INPUT_FRAMING_TOKENS + MAX_OUTPUT_TOKENS
                or type(snapshot.get("max_completion_tokens")) is not int
                or snapshot["max_completion_tokens"] < MAX_OUTPUT_TOKENS):
            raise ValueError("model identity or context limit differs")
        total += calls * (
            (MAX_INPUT_BYTES + INPUT_FRAMING_TOKENS) * _rate(snapshot, "input_usd_per_token")
            + MAX_OUTPUT_TOKENS * _rate(snapshot, "output_usd_per_token")
            + _rate(snapshot, "request_usd")
        )
    return total.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)


def read_only_headroom(snapshot: Mapping[str, Any], prices: Mapping[str, Mapping[str, Any]]) -> dict:
    """Preview full-block affordability without reserving or modifying ledger."""
    from .mpp008_budget import mpp006_contingent_exposure

    if (snapshot.get("cap_usd") != "50" or snapshot.get("blocked") is not False
            or snapshot.get("unknown_run_ids") != []):
        raise ValueError("shared USD50 ledger is blocked or differs")
    mpp006_contingent_exposure(snapshot, additional_reservation_usd=(
        Decimal(snapshot["reserved_usd"]) - Decimal("6.30784")))
    per_row = per_row_reserve(prices)
    required = ROWS * per_row + CONTINGENCY_USD + UNASSIGNED_RESIDUAL_USD
    available = Decimal(snapshot["available_usd"])
    if not available.is_finite() or available < 0:
        raise ValueError("invalid shared ledger availability")
    return {"status": "DESIGN_ONLY_READ_ONLY",
            "per_row_worst_case_usd": str(per_row),
            "full_block_plus_contingency_usd": str(required),
            "ledger_available_usd": str(available),
            "ledger_seq": snapshot["seq"],
            "affordable_at_snapshot": required <= available,
            "permission_to_freeze_or_call": False,
            "catalog_refresh_and_independent_gate_still_required": True}
