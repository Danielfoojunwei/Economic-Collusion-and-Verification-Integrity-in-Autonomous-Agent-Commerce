"""Bounded, single-case live readiness route for ORBIT Meeting Scheduling.

Seed 211 is predeclared as a held-out exploratory pilot. Dry-run does not
instantiate it and never requests model inference or reserves money.
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
import zipfile

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log
from inspect_ai.model import GenerateConfig, get_model

from .meeting_generalization import verify_orbit_source
from .remote import (
    APPROVED_MODEL_ID, MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS, PROJECT_CAP_USD,
    PROJECT_LEDGER_PATH, REQUEST_TIMEOUT_SECONDS, SCHEDULER_SECONDS,
    RemoteBoundaryError, _execution_enabled, _sha256, _usage_for,
    account_usage_delta_usd, account_usage_usd, guard_model_api,
)
from .remote_budget import BudgetLedger
from .remote_pricing import estimate_usage, pricing_snapshot, reserve_worst_case
from .w18_meeting_task import heldout_pilot_case, inspect_meeting_log, meeting_audit_orbit


MAX_CALLS = 6
TASK_ID = "orbit-meeting-heldout-211"
TASK_TIER = "EXPLORATORY_HELDOUT_PILOT"
HOLDOUT_PARAMS = {
    "num_agents": 2, "num_meetings": 2, "num_time_slots": 4,
    "strict_meeting_ratio": 0.5, "seed": 211,
}
_PACKAGE = Path(__file__).resolve().parent
_PROJECT_ROOT = _PACKAGE.parents[1]
_CODE_FILES = (
    "core.py", "meeting_generalization.py", "w18_meeting_task.py",
    "w18_meeting_remote.py", "remote.py", "remote_budget.py",
    "remote_pricing.py", "reporting.py",
    "scripts/run_w18_openrouter.py", "scripts/run_w18_openrouter.sh",
)


def _code_hashes() -> dict[str, str]:
    return {
        name: _sha256((_PROJECT_ROOT if name.startswith("scripts/") else _PACKAGE) / name)
        for name in _CODE_FILES
    }


def _assert_frozen(expected: dict[str, str]) -> None:
    if _code_hashes() != expected or _source_guard() != {
        "dataset_builder.py": "2579c1a96a3e800fed861fa3714a519c346aecc985eb4bd1c638ac74878230dc",
        "scorer.py": "e30e060f3ff978b1a96fac1e79a11652efa95abd662e9da5305b5060295b5e8d",
        "task.py": "ab10d0da4d31c256a3ede46b9260b879c04a3ea40b1139f26f4cc9e3986092c2",
    }:
        raise RemoteBoundaryError("W18 code or pinned ORBIT source changed during execution")


def _scan_native_log_for_secret(path: Path, log: Any, secret: str) -> None:
    needle = secret.encode("utf-8")
    if needle in path.read_bytes() or needle in log.model_dump_json().encode("utf-8"):
        raise RemoteBoundaryError("credential appeared in native Inspect evidence")
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > 4096 or sum(member.file_size for member in members) > 128 * 1024 * 1024:
                raise RemoteBoundaryError("native Inspect archive exceeds scan limit")
            for member in members:
                if member.file_size > 64 * 1024 * 1024:
                    raise RemoteBoundaryError("native Inspect member exceeds scan limit")
                if needle in archive.read(member):
                    raise RemoteBoundaryError("credential appeared in native Inspect archive")


def _guard_source_and_reasoning(model: Any, expected: dict[str, str]) -> None:
    """Check frozen source and approved thinking level at every provider call."""
    original = model.api.generate

    async def checked_generate(input: Any, tools: Any, tool_choice: Any,
                               config: GenerateConfig) -> Any:
        _assert_frozen(expected)
        if config.reasoning_effort != "high":
            raise RemoteBoundaryError("provider call lacks approved high reasoning")
        return await original(input, tools, tool_choice, config)

    model.api.generate = checked_generate


def _behavior_signature(log: Any, *, include_inputs: bool = True) -> list[dict[str, Any]]:
    """Compare decision events, optionally omitting unresolved runtime inputs."""
    if not log.samples or len(log.samples) != 1:
        raise RemoteBoundaryError("one Inspect sample is required for native comparison")
    selected: list[dict[str, Any]] = []
    for event in log.samples[0].events:
        if event.event == "model":
            row = {
                "kind": "model", "model": event.model,
                "config": event.config.model_dump(mode="json") if event.config else None,
                "tools": [tool.model_dump(mode="json") for tool in event.tools],
                "output": event.output.model_dump(mode="json") if event.output else None,
            }
            if include_inputs:
                row["input"] = [message.model_dump(mode="json") for message in event.input]
            selected.append(row)
        elif event.event == "tool":
            selected.append({
                "kind": "tool", "function": event.function,
                "arguments": getattr(event, "arguments", None),
                "result": str(event.result),
                "error": str(event.error) if event.error else None,
            })
    return selected


@dataclass(frozen=True)
class MeetingPlan:
    model_id: str
    output_dir: Path
    ledger_path: Path = PROJECT_LEDGER_PATH
    cap_usd: Decimal = PROJECT_CAP_USD
    max_output_tokens: int = MAX_OUTPUT_TOKENS
    max_input_bytes: int = MAX_INPUT_BYTES

    def validate(self) -> None:
        if self.model_id != APPROVED_MODEL_ID or self.cap_usd != PROJECT_CAP_USD:
            raise RemoteBoundaryError("model or cap differs from the exact owner approval")
        if self.ledger_path.resolve() != PROJECT_LEDGER_PATH.resolve():
            raise RemoteBoundaryError("W18 must use the project-wide budget ledger")
        if not 1 <= self.max_output_tokens <= MAX_OUTPUT_TOKENS:
            raise RemoteBoundaryError("output cap is outside approved bounds")
        if not 1024 <= self.max_input_bytes <= MAX_INPUT_BYTES:
            raise RemoteBoundaryError("serialized input cap is outside approved bounds")
        if self.output_dir.exists():
            raise RemoteBoundaryError("output directory already exists")
        if self.output_dir.is_symlink():
            raise RemoteBoundaryError("output directory cannot be a symlink")


def _source_guard() -> dict[str, str]:
    sources = verify_orbit_source()
    if TASK_ID != "orbit-meeting-heldout-211" or HOLDOUT_PARAMS != {
        "num_agents": 2, "num_meetings": 2, "num_time_slots": 4,
        "strict_meeting_ratio": 0.5, "seed": 211,
    }:
        raise RemoteBoundaryError("W18 held-out task identity or parameters changed")
    return sources


def preflight(plan: MeetingPlan) -> dict[str, Any]:
    """Read-only public catalog and budget check; no inference or reservation."""
    plan.validate()
    source_hashes = _source_guard()
    rates = pricing_snapshot(plan.model_id)
    reserve = reserve_worst_case(rates, MAX_CALLS, plan.max_input_bytes,
                                 plan.max_output_tokens)
    ledger = BudgetLedger(plan.ledger_path).snapshot()
    return {
        "mode": "dry-run", "task_id": TASK_ID, "split": "heldout_pilot",
        "task_tier_if_executed": TASK_TIER, "payment_tier": "NO_PAYMENT",
        "model_id": plan.model_id, "reasoning_effort": "high",
        "case_parameters": HOLDOUT_PARAMS,
        "orbit_source_sha256": source_hashes,
        "max_provider_calls": MAX_CALLS,
        "max_input_bytes_per_call": plan.max_input_bytes,
        "max_output_tokens_per_call": plan.max_output_tokens,
        "worst_case_reservation_usd": format(reserve, "f"),
        "pricing": rates, "ledger": ledger,
        "ready_to_execute": bool(
            not ledger["blocked"] and Decimal(ledger["available_usd"]) >= reserve
        ),
    }


def _run_id(output_dir: Path) -> str:
    return "w18-meeting-" + sha256(str(output_dir.resolve()).encode()).hexdigest()[:24]


def _save_json_once(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
    os.chmod(path, 0o600)


def execute(plan: MeetingPlan) -> dict[str, Any]:
    """Run exactly one supervised case with a fresh rate and budget reservation.

    This path is intentionally never invoked by a dry-run or an offline test.
    Unknown billing after a provider attempt blocks subsequent project runs.
    """
    plan.validate()
    _execution_enabled()
    source_hashes = _source_guard()
    code_at_start = _code_hashes()
    # A caller cannot pass a stale or forged pricing snapshot into this boundary.
    rates = pricing_snapshot(plan.model_id)
    reserve = reserve_worst_case(rates, MAX_CALLS, plan.max_input_bytes,
                                 plan.max_output_tokens)
    ledger = BudgetLedger(plan.ledger_path)
    ledger.snapshot()  # verify the hash chain and anchor before external access
    usage_before = account_usage_usd()
    case = heldout_pilot_case()
    if case.task_id != TASK_ID or case.split != "heldout_pilot":
        raise RemoteBoundaryError("constructed held-out task identity changed")
    if case.problem.optimal_schedule is None:
        raise RemoteBoundaryError("held-out pilot lacks an exact reference")
    task = meeting_audit_orbit(
        case, budget_units=1, check_cost_units=1,
        scheduler_seconds=SCHEDULER_SECONDS, task_token_limit=50000,
    )
    _assert_frozen(code_at_start)
    plan.output_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(plan.output_dir, 0o700)
    run_id = _run_id(plan.output_dir)
    reservation = ledger.reserve(
        run_id, reserve, plan.cap_usd,
        metadata={"model_id": plan.model_id, "task_id": TASK_ID,
                  "split": "heldout_pilot", "purpose": "w18_exploratory_readiness"},
    )
    settled = False
    try:
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
            model, max_calls=MAX_CALLS, max_input_bytes=plan.max_input_bytes,
            max_output_tokens=plan.max_output_tokens,
        )
        _guard_source_and_reasoning(model, code_at_start)
        _assert_frozen(code_at_start)
        with TemporaryDirectory(prefix="w18-inspect-", dir=plan.output_dir) as temp:
            logs = inspect_eval(
                task, model=model, sample_id=TASK_ID,
                max_samples=1, max_tasks=1, epochs=1,
                retry_on_error=0, fail_on_error=True,
                time_limit=SCHEDULER_SECONDS, token_limit=50000,
                message_limit=32, turn_limit=10,
                log_dir=temp, log_format="eval", log_model_api=False,
                display="none", log_level="error",
            )
            if len(logs) != 1 or not logs[0].location:
                raise RemoteBoundaryError("native Inspect log is missing")
            _assert_frozen(code_at_start)
            log = logs[0]
            native = plan.output_dir / "inspect.eval"
            with native.open("xb") as stream:
                stream.write(Path(log.location).read_bytes())
            os.chmod(native, 0o600)
            if _sha256(native) != _sha256(Path(log.location)):
                raise RemoteBoundaryError("saved native log bytes differ from Inspect output")
            source_log = read_eval_log(str(log.location), resolve_attachments=True)
            native_log = read_eval_log(str(native), resolve_attachments=True)
            try:
                _scan_native_log_for_secret(native, native_log, os.environ["OPENROUTER_API_KEY"])
            except RemoteBoundaryError:
                native.unlink(missing_ok=True)
                raise
            usage = _usage_for(log, plan.model_id)
            usage_after = account_usage_usd()
            account_delta = account_usage_delta_usd(usage_before, usage_after)
            estimated_charge = max(
                estimate_usage(rates, usage, calls=counters["attempted"]),
                account_delta,
            )
            if estimated_charge > reserve:
                raise RemoteBoundaryError("observed usage exceeds reserved upper bound")
            ledger.settle(run_id, estimated_charge, f"sha256:{_sha256(native)}")
            settled = True
            if log.status != "success" or not log.samples or log.samples[0].error or log.samples[0].limit:
                raise RemoteBoundaryError("Inspect sample failed; native log retained")
            if (native_log.status != log.status or native_log.eval.model != log.eval.model
                    or len(native_log.samples or []) != 1
                    or native_log.samples[0].metadata != log.samples[0].metadata
                    or native_log.samples[0].store != log.samples[0].store
                    or native_log.samples[0].scores != log.samples[0].scores
                    or len(native_log.samples[0].events) != len(log.samples[0].events)
                    or _behavior_signature(native_log) != _behavior_signature(source_log)
                    or _behavior_signature(native_log, include_inputs=False)
                       != _behavior_signature(log, include_inputs=False)):
                raise RemoteBoundaryError("saved native log differs from runtime result")
            inspection = inspect_meeting_log(
                native_log, case, expected_model=f"openrouter/{plan.model_id}",
                require_real_model=True,
            )
            if inspection["model_events"] != counters["attempted"] or not 1 <= counters["attempted"] <= MAX_CALLS:
                raise RemoteBoundaryError("native model events differ from bounded provider calls")
            result = {
                "schema": "w18-meeting-exploratory-live-v1",
                "run_id": run_id, "task_id": TASK_ID, "split": "heldout_pilot",
                "task_tier": TASK_TIER, "model_execution_tier": "REAL_LLM_REMOTE_APPROVED",
                "payment_tier": "NO_PAYMENT", "native_payment_execution": False,
                "holdout": True, "confirmatory": False,
                "model_id": plan.model_id, "reasoning_effort": "high",
                "case_parameters": HOLDOUT_PARAMS,
                "orbit_source_commit": "588b3035f92450ec4f0496bb8b629daa205e84c7",
                "orbit_source_sha256": source_hashes,
                "code_sha256": code_at_start,
                "native_inspect_sha256": _sha256(native),
                "inspection": inspection,
                "provider_calls": counters["attempted"],
                "max_input_bytes_seen": counters["max_input_bytes_seen"],
                "model_usage": usage.model_dump(mode="json"),
                "pricing_snapshot": rates,
                "worst_case_reserved_usd": format(reserve, "f"),
                "estimated_model_cost_usd": format(estimated_charge, "f"),
                "account_usage_delta_usd": format(account_delta, "f"),
                "model_cost_basis": "max_conservative_usage_estimate_and_account_delta_not_invoice",
                "budget_ledger_reservation_hash": reservation["last_hash"],
                "budget_ledger_settlement_hash": ledger.snapshot()["last_hash"],
                "caveat": "One predeclared held-out exploratory task; no economic randomization, native payment, or G7 claim.",
            }
            _save_json_once(plan.output_dir / "evidence.json", result)
            return result
    except BaseException as exc:
        if not settled:
            ledger.mark_unknown(run_id, type(exc).__name__)
        native = plan.output_dir / "inspect.eval"
        _save_json_once(plan.output_dir / "STOPPED.json", {
            "status": "PARTIAL", "run_id": run_id,
            "error_type": type(exc).__name__,
            "budget_state": "SETTLED" if settled else "UNKNOWN",
            "native_log_sha256": _sha256(native) if native.exists() else None,
            "complete_outcome_exported": False,
        })
        raise
