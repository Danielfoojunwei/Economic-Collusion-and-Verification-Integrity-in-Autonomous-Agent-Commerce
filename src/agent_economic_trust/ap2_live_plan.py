"""Unfrozen prospective AP2 audit-purchase × invoice-release assignment."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
import hmac
import json
from pathlib import Path
import subprocess
from typing import Any

from .ap2_live_task import Ap2LiveRow
from .ap2_live_fixture import invoice_case


STUDY_ID = "ap2-audit-purchase-invoice-release-live-001"
MODEL_ID = "openai/gpt-5.6-sol"
MAX_CALLS_PER_EPISODE = 12
MAX_INPUT_BYTES = 49_152
MAX_OUTPUT_TOKENS = 4_096
CONTINGENCY_USD = Decimal("2")
ADAPTERS = ("PERMISSIVE", "STRICT")
TRUTHS = ("good", "bad")
_COMMON_GIT_DIR = Path(subprocess.run(
    ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
    cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True,
    check=True, timeout=10).stdout.strip())
CANONICAL_LEDGER_PATH = _COMMON_GIT_DIR.parent / "artifacts/budget/openrouter-ledger.jsonl"


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def _id(seed: bytes, purpose: str, *parts: object) -> str:
    return hmac.new(seed, canonical([STUDY_ID, purpose, *parts]), "sha256").hexdigest()[:24]


def make_schedule(seed_hex: str) -> tuple[Ap2LiveRow, ...]:
    if len(seed_hex) != 64 or any(c not in "0123456789abcdef" for c in seed_hex):
        raise ValueError("assignment seed must be 32 lowercase hex bytes")
    seed = bytes.fromhex(seed_hex)
    rows = []
    for truth in TRUTHS:
        fixture, _ = invoice_case(truth)
        for adapter in ADAPTERS:
            pair = "pair-" + _id(seed, "pair", truth, adapter)
            rows.append(Ap2LiveRow(
                episode_id="ap2live-" + _id(seed, "episode", pair),
                pair_id=pair, adapter=adapter, truth=truth,
                task_id=fixture.task_id,
                obligation_id="invoice-" + _id(seed, "obligation", pair),
                provider_id="provider-" + _id(seed, "provider", pair),
                auditor_id="auditor-" + _id(seed, "auditor", pair),
            ))
    return tuple(sorted(rows, key=lambda row: _id(seed, "execution_order", row.episode_id)))


def manifest(seed_hex: str, rows: tuple[Ap2LiveRow, ...]) -> dict:
    if rows != make_schedule(seed_hex):
        raise ValueError("assignment differs from seeded schedule")
    public_rows = [
        {key: value for key, value in asdict(row).items()
         if key not in {"truth", "task_id"}}
        for row in rows
    ]
    return {
        "schema": "ap2-live-prospective-assignment-v1",
        "status": "PROSPECTIVE_UNFROZEN",
        "study_id": STUDY_ID,
        "planned_episodes": 4,
        "assignment_unit": "fresh provider-auditor pair",
        "private_seed_commitment_sha256": sha256(bytes.fromhex(seed_hex)).hexdigest(),
        "private_rows_hmac_sha256": hmac.new(bytes.fromhex(seed_hex), canonical(
            [asdict(row) for row in rows]), "sha256").hexdigest(),
        "public_rows": public_rows,
        "private_execution_order": [row.episode_id for row in rows],
        "model_route": MODEL_ID, "role_isolation": "two ORBIT role agents on same approved route",
        "reasoning_effort": "high", "reasoning_history": "none",
        "max_calls_per_episode": MAX_CALLS_PER_EPISODE,
        "max_serialized_input_bytes": MAX_INPUT_BYTES,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "automatic_retries": 0,
        "lifetime_project_cap_usd": "50",
        "full_block_reserve_required": True,
        "contingency_usd": str(CONTINGENCY_USD),
        "model_tier": "REAL_LLM_REMOTE_APPROVED",
        "transaction_tier": "NATIVE_LOCAL_PROTOCOL",
        "ap2_payment_execution": "NONE",
        "audit_purchase_execution": "APPLICATION_LOCAL_ERC20",
        "ap2_purchase_quality_authority": "NONE",
        "design": "2 truths × 2 application release adapters; same public model inputs, fresh pair per row",
        "primary_endpoints": ["agent_false_approval", "wrongful_native_payout",
                              "good_work_nonpayment", "independent_check_use"],
        "missing_policy": "all four assigned rows retained; incomplete and stopped rows remain in denominator",
        "inference": "mechanism demonstration, no population or protocol-vulnerability claim",
    }
