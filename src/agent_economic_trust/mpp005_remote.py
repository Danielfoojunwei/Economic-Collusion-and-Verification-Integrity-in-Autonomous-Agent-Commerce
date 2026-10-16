"""One bounded remote-model meeting episode with native local MPP consequences.

The execution entry point has no loop. A saved row is not scientific evidence
until the separate collector reopens its raw model and payment receipts.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
import json
import os
from pathlib import Path
import shutil
from typing import Any

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log
from inspect_ai.model import GenerateConfig, get_model

from .mpp005_plan import (CONTINGENCY_USD, EVAL_TOKEN_LIMIT, MAX_CALLS_PER_EPISODE,
    MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS, MODEL_ID, SCHEDULER_SECONDS, TASK_TOKEN_LIMIT,
    CANONICAL_LEDGER_PATH)
from .mpp005_boundary import (REQUEST_TIMEOUT_SECONDS, RemoteBoundaryError,
    _usage_for, account_usage_delta_usd, account_usage_usd, assert_no_key,
    file_sha, guard_api, verify_model_boundary, write_json)
from .remote_budget import BudgetLedger
from .remote_pricing import estimate_usage, pricing_snapshot, reserve_worst_case


ROOT = Path(__file__).resolve().parents[2]
ASSIGNMENT = ROOT / "artifacts/gates/MPP005/assignment-meeting-001"
RUNS = ROOT / "artifacts/gates/MPP005/runs-meeting-001"


def run_id(assignment_sha: str, episode_id: str) -> str:
    return f"mpp005-{assignment_sha[:12]}-{episode_id}"


@dataclass(frozen=True)
class Mpp005Plan:
    assignment_dir: Path = ASSIGNMENT
    runs_dir: Path = RUNS
    ledger_path: Path = CANONICAL_LEDGER_PATH
    model_id: str = MODEL_ID
    max_calls: int = MAX_CALLS_PER_EPISODE
    max_input_bytes: int = MAX_INPUT_BYTES
    max_output_tokens: int = MAX_OUTPUT_TOKENS

    def validate(self) -> tuple[dict, str, tuple]:
        from scripts import freeze_mpp005
        if (self.assignment_dir.resolve() != ASSIGNMENT.resolve()
                or self.runs_dir.resolve() != RUNS.resolve()
                or self.ledger_path.resolve() != CANONICAL_LEDGER_PATH.resolve()
                or self.model_id != MODEL_ID or self.max_calls != MAX_CALLS_PER_EPISODE
                or self.max_input_bytes != MAX_INPUT_BYTES
                or self.max_output_tokens != MAX_OUTPUT_TOKENS):
            raise RemoteBoundaryError("MPP005 runner differs from canonical frozen assignment")
        freeze_mpp005.verify()
        return freeze_mpp005.load_assignment(self.assignment_dir)


def fresh_budget(plan: Mpp005Plan, frozen: dict, remaining: int) -> tuple[dict, Decimal, dict]:
    from scripts import freeze_mpp005
    freeze_mpp005.verify()
    state = BudgetLedger(plan.ledger_path).snapshot()
    if (state["blocked"] or state["unknown_run_ids"] or state["cap_usd"] != "50"
            or Decimal(state["reserved_usd"]) != 0):
        raise RemoteBoundaryError("shared lifetime ledger blocked or a concurrent reservation is active")
    rates = pricing_snapshot(plan.model_id)
    reserve = max(Decimal(frozen["worst_case_reserve_usd_per_episode"]),
                  reserve_worst_case(rates, plan.max_calls, plan.max_input_bytes, plan.max_output_tokens))
    if reserve * remaining + Decimal(CONTINGENCY_USD) > Decimal(state["available_usd"]):
        raise RemoteBoundaryError("full remaining MPP005 block plus contingency exceeds USD50 headroom")
    return rates, reserve, state


def preflight(plan: Mpp005Plan = Mpp005Plan()) -> dict:
    from .mpp005_reporting import verify_episode
    frozen, assignment_sha, rows = plan.validate()
    by_id = {row.episode_id: row for row in rows}
    if len(by_id) != len(rows) or set(by_id) != set(frozen["execution_order"]):
        raise RemoteBoundaryError("frozen MPP005 order or denominator differs")
    ledger = BudgetLedger(plan.ledger_path).snapshot()
    next_index = None
    for index, episode_id in enumerate(frozen["execution_order"]):
        row = by_id[episode_id]
        directory = plan.runs_dir / "episodes" / episode_id
        if (directory / "STOPPED.json").exists():
            raise RemoteBoundaryError("earlier MPP005 row stopped; no reroll or later paid calls")
        if (directory / "episode_record.json").is_file():
            if next_index is not None:
                raise RemoteBoundaryError("completed episode after a gap in frozen order")
            verify_episode(row, directory, assignment_sha=assignment_sha, ledger=ledger)
        elif directory.exists():
            raise RemoteBoundaryError("partial assigned episode exists; no retry")
        elif next_index is None:
            next_index = index
    if next_index is None:
        raise RemoteBoundaryError("all assigned MPP005 episodes already attempted")
    row = by_id[frozen["execution_order"][next_index]]
    if run_id(assignment_sha, row.episode_id) in ledger["runs"]:
        raise RemoteBoundaryError("assigned ledger run ID already exists")
    rates, reserve, state = fresh_budget(plan, frozen, len(rows) - next_index)
    return {"mode": "dry-run", "ready_to_execute": True,
            "next_episode_id": row.episode_id, "next_arm": row.arm,
            "next_index": next_index, "remaining_episodes": len(rows) - next_index,
            "assignment_manifest_sha256": assignment_sha,
            "next_reservation_usd": str(reserve),
            "full_remaining_reservation_usd": str(reserve * (len(rows) - next_index)),
            "contingency_usd": CONTINGENCY_USD, "available_usd": state["available_usd"],
            "fresh_public_pricing": rates, "model_id": plan.model_id,
            "reasoning_effort": "high", "reasoning_history": "none",
            "max_calls": plan.max_calls, "max_input_bytes": plan.max_input_bytes,
            "max_output_tokens": plan.max_output_tokens, "max_retries": 0}


def _execution_enabled() -> None:
    try:
        limit = Decimal(os.environ.get("MAX_REAL_SPEND", "0"))
    except Exception as exc:
        raise RemoteBoundaryError("MAX_REAL_SPEND must be numeric") from exc
    if (os.environ.get("ALLOW_EXTERNAL_MODEL_CALLS", "false").lower() != "true"
            or limit != Decimal("50") or not os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("ALLOW_TESTNET", "false").lower() == "true"
            or os.environ.get("ALLOW_MAINNET", "false").lower() == "true"):
        raise RemoteBoundaryError("approved local-only USD50 model route is unavailable")


def _verify_partial_native(log: Any, service: Any, *, quality: str) -> list[dict[str, Any]]:
    """Incomplete model episodes retain real charges but no imputed verdict."""
    if log.status != "success" or len(log.samples or []) != 1 or log.samples[0].error:
        raise RemoteBoundaryError("incomplete Inspect run lacks trustworthy partial sample")
    sample = log.samples[0]
    if sample.store.get("OpenMppStore:decision") is not None:
        raise RemoteBoundaryError("a saved decision failed full independent verification")
    records = sample.store.get("NativeServiceStore:operations") or []
    if len(records) > 1 or any(record.get("operation") != "check" for record in records):
        raise RemoteBoundaryError("incomplete native operations are ambiguous")
    # service.operate writes request/proof before the Store append. A failed
    # ToolError can leave a real paid debit with no Store record; never turn it
    # into an observed zero. Preserve the files and stop further paid rows.
    if any(event.event == "tool" and event.function in {"market_check", "market_decide"}
           and event.error for event in sample.events):
        raise RemoteBoundaryError("failed native tool may have paid before error")
    for operation in ("check", "release"):
        request_exists = (service.evidence_dir / f"{operation}-request.json").exists()
        evidence_exists = (service.evidence_dir / f"{operation}-evidence.json").exists()
        recorded = any(record["operation"] == operation for record in records)
        if request_exists != recorded or evidence_exists != recorded:
            raise RemoteBoundaryError("unrecorded native request or evidence may have paid")
    successful = [event for event in sample.events if event.event == "tool"
                  and event.function == "market_check" and not event.error]
    if bool(successful) != bool(records):
        raise RemoteBoundaryError("native check Store and raw tool trace differ")
    verified = []
    for record in records:
        evidence = asyncio.run(service.verify(record))
        from .meeting_booking_market import BookingMarket, calendar_record
        if (evidence["request"]["buyer_calendar"] != calendar_record(quality)
                or evidence["request"]["public_service"]["artifact_digest"]
                   != BookingMarket(quality).public_view()["artifact_digest"]
                or evidence["payer_role"] != "auditor" or evidence["payee_role"] != "oracle"
                or evidence["amount_atomic"] != 2_000):
            raise RemoteBoundaryError("partial paid check truth, binding or recipient differs")
        verified.append({"operation": record["operation"],
                         "evidence_sha256": record["sha256"],
                         "amount_atomic": evidence["amount_atomic"]})
    return verified


def execute_one(plan: Mpp005Plan = Mpp005Plan()) -> dict:
    """Execute exactly the next frozen row after a fresh full-block reservation."""
    preview = preflight(plan)
    _execution_enabled()
    from .open_mpp_native_service import NativeMeetingService, inspect_native_service_log, native_service_orbit
    frozen, assignment_sha, rows = plan.validate()
    row = next(r for r in rows if r.episode_id == preview["next_episode_id"])
    directory = plan.runs_dir / "episodes" / row.episode_id
    directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.mkdir(mode=0o700)
    os.chmod(directory, 0o700)
    service = NativeMeetingService((directory / "native").resolve())
    ledger = BudgetLedger(plan.ledger_path)
    ident = run_id(assignment_sha, row.episode_id)
    observed: list[dict] = []
    reserved = settled = False
    try:
        asyncio.run(service.prepare())
        task = native_service_orbit(row.truth, service=service, condition=row.arm,
            trial_id=row.trial_id, scheduler_seconds=SCHEDULER_SECONDS,
            task_token_limit=TASK_TOKEN_LIMIT)
        before = account_usage_usd()
        config = GenerateConfig(reasoning_effort="high", reasoning_history="none",
            max_tokens=plan.max_output_tokens, max_retries=0,
            timeout=REQUEST_TIMEOUT_SECONDS, max_connections=1, cache=False)
        model = get_model(f"openrouter/{plan.model_id}", config=config, memoize=False,
            base_url="https://openrouter.ai/api/v1", max_retries=0,
            stream=False, responses_api=False)
        observed = guard_api(model, plan)
        prices, reserve, _ = fresh_budget(plan, frozen, preview["remaining_episodes"])
        snapshot = ledger.reserve(ident, reserve, Decimal("50"),
            metadata={"model_id": plan.model_id, "episode_id": row.episode_id,
                      "assignment_sha": assignment_sha})
        reserved = True
        if Decimal(snapshot["available_usd"]) < (
                reserve * (preview["remaining_episodes"] - 1) + Decimal(CONTINGENCY_USD)):
            raise RemoteBoundaryError("concurrent spending consumed remaining block reserve")
        logs = inspect_eval(task, model=model, sample_id=row.trial_id,
            max_samples=1, max_tasks=1, epochs=1, retry_on_error=0, fail_on_error=True,
            time_limit=SCHEDULER_SECONDS, token_limit=EVAL_TOKEN_LIMIT,
            message_limit=80, turn_limit=MAX_CALLS_PER_EPISODE,
            log_dir=str(directory / "inspect_work"), log_format="eval",
            log_model_api=False, display="none", log_level="error")
        if len(logs) != 1 or not logs[0].location:
            raise RemoteBoundaryError("one saved Inspect log required")
        raw = Path(logs[0].location)
        assert_no_key(raw)
        target = directory / "inspect.eval"
        shutil.copyfile(raw, target)
        os.chmod(target, 0o600)
        if file_sha(raw) != file_sha(target):
            raise RemoteBoundaryError("Inspect archive copy differs")
        saved = read_eval_log(str(target), resolve_attachments=True)
        estimated = estimate_usage(prices, _usage_for(logs[0], plan.model_id), calls=len(observed))
        after = account_usage_usd()
        account_delta = account_usage_delta_usd(before, after)
        cost = max(estimated, account_delta)
        if cost > reserve:
            raise RemoteBoundaryError("observed charge exceeds prospective reservation")
        ledger.settle(ident, cost, "sha256:" + file_sha(target))
        settled = True
        verify_model_boundary(saved, observed, plan)
        if saved.samples[0].store.get("OpenMppStore:decision") is None:
            partial = _verify_partial_native(saved, service, quality=row.truth)
            decision = None
            status = "OBSERVED_INCOMPLETE"
        else:
            decision = asyncio.run(inspect_native_service_log(saved, service=service,
                quality=row.truth, condition=row.arm,
                expected_model=f"openrouter/{plan.model_id}", require_real_model=True))
            write_json(directory / "decision.json", decision)
            flow = decision["selected_flow"]
            compensation = directory / "native/compensation-evidence.json"
            asyncio.run(service._command(ROOT / "protocols/mpp/meeting-local.mjs",
                directory / "decision.json", flow, compensation))
            asyncio.run(service._command(ROOT / "protocols/mpp/verify-meeting-evidence.mjs", compensation))
            partial = []
            status = "COMPLETE"
        plan.validate()
        record = {"schema": "mpp005-paid-episode-v1", "status": status,
            "episode_id": row.episode_id, "assignment_manifest_sha256": assignment_sha,
            "model_id": plan.model_id, "reasoning_effort": "high", "reasoning_history": "none",
            "model_execution_tier": "REAL_LLM_REMOTE_APPROVED", "transaction_tier": "NATIVE_LOCAL_PROTOCOL",
            "model_request_boundary": observed, "ledger_run_id": ident,
            "model_cost_usd": str(cost), "inspect_sha256": file_sha(target),
            "usage_estimate_usd": str(estimated),
            "account_usage_before_usd": str(before),
            "account_usage_after_usd": str(after),
            "account_usage_delta_usd": str(account_delta),
            "fresh_public_pricing_snapshot": prices,
            "prepare_sha256": file_sha(directory / "native/prepare-evidence.json"),
            "decision_sha256": decision["decision_sha256"] if decision else None,
            "compensation_sha256": file_sha(compensation) if decision else None,
            "partial_native_operations": partial,
            "no_verdict_endpoints": "UNRESOLVED" if decision is None else None}
        write_json(directory / "episode_record.json", record)
        from .mpp005_reporting import verify_episode
        return verify_episode(row, directory, assignment_sha=assignment_sha, ledger=ledger.snapshot())
    except BaseException as exc:
        unknown = False
        secondary: list[str] = []
        if reserved and not settled:
            try:
                ledger.mark_unknown(ident, type(exc).__name__)
                unknown = True
            except Exception as error:
                secondary.append("billing:" + type(error).__name__)
        partial_files: list[dict[str, str]] = []
        removed: list[str] = []
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                assert_no_key(path)
                partial_files.append({"path": str(path.relative_to(directory)), "sha256": file_sha(path)})
            except RemoteBoundaryError:
                removed.append(str(path.relative_to(directory)))
                path.unlink()
            except Exception as error:
                secondary.append("partial_inventory:" + type(error).__name__)
        write_json(directory / "STOPPED.json", {
            "schema": "mpp005-stopped-episode-v1", "episode_id": row.episode_id,
            "assignment_manifest_sha256": assignment_sha,
            "error_type": type(exc).__name__, "budget_state": "SETTLED" if settled else
                            "UNKNOWN" if unknown else "UNRESOLVED" if reserved else "UNRESERVED",
            "ledger_run_id": ident, "model_calls_attempted": len(observed),
            "model_request_boundary": observed, "partial_artifacts": partial_files,
            "removed_secret_artifacts": removed, "no_retry_or_substitution": True,
            "complete_payment_claim": False, "secondary_failure_types": secondary})
        raise
