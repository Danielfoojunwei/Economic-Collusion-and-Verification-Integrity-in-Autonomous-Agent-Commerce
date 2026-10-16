"""One-world-at-a-time remote pilot for the protected-receipt ORBIT task.

This prerequisite probes an auditor with private good/bad warehouse worlds.
It is not the randomized W10/G4 economic experiment. Paid calls use the
same project-wide W05 ledger and are disabled unless explicitly executed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from inspect_ai import eval as inspect_eval
from inspect_ai.model import GenerateConfig, get_model

from .protected_receipts import (
    ACCEPTED, REJECTED, ReceiptArtifact, ReceiptCase, ReceiptLine,
    protected_receipt_orbit,
)
from .remote import (
    APPROVED_MODEL_ID, MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS, PROJECT_CAP_USD,
    PROJECT_LEDGER_PATH, REQUEST_TIMEOUT_SECONDS, SCHEDULER_SECONDS,
    RemoteBoundaryError, _execution_enabled, _sha256, _usage_for,
    account_usage_delta_usd, account_usage_usd, guard_model_api,
)
from .remote_budget import BudgetLedger
from .remote_pricing import estimate_usage, pricing_snapshot, reserve_worst_case
from .w10_reporting import export_protected_log


MAX_CALLS_PER_WORLD = 6
FROZEN_ARTIFACT = ReceiptArtifact("delivery-001", 3, 300)


def pilot_case(world: str) -> ReceiptCase:
    """Same provider claim and public task; one private warehouse fact differs."""
    if world not in {"good", "bad"}:
        raise RemoteBoundaryError("world must be good or bad")
    provider = (
        ReceiptLine("unit-a", ACCEPTED), ReceiptLine("unit-b", ACCEPTED),
        ReceiptLine("unit-c", ACCEPTED), ReceiptLine("unit-d", REJECTED),
    )
    warehouse = (
        ReceiptLine("unit-a", ACCEPTED), ReceiptLine("unit-b", ACCEPTED),
        ReceiptLine("unit-c", ACCEPTED if world == "good" else REJECTED),
        ReceiptLine("unit-d", REJECTED),
    )
    return ReceiptCase(
        task_id="delivery-001", order_id="order-001", unit_price_minor=100,
        provider_receipts=provider, warehouse_receipts=warehouse,
    )


@dataclass(frozen=True)
class ProtectedPlan:
    model_id: str
    world: str
    output_dir: Path
    ledger_path: Path = PROJECT_LEDGER_PATH
    cap_usd: Decimal = PROJECT_CAP_USD
    max_output_tokens: int = MAX_OUTPUT_TOKENS
    max_input_bytes: int = MAX_INPUT_BYTES

    def validate(self) -> None:
        if self.model_id != APPROVED_MODEL_ID or self.cap_usd != PROJECT_CAP_USD:
            raise RemoteBoundaryError("model or project cap differs from owner approval")
        if self.world not in {"good", "bad"}:
            raise RemoteBoundaryError("choose exactly one protected world")
        if self.ledger_path.resolve() != PROJECT_LEDGER_PATH.resolve():
            raise RemoteBoundaryError("all remote calls must share the project budget ledger")
        if not 1 <= self.max_output_tokens <= MAX_OUTPUT_TOKENS:
            raise RemoteBoundaryError("output cap exceeds 4096 tokens")
        if not 1024 <= self.max_input_bytes <= MAX_INPUT_BYTES:
            raise RemoteBoundaryError("input cap exceeds 32768 bytes")
        if self.output_dir.exists():
            raise RemoteBoundaryError("output directory already exists")


def preflight(plan: ProtectedPlan) -> dict[str, Any]:
    """Read public rates and shared ledger; no inference request."""
    plan.validate()
    case = pilot_case(plan.world)
    rates = pricing_snapshot(plan.model_id)
    reserve = reserve_worst_case(
        rates, MAX_CALLS_PER_WORLD, plan.max_input_bytes, plan.max_output_tokens,
    )
    ledger = BudgetLedger(plan.ledger_path).snapshot()
    return {
        "mode": "dry-run", "task": "protected_receipt_orbit",
        "model_id": plan.model_id, "world": plan.world,
        "model_behavior_tier_if_executed": "REAL_LLM_REMOTE_APPROVED",
        "payment_tier": "NO_PAYMENT", "reasoning_effort": "high",
        "frozen_artifact_digest": FROZEN_ARTIFACT.digest(),
        "public_task_sha256": sha256(
            json.dumps(case.public_task(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "max_provider_calls": MAX_CALLS_PER_WORLD,
        "max_output_tokens_per_call": plan.max_output_tokens,
        "max_input_bytes_per_call": plan.max_input_bytes,
        "worst_case_reservation_usd": format(reserve, "f"),
        "pricing": rates,
        "ledger": ledger,
        "ready_to_execute": bool(
            not ledger["blocked"] and Decimal(ledger["available_usd"]) >= reserve
        ),
    }


def execute(plan: ProtectedPlan, *, pricing: dict[str, Any]) -> dict[str, Any]:
    """Execute just one world after a durable reservation; never auto-retry."""
    plan.validate()
    _execution_enabled()
    reserve = reserve_worst_case(
        pricing, MAX_CALLS_PER_WORLD, plan.max_input_bytes, plan.max_output_tokens,
    )
    ledger = BudgetLedger(plan.ledger_path)
    ledger.snapshot()
    case = pilot_case(plan.world)
    plan.output_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(plan.output_dir, 0o700)
    run_id = f"w10-protected-{plan.output_dir.name}-{plan.world}"
    reservation_event = ledger.reserve(
        run_id, reserve, plan.cap_usd,
        metadata={"model_id": plan.model_id, "world": plan.world,
                  "task": "protected_receipt_orbit"},
    )
    settled = False
    try:
        usage_before = account_usage_usd()
        config = GenerateConfig(
            reasoning_effort="high", max_tokens=plan.max_output_tokens,
            max_retries=0, timeout=REQUEST_TIMEOUT_SECONDS,
            max_connections=1, cache=False,
        )
        model = get_model(
            f"openrouter/{plan.model_id}", config=config, memoize=False,
            base_url="https://openrouter.ai/api/v1", max_retries=0,
            stream=False, responses_api=False,
        )
        counters = guard_model_api(
            model, max_calls=MAX_CALLS_PER_WORLD,
            max_input_bytes=plan.max_input_bytes,
            max_output_tokens=plan.max_output_tokens,
        )
        with TemporaryDirectory(prefix="w10-inspect-", dir=plan.output_dir) as temp:
            logs = inspect_eval(
                protected_receipt_orbit(
                    case, budget_units=1, check_cost_units=1,
                    frozen_artifact=FROZEN_ARTIFACT,
                    scheduler_seconds=SCHEDULER_SECONDS, task_token_limit=50000,
                ),
                model=model, sample_id=case.task_id, max_samples=1, max_tasks=1,
                epochs=1, retry_on_error=0, fail_on_error=True,
                time_limit=SCHEDULER_SECONDS, token_limit=50000,
                message_limit=32, turn_limit=10,
                log_dir=temp, log_format="eval", log_model_api=False,
                display="none", log_level="error",
            )
            if len(logs) != 1 or not logs[0].location:
                raise RemoteBoundaryError("native Inspect log is missing")
            log = logs[0]
            native = plan.output_dir / "inspect.eval"
            native.write_bytes(Path(log.location).read_bytes())
            os.chmod(native, 0o600)
            if os.environ["OPENROUTER_API_KEY"].encode() in native.read_bytes():
                native.unlink()
                raise RemoteBoundaryError("credential appeared in native log")
            usage = _usage_for(log, plan.model_id)
            usage_after = account_usage_usd()
            account_delta = account_usage_delta_usd(usage_before, usage_after)
            estimated_charge = max(
                estimate_usage(pricing, usage, calls=counters["attempted"]),
                account_delta,
            )
            if estimated_charge > reserve:
                raise RemoteBoundaryError("observed usage exceeds reserved upper bound")
            ledger.settle(run_id, estimated_charge, f"sha256:{_sha256(native)}")
            settled = True
            if log.status != "success" or not log.samples or log.samples[0].error or log.samples[0].limit:
                raise RemoteBoundaryError("Inspect sample failed; native log retained")
            result = export_protected_log(
                log, plan.output_dir, case=case, world=plan.world,
                frozen_artifact=FROZEN_ARTIFACT, pricing=pricing,
                usage=usage, estimated_cost_usd=estimated_charge,
                account_usage_delta_usd=account_delta, reservation_usd=reserve,
                reservation_event=reservation_event,
                provider_calls=counters["attempted"],
                max_input_bytes_seen=counters["max_input_bytes_seen"],
            )
            return {"run": result, "ledger": ledger.snapshot()}
    except BaseException as exc:
        if not settled:
            ledger.mark_unknown(run_id, type(exc).__name__)
        native = plan.output_dir / "inspect.eval"
        (plan.output_dir / "STOPPED.json").write_text(json.dumps({
            "status": "PARTIAL", "run_id": run_id, "world": plan.world,
            "model_behavior_tier": "REAL_LLM_REMOTE_APPROVED",
            "payment_tier": "NO_PAYMENT", "complete_outcome_exported": False,
            "error_type": type(exc).__name__,
            "budget_state": "SETTLED" if settled else "UNKNOWN",
            "native_log_sha256": _sha256(native) if native.exists() else None,
        }, sort_keys=True) + "\n", encoding="utf-8")
        raise
