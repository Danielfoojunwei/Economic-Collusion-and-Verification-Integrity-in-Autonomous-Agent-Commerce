"""Fail-stop one-row x402 011 ORBIT/Inspect execution against USD50 ledger.

Import, preflight and static checks are read only. `execute_one` requires a
reviewed frozen assignment, cross-study clearance and explicit local-only
paid-model settings; this prospective branch never executes it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
import json
import os
from pathlib import Path
import shutil
from typing import Any

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log

from .mpp005_boundary import (RemoteBoundaryError, account_usage_delta_usd,
    account_usage_usd, assert_no_key, file_sha, write_json)
from .mpp008_pricing import estimate_model_usage, pricing_snapshots
from .remote_budget import BudgetLedger
from .x402_live011_budget import FEE_HOLD_USD, fee011_failed_request_hold
from .x402_live011_boundary import guard_model_apis, models, verify_raw_model_boundary
from .x402_live011_native import X402LiveNative
from .x402_live011_native_verifier import verify_live_native
from .x402_live011_plan import (AUDITOR_CALLS, CANONICAL_LEDGER,
    CONTINGENCY_USD, MAX_OUTPUT_TOKENS, PROVIDER_CALLS, ROWS,
    UNASSIGNED_RESIDUAL_USD, X402LiveRow, digest, reserve_pair)
from .x402_live011_task import x402_live011_orbit


ROOT = Path(__file__).resolve().parents[2]
ASSIGNMENT = ROOT / "artifacts/gates/X402_LIVE011/assignment-001"
RUNS = ROOT / "artifacts/gates/X402_LIVE011/runs-001"


def run_id(assignment_sha: str, episode_id: str) -> str:
    return f"x402011-{assignment_sha[:12]}-{episode_id}"


@dataclass(frozen=True)
class X402LivePlan:
    assignment_dir: Path = ASSIGNMENT
    runs_dir: Path = RUNS
    ledger_path: Path = CANONICAL_LEDGER

    def validate_static(self):
        from scripts import freeze_x402_live011
        if (self.assignment_dir.resolve() != ASSIGNMENT.resolve()
                or self.runs_dir.resolve() != RUNS.resolve()
                or self.ledger_path.resolve() != CANONICAL_LEDGER.resolve()):
            raise RemoteBoundaryError("x402 011 path differs from frozen shared-ledger study")
        freeze_x402_live011.verify_static()
        return freeze_x402_live011.load_assignment()

    def validate(self):
        from scripts import freeze_x402_live011
        self.validate_static()
        freeze_x402_live011.verify()
        return freeze_x402_live011.load_assignment()


def remaining_headroom(reserves: list[Decimal]) -> Decimal:
    if any(not isinstance(x, Decimal) or not x.is_finite() or x <= 0
           for x in reserves):
        raise RemoteBoundaryError("x402 011 remaining reserve differs")
    return (sum(reserves, Decimal(0)) + CONTINGENCY_USD
            + UNASSIGNED_RESIDUAL_USD)


def _pricing_basis(snapshots: dict) -> dict:
    return {model: {key: value for key, value in item.items()
                    if key != "fetched_utc"}
            for model, item in snapshots.items()}


def _run_set(state: dict, frozen: dict, assignment_sha: str) -> None:
    prior = frozen["prior_ledger_run_ids"]
    own = {run_id(assignment_sha, episode)
           for episode in frozen["execution_order"]}
    if (prior != sorted(set(prior))
            or set(state["runs"]) - set(prior) - own
            or any(ident not in state["runs"] for ident in prior)
            or digest({ident: state["runs"][ident] for ident in prior})
                != frozen["prior_ledger_runs_sha256"]):
        raise RemoteBoundaryError("x402 011 concurrent or prior shared-ledger run changed")


def _ledger(state: dict, frozen: dict, assignment_sha: str,
            *, extra_reserve: Decimal = Decimal(0),
            active_run_id: str | None = None) -> None:
    if (state["cap_usd"] != "50" or state["blocked"]
            or state["unknown_run_ids"]
            or Decimal(state["reserved_usd"]) !=
               Decimal("6.30784") + FEE_HOLD_USD + extra_reserve):
        raise RemoteBoundaryError("x402 011 ledger unknown/concurrent reserve differs")
    fee011_failed_request_hold(state, additional_reservation_usd=extra_reserve,
                               active_x402_run_id=active_run_id)
    _run_set(state, frozen, assignment_sha)


def fresh_budget(frozen: dict, assignment_sha: str,
                 remaining: tuple[X402LiveRow, ...]) -> tuple[dict, dict, dict]:
    state = BudgetLedger(CANONICAL_LEDGER).snapshot()
    _ledger(state, frozen, assignment_sha)
    prices = pricing_snapshots()
    if _pricing_basis(prices) != _pricing_basis(frozen["public_pricing_snapshot"]):
        raise RemoteBoundaryError("x402 011 model catalog changed after frozen assignment")
    reserves = {row.episode_id: max(
        Decimal(frozen["budget_gate"]["per_row_worst_case_usd"][row.episode_id]),
        reserve_pair(prices, row)) for row in remaining}
    if remaining_headroom(list(reserves.values())) > Decimal(state["available_usd"]):
        raise RemoteBoundaryError("x402 011 entire remaining block exceeds USD50 headroom")
    return prices, reserves, state


def preflight(plan: X402LivePlan = X402LivePlan()) -> dict:
    from scripts.collect_x402_live011 import verify_episode
    frozen, assignment_sha, rows = plan.validate()
    ledger = BudgetLedger(plan.ledger_path).snapshot()
    _ledger(ledger, frozen, assignment_sha)
    next_index = None
    for index, row in enumerate(rows):
        directory = plan.runs_dir / "episodes" / row.episode_id
        if (directory / "STOPPED.json").exists():
            raise RemoteBoundaryError("earlier x402 011 row stopped; no later paid call")
        if (directory / "episode_record.json").is_file():
            if next_index is not None:
                raise RemoteBoundaryError("x402 011 completed row after execution gap")
            verify_episode(row, directory, assignment_sha=assignment_sha, ledger=ledger)
        elif directory.exists():
            raise RemoteBoundaryError("partial x402 011 row exists; no retry")
        elif next_index is None:
            next_index = index
    if next_index is None:
        raise RemoteBoundaryError("all four assigned x402 011 rows already attempted")
    row = rows[next_index]
    ident = run_id(assignment_sha, row.episode_id)
    if ident in ledger["runs"]:
        raise RemoteBoundaryError("assigned x402 011 ledger run ID already used")
    _, reserves, state = fresh_budget(frozen, assignment_sha, rows[next_index:])
    return {"status": "PREFLIGHT_PASS_NO_PAID_CALL",
            "assignment_manifest_sha256": assignment_sha,
            "next_index": next_index, "next_episode_id": row.episode_id,
            "next_run_id": ident, "per_row_reserve_usd": str(reserves[row.episode_id]),
            "full_remaining_headroom_usd": str(remaining_headroom(list(reserves.values()))),
            "ledger_available_usd": state["available_usd"],
            "ledger_seq": state["seq"],
            "role_models": {"provider": row.provider_model_id,
                            "auditor": row.auditor_model_id},
            "reasoning_effort_by_role": {"provider": "high", "auditor": "high"}}


def _enabled() -> None:
    if (os.environ.get("ALLOW_EXTERNAL_MODEL_CALLS", "false").lower() != "true"
            or Decimal(os.environ.get("MAX_REAL_SPEND", "0")) != Decimal("50")
            or not os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("ALLOW_TESTNET", "false").lower() == "true"
            or os.environ.get("ALLOW_MAINNET", "false").lower() == "true"):
        raise RemoteBoundaryError("approved USD50 remote-model and local-only settings required")


def _usage_estimate(log: Any, prices: dict, observed: list[dict]) -> Decimal:
    usage = log.samples[0].model_usage
    counts = Counter(item["model"].removeprefix("openrouter/") for item in observed)
    if set(usage) != {"openrouter/" + name for name in counts}:
        raise RemoteBoundaryError("x402 011 usage routes differ from forwarded requests")
    return sum((estimate_model_usage(prices[name], usage["openrouter/" + name], count)
                for name, count in counts.items()), Decimal(0))


def _partial_artifacts(directory: Path) -> list[dict]:
    result = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            assert_no_key(path)
            result.append({"path": str(path.relative_to(directory)),
                           "sha256": file_sha(path)})
        except RemoteBoundaryError:
            path.unlink()
    return result


def _stopped_model_events(directory: Path, observed: list[dict]) -> dict:
    """Preserve Inspect's model outcomes separately from API-wrapper returns.

    A wrapper returning does not establish a successful saved ModelEvent or a
    billable request. The FEE011 stop showed exactly that discrepancy. Failed
    events and missing logs remain unresolved; neither can support settlement.
    """
    archived = directory / "inspect.eval"
    work = sorted((directory / "inspect_work").glob("*.eval"))
    candidates = ([archived] if archived.is_file() else []) + work
    inventory = [{"path": str(path.relative_to(directory)),
                  "sha256": file_sha(path)} for path in candidates]
    single = (len(work) <= 1 and candidates and
              (not archived.is_file() or not work or
               inventory[0]["sha256"] == inventory[1]["sha256"]))
    if not single:
        return {"status": "NO_SINGLE_INSPECT_ARCHIVE",
                "inspect_archive_inventory": inventory,
                "guarded_api_invocations": len(observed),
                "guard_completed_returns": sum(item.get("completed") is True
                                               for item in observed)}
    try:
        selected = archived if archived.is_file() else work[0]
        log = read_eval_log(str(selected), resolve_attachments=True)
        samples = log.samples or []
        if len(samples) != 1:
            raise ValueError("Inspect stopped archive sample count differs")
        events = [item for item in samples[0].events if item.event == "model"]
        successful = sum(not item.error for item in events)
        completed = sum(item.get("completed") is True for item in observed)
        return {"status": "REPLAYED_INSPECT_MODEL_EVENTS",
                "inspect_path": str(selected.relative_to(directory)),
                "inspect_sha256": file_sha(selected),
                "inspect_archive_inventory": inventory,
                "eval_status": log.status,
                "guarded_api_invocations": len(observed),
                "guard_completed_returns": completed,
                "inspect_model_events": len(events),
                "inspect_successful_model_events": successful,
                "inspect_failed_model_events": len(events) - successful,
                "guard_inspect_counts_agree":
                    len(events) == len(observed) and successful == completed,
                "provider_billing_for_failed_events": "UNVERIFIED"}
    except Exception as exc:
        return {"status": "INSPECT_ARCHIVE_UNVERIFIED",
                "inspect_path": str(selected.relative_to(directory)),
                "inspect_sha256": file_sha(selected),
                "inspect_archive_inventory": inventory,
                "read_error_type": type(exc).__name__,
                "guarded_api_invocations": len(observed),
                "guard_completed_returns": sum(item.get("completed") is True
                                               for item in observed)}


def _stopped_account_usage(before: Decimal | None) -> dict:
    if before is None:
        return {"status": "NO_PRECALL_ACCOUNT_BASELINE",
                "failed_call_billing": "UNVERIFIED"}
    try:
        after = account_usage_usd()
        delta = account_usage_delta_usd(before, after)
        return {"status": "AGGREGATE_ACCOUNT_DELTA_OBSERVED",
                "before_usd": str(before), "after_usd": str(after),
                "aggregate_delta_usd": str(delta),
                "failed_call_billing": "UNVERIFIED",
                "scope": "whole OpenRouter account; not a per-call receipt"}
    except Exception as exc:
        return {"status": "ACCOUNT_DELTA_UNVERIFIED",
                "before_usd": str(before), "read_error_type": type(exc).__name__,
                "failed_call_billing": "UNVERIFIED"}


def execute_one(plan: X402LivePlan = X402LivePlan()) -> dict:
    preview = preflight(plan)
    _enabled()
    from scripts.collect_x402_live011 import verify_episode
    frozen, assignment_sha, rows = plan.validate()
    row = rows[preview["next_index"]]
    ident = run_id(assignment_sha, row.episode_id)
    prices, reserves, _ = fresh_budget(frozen, assignment_sha,
                                        rows[preview["next_index"]:])
    reserve = reserves[row.episode_id]
    directory = plan.runs_dir / "episodes" / row.episode_id
    directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.mkdir(mode=0o700)
    ledger = BudgetLedger(plan.ledger_path)
    reserved = settled = False
    observed: list[dict] = []
    before: Decimal | None = None
    try:
        state = ledger.reserve(ident, reserve, Decimal("50"), metadata={
            "episode_id": row.episode_id, "assignment_sha": assignment_sha,
            "provider_model_id": row.provider_model_id,
            "auditor_model_id": row.auditor_model_id})
        reserved = True
        _ledger(state, frozen, assignment_sha, extra_reserve=reserve,
                active_run_id=ident)
        if (remaining_headroom([reserves[r.episode_id] for r in
                rows[preview["next_index"] + 1:]]) > Decimal(state["available_usd"])):
            raise RemoteBoundaryError("post-reserve x402 011 remaining headroom changed")
        with X402LiveNative(row, directory / "native") as native:
            task = x402_live011_orbit(row, retainer_receipt=native.retainer,
                native_check=native.buy_check, native_settle=native.settle,
                model_behavior_tier="REAL_LLM_REMOTE_APPROVED")
            before = account_usage_usd()
            role_models = models(row)
            observed = guard_model_apis(role_models, row)
            logs = inspect_eval(task, model=role_models["provider"],
                sample_id=row.episode_id, max_samples=1, max_tasks=1,
                epochs=1, retry_on_error=0, fail_on_error=True,
                time_limit=1860, token_limit=650_000,
                message_limit=96, turn_limit=PROVIDER_CALLS + AUDITOR_CALLS,
                log_dir=str(directory / "inspect_work"), log_format="eval",
                log_model_api=False, display="none", log_level="error")
            if len(logs) != 1 or not logs[0].location:
                raise RemoteBoundaryError("one saved x402 011 Inspect log required")
            raw = Path(logs[0].location)
            assert_no_key(raw)
            target = directory / "inspect.eval"
            shutil.copyfile(raw, target)
            os.chmod(target, 0o600)
            if file_sha(raw) != file_sha(target):
                raise RemoteBoundaryError("x402 011 Inspect archive copy changed")
            saved = read_eval_log(str(target), resolve_attachments=True)
            boundary = verify_raw_model_boundary(saved, observed, row)
            estimate = _usage_estimate(saved, prices, observed)
            after = account_usage_usd()
            delta = account_usage_delta_usd(before, after)
            cost = max(estimate, delta)
            if cost > reserve:
                raise RemoteBoundaryError("x402 011 model cost exceeds reserved cap")
            ledger.settle(ident, cost, "sha256:" + file_sha(target))
            settled = True
            latest = ledger.snapshot()
            _ledger(latest, frozen, assignment_sha)
            if (remaining_headroom([reserves[r.episode_id] for r in
                    rows[preview["next_index"] + 1:]]) > Decimal(latest["available_usd"])):
                raise RemoteBoundaryError("post-settlement x402 011 block headroom changed")
        if native.settlement is None:
            raise RemoteBoundaryError("auditor made no terminal verdict; preserve stopped row")
        native_result = verify_live_native(directory / "native", row)
        if native_result["status"] != "PASS":
            raise RemoteBoundaryError("x402 011 native receipt replay failed")
        plan.validate_static()  # source seal only; ledger was legitimately mutated
        record = {"schema": "x402-live011-paid-episode-v1", "status": "COMPLETE",
                  "episode_id": row.episode_id,
                  "assignment_manifest_sha256": assignment_sha,
                  "provider_model_id": row.provider_model_id,
                  "auditor_model_id": row.auditor_model_id,
                  "model_tier": "REAL_LLM_REMOTE_APPROVED",
                  "payment_tier": "NATIVE_LOCAL_PROTOCOL",
                  "reasoning_effort_by_role": {"provider": "high", "auditor": "high"},
                  "reasoning_history": "none",
                  "http_client_max_retries_by_role": {"provider": 0, "auditor": 0},
                  "ledger_run_id": ident, "model_cost_usd": str(cost),
                  "model_request_boundary": observed, "raw_model_boundary": boundary,
                  "inspect_sha256": file_sha(directory / "inspect.eval"),
                  "native_path": "native/native-bridge.json",
                  "native_sha256": file_sha(directory / "native/native-bridge.json"),
                  "usage_estimate_usd": str(estimate),
                  "account_usage_before_usd": str(before),
                  "account_usage_after_usd": str(after),
                  "account_usage_delta_usd": str(delta),
                  "fresh_public_pricing_snapshots": prices}
        write_json(directory / "episode_record.json", record)
        return verify_episode(row, directory,
                              assignment_sha=assignment_sha, ledger=ledger.snapshot())
    except BaseException as exc:
        record = directory / "episode_record.json"
        if record.exists():
            record.rename(directory / "unverified_episode_record.json")
        unknown = False
        if reserved and not settled:
            try:
                ledger.mark_unknown(ident, type(exc).__name__)
                unknown = True
            except Exception:
                pass
        partial = _partial_artifacts(directory)
        model_events = _stopped_model_events(directory, observed)
        account_usage = _stopped_account_usage(before)
        write_json(directory / "STOPPED.json", {
            "schema": "x402-live011-stopped-episode-v1",
            "episode_id": row.episode_id,
            "assignment_manifest_sha256": assignment_sha,
            "error_type": type(exc).__name__,
            "ledger_run_id": ident,
            "budget_state": "SETTLED" if settled else
                "UNKNOWN" if unknown else "UNRESOLVED" if reserved else "UNRESERVED",
            "model_request_boundary": observed,
            "stopped_model_events": model_events,
            "stopped_account_usage": account_usage,
            "partial_artifacts": partial,
            "no_retry_or_substitution": True,
            "complete_native_claim": False,
            "prior_native_terminal_possible": True})
        raise
