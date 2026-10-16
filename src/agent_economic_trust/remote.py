"""Bounded, explicitly enabled OpenRouter execution of the ORBIT pilot.

The budget ledger is project-wide. A reservation precedes every possible
provider request; uncertain provider outcomes block later reservations.
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
from urllib.request import Request, urlopen

from inspect_ai import eval as inspect_eval
from inspect_ai.model import GenerateConfig, get_model

from .orbit_task import FIXTURES_BY_ID, reconciliation_orbit
from .remote_budget import BudgetLedger
from .remote_pricing import estimate_usage, pricing_snapshot, reserve_worst_case
from .remote_reporting import export_remote_log


APPROVED_MODEL_ID = "openai/gpt-5.6-sol"
PROJECT_CAP_USD = Decimal("20")
PROJECT_LEDGER_PATH = (
    Path(__file__).resolve().parents[2] / "artifacts" / "budget" / "openrouter-ledger.jsonl"
)
MAX_CALLS_PER_SAMPLE = 5
MAX_OUTPUT_TOKENS = 4096
MAX_INPUT_BYTES = 32768
SCHEDULER_SECONDS = 240
REQUEST_TIMEOUT_SECONDS = 180


class RemoteBoundaryError(RuntimeError):
    """A local spend or call boundary stopped remote execution."""


def account_usage_usd() -> Decimal:
    """Read only the authenticated account usage number; never persist the key."""
    credential = os.environ.get("OPENROUTER_API_KEY")
    if not credential:
        raise RemoteBoundaryError("OpenRouter account credential is missing")
    request = Request(
        "https://openrouter.ai/api/v1/auth/key",
        headers={"Authorization": f"Bearer {credential}", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=15) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("oversized account response")
        parsed = json.loads(raw, parse_float=Decimal)
        amount = parsed["data"]["usage"]
        if isinstance(amount, bool) or not isinstance(amount, (str, int, float, Decimal)):
            raise ValueError("account usage is not numeric")
        value = Decimal(str(amount))
        if not value.is_finite() or value < 0:
            raise ValueError("account usage is invalid")
        return value
    except Exception as exc:
        # Do not expose HTTP exception text; it may contain authorization data.
        raise RemoteBoundaryError("OpenRouter account usage is unavailable") from exc


def account_usage_delta_usd(before: Decimal, after: Decimal) -> Decimal:
    """Treat an account counter decrease as ambiguous billing."""
    if after < before:
        raise RemoteBoundaryError("OpenRouter account usage counter decreased")
    return after - before


@dataclass(frozen=True)
class RemotePlan:
    model_id: str
    sample_ids: tuple[str, ...]
    output_dir: Path
    ledger_path: Path
    cap_usd: Decimal = PROJECT_CAP_USD
    max_output_tokens: int = MAX_OUTPUT_TOKENS
    max_input_bytes: int = MAX_INPUT_BYTES

    def validate(self) -> None:
        if self.model_id != APPROVED_MODEL_ID:
            raise RemoteBoundaryError("model ID differs from owner-approved OpenRouter model")
        if self.cap_usd != PROJECT_CAP_USD:
            raise RemoteBoundaryError("project cap must equal the approved USD 20 limit")
        if not 1 <= len(self.sample_ids) <= 3 or len(set(self.sample_ids)) != len(self.sample_ids):
            raise RemoteBoundaryError("choose one to three distinct sample IDs")
        if any(sample_id not in FIXTURES_BY_ID for sample_id in self.sample_ids):
            raise RemoteBoundaryError("unknown sample ID")
        if not 1 <= self.max_output_tokens <= MAX_OUTPUT_TOKENS:
            raise RemoteBoundaryError("output cap exceeds 4096 tokens")
        if not 1024 <= self.max_input_bytes <= MAX_INPUT_BYTES:
            raise RemoteBoundaryError("input cap exceeds 32768 bytes")
        if self.output_dir.exists():
            raise RemoteBoundaryError("output directory already exists")


def _dollars(value: Decimal) -> str:
    return format(value, "f")


def _safe_model_input_size(input: Any, tools: Any) -> int:
    """Count bytes of every forwarded message and offered tool definition."""
    def encode(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return value

    return len(json.dumps(
        {"input": [encode(value) for value in input],
         "tools": [encode(value) for value in tools]},
        default=str, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8"))


def guard_model_api(model: Any, *, max_calls: int, max_input_bytes: int,
                    max_output_tokens: int) -> dict[str, int]:
    """Intercept each Inspect provider call before the network boundary."""
    calls = {"attempted": 0, "max_input_bytes_seen": 0}
    original = model.api.generate

    async def bounded_generate(input: Any, tools: Any, tool_choice: Any,
                               config: GenerateConfig) -> Any:
        if calls["attempted"] >= max_calls:
            raise RemoteBoundaryError("sample model-call cap reached")
        size = _safe_model_input_size(input, tools)
        if size > max_input_bytes:
            raise RemoteBoundaryError("serialized model input exceeds byte cap")
        if config.max_tokens is None or config.max_tokens > max_output_tokens:
            raise RemoteBoundaryError("model output cap is absent or too high")
        if config.max_retries not in (None, 0):
            raise RemoteBoundaryError("Inspect model retries must be disabled")
        calls["attempted"] += 1
        calls["max_input_bytes_seen"] = max(calls["max_input_bytes_seen"], size)
        return await original(input, tools, tool_choice, config)

    model.api.generate = bounded_generate
    return calls


def preflight(plan: RemotePlan) -> dict[str, Any]:
    """Read public rates and the ledger; never issue an inference request."""
    plan.validate()
    rates = pricing_snapshot(plan.model_id)
    reservation = reserve_worst_case(
        rates, MAX_CALLS_PER_SAMPLE, plan.max_input_bytes, plan.max_output_tokens,
    )
    ledger = BudgetLedger(plan.ledger_path).snapshot() if plan.ledger_path.exists() else None
    return {
        "model_id": plan.model_id,
        "sample_ids": list(plan.sample_ids),
        "project_cap_usd": _dollars(plan.cap_usd),
        "max_calls_per_sample": MAX_CALLS_PER_SAMPLE,
        "max_output_tokens_per_call": plan.max_output_tokens,
        "max_serialized_input_bytes_per_call": plan.max_input_bytes,
        "worst_case_reservation_usd_per_sample": _dollars(reservation),
        "pricing": rates,
        "ledger": ledger,
        "ready_to_execute": bool(
            ledger is not None and not ledger["blocked"]
            and Decimal(ledger["available_usd"]) >= reservation
        ),
    }


def _execution_enabled() -> None:
    if os.environ.get("ALLOW_EXTERNAL_MODEL_CALLS", "false").lower() != "true":
        raise RemoteBoundaryError("ALLOW_EXTERNAL_MODEL_CALLS must be true")
    try:
        configured = Decimal(os.environ.get("MAX_REAL_SPEND", "0"))
    except Exception as exc:
        raise RemoteBoundaryError("MAX_REAL_SPEND must be a USD decimal") from exc
    if configured != PROJECT_CAP_USD:
        raise RemoteBoundaryError("MAX_REAL_SPEND must equal the approved USD 20 cap")
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise RemoteBoundaryError("OPENROUTER_API_KEY is missing")
    if os.environ.get("ALLOW_MAINNET", "false").lower() == "true":
        raise RemoteBoundaryError("mainnet must remain disabled")


def _usage_for(log: Any, model_id: str) -> Any:
    if not log.samples or len(log.samples) != 1:
        raise RemoteBoundaryError("one Inspect sample with usage is required")
    usage = log.samples[0].model_usage
    if not usage or len(usage) != 1:
        raise RemoteBoundaryError("provider usage is absent or ambiguous")
    name, value = next(iter(usage.items()))
    if not name.endswith(model_id):
        raise RemoteBoundaryError("provider usage model differs from approved ID")
    if value.total_tokens <= 0 or value.output_tokens < 0 or value.input_tokens < 0:
        raise RemoteBoundaryError("provider token accounting is incomplete")
    return value


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def execute(plan: RemotePlan, *, pricing: dict[str, Any]) -> dict[str, Any]:
    """Run each sample serially after a durable project-budget reservation."""
    plan.validate()
    _execution_enabled()
    if plan.ledger_path.resolve() != PROJECT_LEDGER_PATH.resolve():
        raise RemoteBoundaryError("paid runs must use the one project-wide budget ledger")
    if not plan.ledger_path.exists():
        raise RemoteBoundaryError("project budget ledger has not been initialized")
    reservation = reserve_worst_case(
        pricing, MAX_CALLS_PER_SAMPLE, plan.max_input_bytes, plan.max_output_tokens,
    )
    ledger = BudgetLedger(plan.ledger_path)
    ledger.snapshot()  # fail closed on tamper, uncertainty, or missing genesis
    plan.output_dir.mkdir(parents=True, exist_ok=False)
    os.chmod(plan.output_dir, 0o700)
    summaries: list[dict[str, Any]] = []
    for sample_id in plan.sample_ids:
        run_id = f"w05-{plan.output_dir.name}-{sample_id}"
        reservation_event = ledger.reserve(
            run_id, reservation, plan.cap_usd,
            metadata={"model_id": plan.model_id, "sample_id": sample_id},
        )
        settled = False
        try:
            sample_dir = plan.output_dir / sample_id
            sample_dir.mkdir(mode=0o700)
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
                model, max_calls=MAX_CALLS_PER_SAMPLE,
                max_input_bytes=plan.max_input_bytes,
                max_output_tokens=plan.max_output_tokens,
            )
            with TemporaryDirectory(prefix="w05-inspect-", dir=plan.output_dir) as temp:
                logs = inspect_eval(
                    reconciliation_orbit(
                        scheduler_seconds=SCHEDULER_SECONDS,
                        task_token_limit=50000,
                        model_behavior_tier="REAL_LLM_REMOTE_APPROVED",
                    ),
                    model=model, sample_id=sample_id, max_samples=1, max_tasks=1,
                    epochs=1, retry_on_error=0, fail_on_error=True,
                    time_limit=SCHEDULER_SECONDS, token_limit=50000,
                    message_limit=24, turn_limit=8,
                    log_dir=temp, log_format="eval", log_model_api=False,
                    display="none", log_level="error",
                )
                if len(logs) != 1:
                    raise RemoteBoundaryError("Inspect returned an unexpected log count")
                log = logs[0]
                if not log.location:
                    raise RemoteBoundaryError("native Inspect log is missing")
                native = sample_dir / "inspect.eval"
                native.write_bytes(Path(log.location).read_bytes())
                os.chmod(native, 0o600)
                secret = os.environ["OPENROUTER_API_KEY"].encode("utf-8")
                if secret in native.read_bytes():
                    native.unlink()
                    raise RemoteBoundaryError("credential appeared in native log")
                usage = _usage_for(log, plan.model_id)
                usage_after = account_usage_usd()
                account_delta = account_usage_delta_usd(usage_before, usage_after)
                estimated_charge = max(
                    estimate_usage(pricing, usage, calls=counters["attempted"]),
                    account_delta,
                )
                if estimated_charge > reservation:
                    raise RemoteBoundaryError("reported usage exceeds reserved worst-case cost")
                ledger.settle(run_id, estimated_charge, f"sha256:{_sha256(native)}")
                settled = True
                if log.status != "success" or log.samples[0].error or log.samples[0].limit:
                    raise RemoteBoundaryError("Inspect sample failed; native log retained")
                result = export_remote_log(
                    log, sample_dir, pricing=pricing,
                    usage=usage, cost_usd=estimated_charge,
                    account_usage_delta_usd=account_delta,
                    reservation_usd=reservation,
                    reservation_event=reservation_event,
                    native_path=native,
                    provider_calls=counters["attempted"],
                    max_input_bytes_seen=counters["max_input_bytes_seen"],
                )
                summaries.append(result)
        except BaseException as exc:
            if not settled:
                # The request may have been billed despite a timeout/error.
                # An UNKNOWN hold conservatively consumes the reservation.
                ledger.mark_unknown(run_id, type(exc).__name__)
            native = sample_dir / "inspect.eval"
            (sample_dir / "STOPPED.json").write_text(
                json.dumps({
                    "run_id": run_id, "status": "PARTIAL",
                    "model_behavior_tier": "REAL_LLM_REMOTE_APPROVED",
                    "payment_tier": "MOCK_LOCAL",
                    "error_type": type(exc).__name__,
                    "budget_state": "SETTLED" if settled else "UNKNOWN",
                    "native_log_sha256": _sha256(native) if native.exists() else None,
                    "complete_outcome_exported": False,
                }, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            raise
    return {"samples": summaries, "ledger": ledger.snapshot()}
