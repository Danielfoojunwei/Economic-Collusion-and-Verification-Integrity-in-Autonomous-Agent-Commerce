"""One-row, fail-stop FEE012 live-model runner against the shared USD50 ledger."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
import os
from pathlib import Path
import shutil
from typing import Any

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log

from .erc8183_fee_native import FeeNativeController
from .erc8183_fee_native_verifier import verify_file as verify_native_file
from .erc8183_fee_remote import _enabled
from .fee012_boundary import guard_model_apis, models, verify_boundary
from .fee012_budget import exact_prior_holds
from .fee012_plan import (AUDITOR_CALLS, CANONICAL_LEDGER, CONTINGENCY_USD,
                          PROVIDER_CALLS, ROWS, UNASSIGNED_RESIDUAL_USD,
                          Fee012Row, digest, per_row_reserve, required_headroom)
from .fee012_task import fee012_invoice_orbit
from .mpp005_boundary import (RemoteBoundaryError, account_usage_delta_usd,
                               account_usage_usd, assert_no_key, file_sha,
                               write_json)
from .mpp008_pricing import estimate_model_usage, pricing_snapshots
from .remote_budget import BudgetLedger
from .x402_live012_remote import (_partial_artifacts, _stopped_account_usage,
                                   _stopped_model_events)


ROOT = Path(__file__).resolve().parents[2]
ASSIGNMENT = ROOT / "artifacts/gates/ERC8183_FEE012/assignment-001"
RUNS = ROOT / "artifacts/gates/ERC8183_FEE012/runs-001"


def run_id(assignment_sha: str, episode_id: str) -> str:
    return f"fee012-{assignment_sha[:12]}-{episode_id}"


@dataclass(frozen=True)
class Fee012Plan:
    assignment_dir: Path = ASSIGNMENT
    runs_dir: Path = RUNS
    ledger_path: Path = CANONICAL_LEDGER

    def validate_static(self):
        from scripts import fee012_freeze
        if (self.assignment_dir.resolve() != ASSIGNMENT.resolve()
                or self.runs_dir.resolve() != RUNS.resolve()
                or self.ledger_path.resolve() != CANONICAL_LEDGER.resolve()):
            raise RemoteBoundaryError("FEE012 paths differ from canonical sealed study")
        fee012_freeze.verify_static()
        return fee012_freeze.load_assignment()

    def validate(self):
        from scripts import fee012_freeze
        self.validate_static()
        fee012_freeze.verify()
        return fee012_freeze.load_assignment()


def _pricing_basis(snapshots: dict) -> dict:
    return {name: {key: value for key, value in item.items()
                   if key != "fetched_utc"} for name, item in snapshots.items()}


def _run_set(state: dict, frozen: dict, assignment_sha: str) -> None:
    prior = frozen["prior_ledger_run_ids"]
    own = {run_id(assignment_sha, episode)
           for episode in frozen["execution_order"]}
    if (prior != sorted(set(prior))
            or set(state["runs"]) - set(prior) - own
            or any(ident not in state["runs"] for ident in prior)
            or digest({ident: state["runs"][ident] for ident in prior})
               != frozen["prior_ledger_runs_sha256"]):
        raise RemoteBoundaryError("FEE012 predecessor or concurrent ledger run differs")


def _ledger(state: dict, frozen: dict, assignment_sha: str, *,
            active_run_id: str | None = None,
            active_reservation_usd: Decimal = Decimal(0)) -> None:
    if (state["cap_usd"] != "50" or state["blocked"]
            or state["unknown_run_ids"]):
        raise RemoteBoundaryError("FEE012 USD50 shared ledger blocked")
    exact_prior_holds(state, active_run_id=active_run_id,
                      active_reservation_usd=active_reservation_usd)
    _run_set(state, frozen, assignment_sha)


def fresh_budget(frozen: dict, assignment_sha: str,
                 remaining: tuple[Fee012Row, ...]) -> tuple[dict, Decimal, dict]:
    state = BudgetLedger(CANONICAL_LEDGER).snapshot()
    _ledger(state, frozen, assignment_sha)
    prices = pricing_snapshots()
    if _pricing_basis(prices) != _pricing_basis(frozen["public_pricing_snapshot"]):
        raise RemoteBoundaryError("FEE012 public model catalog changed after freeze")
    reserve = max(Decimal(frozen["budget_gate"]["per_row_worst_case_usd"]),
                  per_row_reserve(prices))
    if (len(remaining) * reserve + CONTINGENCY_USD + UNASSIGNED_RESIDUAL_USD
            > Decimal(state["available_usd"])):
        raise RemoteBoundaryError("FEE012 full remaining block exceeds USD50 headroom")
    return prices, reserve, state


def preflight(plan: Fee012Plan = Fee012Plan()) -> dict:
    from scripts.fee012_collect import verify_episode
    frozen, assignment_sha, rows = plan.validate()
    state = BudgetLedger(plan.ledger_path).snapshot()
    _ledger(state, frozen, assignment_sha)
    next_index = None
    for index, row in enumerate(rows):
        directory = plan.runs_dir / "episodes" / row.episode_id
        if (directory / "STOPPED.json").is_file():
            raise RemoteBoundaryError("earlier FEE012 row stopped; no retry or later call")
        if (directory / "episode_record.json").is_file():
            if next_index is not None:
                raise RemoteBoundaryError("FEE012 completed row after execution gap")
            verify_episode(row, directory, assignment_sha=assignment_sha, ledger=state)
        elif directory.exists():
            raise RemoteBoundaryError("partial FEE012 row exists; no retry")
        elif next_index is None:
            next_index = index
    if next_index is None:
        raise RemoteBoundaryError("all six assigned FEE012 rows already attempted")
    row = rows[next_index]
    ident = run_id(assignment_sha, row.episode_id)
    if ident in state["runs"]:
        raise RemoteBoundaryError("assigned FEE012 ledger run ID already used")
    _, reserve, state = fresh_budget(frozen, assignment_sha, rows[next_index:])
    return {"status": "PREFLIGHT_PASS_NO_PAID_CALL",
            "assignment_manifest_sha256": assignment_sha,
            "next_index": next_index, "next_episode_id": row.episode_id,
            "next_run_id": ident, "per_row_reserve_usd": str(reserve),
            "full_remaining_headroom_usd": str(
                len(rows[next_index:]) * reserve + CONTINGENCY_USD + UNASSIGNED_RESIDUAL_USD),
            "ledger_available_usd": state["available_usd"],
            "ledger_seq": state["seq"],
            "role_models": {"provider": row.provider_model_id,
                            "auditor": row.auditor_model_id},
            "reasoning_effort_by_role": {"provider": "high", "auditor": "high"}}


def _usage_estimate(log: Any, prices: dict, observed: list[dict]) -> Decimal:
    usage = log.samples[0].model_usage
    counts = Counter(item["model"].removeprefix("openrouter/") for item in observed)
    if set(usage) != {"openrouter/" + name for name in counts}:
        raise RemoteBoundaryError("FEE012 usage routes differ from forwarded requests")
    return sum((estimate_model_usage(prices[name], usage["openrouter/" + name], count)
                for name, count in counts.items()), Decimal(0))


def execute_one(plan: Fee012Plan = Fee012Plan()) -> dict:
    preview = preflight(plan)
    _enabled()
    from scripts.fee012_collect import verify_episode
    frozen, assignment_sha, rows = plan.validate()
    row = rows[preview["next_index"]]
    ident = run_id(assignment_sha, row.episode_id)
    prices, reserve, _ = fresh_budget(frozen, assignment_sha,
                                       rows[preview["next_index"]:])
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
        _ledger(state, frozen, assignment_sha, active_run_id=ident,
                active_reservation_usd=reserve)
        if (required_headroom(prices, ROWS - preview["next_index"] - 1)
                > Decimal(state["available_usd"])):
            raise RemoteBoundaryError("FEE012 post-reserve block headroom changed")
        with FeeNativeController(row, directory / "erc8183") as native:
            prefix = native.public_prefix()
            task = fee012_invoice_orbit(row, native_prefix=prefix,
                native_check=native.buy_check, native_settle=native.settle,
                model_behavior_tier="REAL_LLM_REMOTE_APPROVED")
            before = account_usage_usd()
            role_models = models(row)
            observed = guard_model_apis(role_models, row, prefix)
            logs = inspect_eval(task, model=role_models["provider"],
                sample_id=row.episode_id, max_samples=1, max_tasks=1,
                epochs=1, retry_on_error=0, fail_on_error=True,
                time_limit=1860, token_limit=650_000,
                message_limit=96, turn_limit=PROVIDER_CALLS + AUDITOR_CALLS,
                log_dir=str(directory / "inspect_work"), log_format="eval",
                log_model_api=False, display="none", log_level="error")
            if len(logs) != 1 or not logs[0].location:
                raise RemoteBoundaryError("one saved FEE012 Inspect log required")
            raw = Path(logs[0].location)
            assert_no_key(raw)
            target = directory / "inspect.eval"
            shutil.copyfile(raw, target)
            os.chmod(target, 0o600)
            if file_sha(raw) != file_sha(target):
                raise RemoteBoundaryError("FEE012 Inspect archive copy changed")
            saved = read_eval_log(str(target), resolve_attachments=True)
            boundary = verify_boundary(saved, observed, row, prefix)
            estimate = _usage_estimate(saved, prices, observed)
            after = account_usage_usd()
            delta = account_usage_delta_usd(before, after)
            cost = max(estimate, delta)
            if cost > reserve:
                raise RemoteBoundaryError("FEE012 model cost exceeds reserved cap")
            terminal = boundary["terminal_verdict_issued"]
            if terminal is not (native.verdict is not None):
                raise RemoteBoundaryError("FEE012 model terminal/native job mismatch")
        native_name = "native-evidence.json" if terminal else "native-partial.json"
        native_path = directory / "erc8183" / native_name
        native_result = verify_native_file(native_path, row)
        if native_result["status"] != (
                "COMPLETE_VERIFIED" if terminal else "FUNDED_SUBMITTED_VERIFIED"):
            raise RemoteBoundaryError("FEE012 native receipt replay differs from terminal state")
        ledger.settle(ident, cost, "sha256:" + file_sha(target))
        settled = True
        latest = ledger.snapshot()
        _ledger(latest, frozen, assignment_sha)
        if (required_headroom(prices, ROWS - preview["next_index"] - 1)
                > Decimal(latest["available_usd"])):
            raise RemoteBoundaryError("FEE012 post-settlement block headroom changed")
        plan.validate_static()
        record = {"schema": "fee012-paid-episode-v1",
                  "status": "COMPLETE" if terminal else "OBSERVED_INCOMPLETE",
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
                  "model_request_boundary": observed,
                  "raw_model_boundary": boundary,
                  "inspect_sha256": file_sha(target),
                  "native_path": str(native_path.relative_to(directory)),
                  "native_sha256": file_sha(native_path),
                  "native_status": native_result["status"],
                  "usage_estimate_usd": str(estimate),
                  "account_usage_before_usd": str(before),
                  "account_usage_after_usd": str(after),
                  "account_usage_delta_usd": str(delta),
                  "fresh_public_pricing_snapshots": prices}
        write_json(directory / "episode_record.json", record)
        return verify_episode(row, directory, assignment_sha=assignment_sha,
                              ledger=ledger.snapshot())
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
        try:
            observed_ledger_status = ledger.snapshot().get("runs", {}).get(
                ident, {}).get("status")
        except Exception:
            observed_ledger_status = "UNREADABLE"
        partial = _partial_artifacts(directory)
        model_events = _stopped_model_events(directory, observed)
        account_usage = _stopped_account_usage(before)
        write_json(directory / "STOPPED.json", {
            "schema": "fee012-stopped-episode-v1",
            "episode_id": row.episode_id,
            "assignment_manifest_sha256": assignment_sha,
            "error_type": type(exc).__name__,
            "ledger_run_id": ident,
            "budget_state": "SETTLED" if settled else
                "UNKNOWN" if unknown else "UNRESOLVED" if reserved else "UNRESERVED",
            "ledger_status_at_stop": observed_ledger_status,
            "model_request_boundary": observed,
            "stopped_model_events": model_events,
            "stopped_account_usage": account_usage,
            "partial_artifacts": partial,
            "no_retry_or_substitution": True,
            "complete_native_claim": False,
            "prior_native_terminal_possible": True})
        raise
