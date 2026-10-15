"""One assigned cross-vendor ORBIT pair with bounded OpenRouter calls and native MPP."""
from __future__ import annotations

import asyncio
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
from inspect_ai.model import GenerateConfig, get_model

from .mpp005_remote import _execution_enabled, _verify_partial_native
from .mpp008_boundary import (REQUEST_TIMEOUT_SECONDS, RemoteBoundaryError,
    account_usage_delta_usd, account_usage_usd, assert_no_key, file_sha,
    guard_model_apis, inspect_mixed_native_log, verify_raw_model_boundary, write_json)
from .mpp008_plan import (AUDITOR_CALLS, CANONICAL_LEDGER_PATH, CONTINGENCY_USD,
    EVAL_TOKEN_LIMIT, MAX_CALLS_PER_EPISODE, MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS,
    MODELS, PROVIDER_CALLS, SCHEDULER_SECONDS)
from .mpp008_pricing import estimate_model_usage, pricing_snapshots, reserve_pair
from .mpp008_task import native_mixed_model_task
from .remote_budget import BudgetLedger


ROOT = Path(__file__).resolve().parents[2]
ASSIGNMENT = ROOT / "artifacts/gates/MPP008/assignment-mixed-001"
RUNS = ROOT / "artifacts/gates/MPP008/runs-mixed-001"


def run_id(assignment_sha: str, episode_id: str) -> str:
    return f"mpp008-{assignment_sha[:12]}-{episode_id}"


@dataclass(frozen=True)
class Mpp008Plan:
    assignment_dir: Path = ASSIGNMENT
    runs_dir: Path = RUNS
    ledger_path: Path = CANONICAL_LEDGER_PATH

    def validate(self):
        from scripts import freeze_mpp008
        if (self.assignment_dir.resolve() != ASSIGNMENT.resolve()
                or self.runs_dir.resolve() != RUNS.resolve()
                or self.ledger_path.resolve() != CANONICAL_LEDGER_PATH.resolve()):
            raise RemoteBoundaryError("MPP008 path differs from canonical assignment or shared ledger")
        freeze_mpp008.verify()
        return freeze_mpp008.load_assignment()


def fresh_budget(plan: Mpp008Plan, frozen: dict, remaining: list[Any]):
    from scripts import freeze_mpp008
    freeze_mpp008.verify()
    state = BudgetLedger(plan.ledger_path).snapshot()
    if (state["blocked"] or state["unknown_run_ids"] or state["cap_usd"] != "50"
            or Decimal(state["reserved_usd"]) != 0):
        raise RemoteBoundaryError("shared lifetime ledger blocked or concurrent reservation")
    prices = pricing_snapshots()
    if {name: value["catalog_model_sha256"] for name, value in prices.items()} != {
            name: value["catalog_model_sha256"] for name, value in frozen["public_pricing_snapshots"].items()}:
        raise RemoteBoundaryError("MPP008 published model route/catalog changed since freeze")
    reserves = {row.episode_id: max(Decimal(frozen["worst_case_reserve_usd_by_episode"][row.episode_id]),
                                    reserve_pair(prices, row.provider_model_id, row.auditor_model_id))
                for row in remaining}
    if sum(reserves.values(), Decimal(0)) + Decimal(CONTINGENCY_USD) > Decimal(state["available_usd"]):
        raise RemoteBoundaryError("remaining mixed-model block plus contingency exceeds USD50 headroom")
    return prices, reserves, state


def preflight(plan: Mpp008Plan = Mpp008Plan()) -> dict:
    from .mpp008_reporting import verify_episode
    frozen, assignment_sha, rows = plan.validate()
    by_id = {row.episode_id: row for row in rows}
    if len(by_id) != 8 or set(by_id) != set(frozen["execution_order"]):
        raise RemoteBoundaryError("frozen MPP008 denominator differs")
    ledger = BudgetLedger(plan.ledger_path).snapshot()
    next_index = None
    for index, episode_id in enumerate(frozen["execution_order"]):
        row = by_id[episode_id]
        directory = plan.runs_dir / "episodes" / episode_id
        if (directory / "STOPPED.json").exists():
            raise RemoteBoundaryError("earlier MPP008 row stopped; no reroll or later paid calls")
        if (directory / "episode_record.json").is_file():
            if next_index is not None:
                raise RemoteBoundaryError("completed MPP008 row after a gap")
            verified = verify_episode(row, directory, assignment_sha=assignment_sha, ledger=ledger)
            if index == 0 and verified["status"] not in {"COMPLETE", "OBSERVED_INCOMPLETE"}:
                raise RemoteBoundaryError("predeclared Sol strict-schema compatibility gate failed; stop remaining block")
        elif directory.exists():
            raise RemoteBoundaryError("partial assigned MPP008 episode exists; no retry")
        elif next_index is None:
            next_index = index
    if next_index is None:
        raise RemoteBoundaryError("all assigned MPP008 episodes already attempted")
    remaining = [by_id[e] for e in frozen["execution_order"][next_index:]]
    row = remaining[0]
    if run_id(assignment_sha, row.episode_id) in ledger["runs"]:
        raise RemoteBoundaryError("assigned MPP008 ledger run ID already exists")
    prices, reserves, state = fresh_budget(plan, frozen, remaining)
    return {"mode": "dry-run", "ready_to_execute": True,
            "next_episode_id": row.episode_id, "next_index": next_index,
            "next_provider_model_id": row.provider_model_id,
            "next_auditor_model_id": row.auditor_model_id,
            "first_row_compatibility_gate": next_index == 0,
            "assignment_manifest_sha256": assignment_sha,
            "next_reservation_usd": str(reserves[row.episode_id]),
            "full_remaining_reservation_usd": str(sum(reserves.values(), Decimal(0))),
            "contingency_usd": CONTINGENCY_USD, "available_usd": state["available_usd"],
            "fresh_public_pricing": prices, "reasoning_effort_by_role": {
                "provider": "high", "auditor": "high"},
            "max_calls_by_role": {"provider": PROVIDER_CALLS, "auditor": AUDITOR_CALLS},
            "max_input_bytes": MAX_INPUT_BYTES, "max_output_tokens": MAX_OUTPUT_TOKENS,
            "max_retries": 0}


def _usage_estimate(log: Any, prices: dict, observed: list[dict]) -> Decimal:
    if len(log.samples or []) != 1:
        raise RemoteBoundaryError("one Inspect sample required for usage")
    usage = log.samples[0].model_usage
    counts = Counter(item["model"].removeprefix("openrouter/") for item in observed)
    if not counts or not set(counts).issubset(MODELS) or set(usage) != {
            "openrouter/" + mid for mid in counts}:
        raise RemoteBoundaryError("saved provider usage keys differ from actual calls")
    return sum((estimate_model_usage(prices[mid], usage["openrouter/" + mid], calls)
                for mid, calls in counts.items()), Decimal(0))


def _configured_models(row):
    config = GenerateConfig(reasoning_effort="high", reasoning_history="none",
        max_tokens=MAX_OUTPUT_TOKENS, max_retries=0, timeout=REQUEST_TIMEOUT_SECONDS,
        max_connections=1, cache=False)
    models = {}
    for role, mid in (("provider", row.provider_model_id), ("auditor", row.auditor_model_id)):
        model = get_model("openrouter/" + mid)
        if type(model.api).__name__ != "OpenRouterAPI" or str(model) != "openrouter/" + mid:
            raise RemoteBoundaryError("explicit ORBIT model route is not native OpenRouter")
        # The OpenAI SDK retries below ModelAPI.generate. A GenerateConfig cap
        # alone does not govern that client; freeze the actual forwarding path.
        model.api.client.max_retries = 0
        if model.api.client.max_retries != 0:
            raise RemoteBoundaryError("OpenRouter HTTP client retains implicit retries")
        model.config = config.model_copy(deep=True)
        if get_model("openrouter/" + mid) is not model:
            raise RemoteBoundaryError("ORBIT explicit model lookup is not the bounded instance")
        models[role] = model
    return models


def execute_one(plan: Mpp008Plan = Mpp008Plan()) -> dict:
    """Execute exactly one frozen row. Any ambiguous payment stops the block."""
    preview = preflight(plan)
    _execution_enabled()
    from .mpp008_native_service import NativeMeetingService
    frozen, assignment_sha, rows = plan.validate()
    row = next(row for row in rows if row.episode_id == preview["next_episode_id"])
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
        task = native_mixed_model_task(row, service=service)
        before = account_usage_usd()
        models = _configured_models(row)
        observed = guard_model_apis(models, row)
        remaining = [next(r for r in rows if r.episode_id == e)
                     for e in frozen["execution_order"][preview["next_index"]:]]
        prices, reserves, _ = fresh_budget(plan, frozen, remaining)
        reserve = reserves[row.episode_id]
        snapshot = ledger.reserve(ident, reserve, Decimal("50"),
            metadata={"provider_model_id": row.provider_model_id,
                      "auditor_model_id": row.auditor_model_id,
                      "episode_id": row.episode_id, "assignment_sha": assignment_sha})
        reserved = True
        if Decimal(snapshot["available_usd"]) < (
                sum((reserves[r.episode_id] for r in remaining[1:]), Decimal(0))
                + Decimal(CONTINGENCY_USD)):
            raise RemoteBoundaryError("concurrent spending consumed remaining block reserve")
        logs = inspect_eval(task, model=models["provider"], sample_id=row.trial_id,
            max_samples=1, max_tasks=1, epochs=1, retry_on_error=0, fail_on_error=True,
            time_limit=SCHEDULER_SECONDS, token_limit=EVAL_TOKEN_LIMIT,
            message_limit=80, turn_limit=MAX_CALLS_PER_EPISODE,
            log_dir=str(directory / "inspect_work"), log_format="eval",
            log_model_api=False, display="none", log_level="error")
        if len(logs) != 1 or not logs[0].location:
            raise RemoteBoundaryError("one saved mixed-model Inspect log required")
        raw = Path(logs[0].location)
        assert_no_key(raw)
        target = directory / "inspect.eval"
        shutil.copyfile(raw, target)
        os.chmod(target, 0o600)
        if file_sha(raw) != file_sha(target):
            raise RemoteBoundaryError("raw Inspect archive copy differs")
        saved = read_eval_log(str(target), resolve_attachments=True)
        estimated = _usage_estimate(saved, prices, observed)
        after = account_usage_usd()
        delta = account_usage_delta_usd(before, after)
        cost = max(estimated, delta)
        if cost > reserve:
            raise RemoteBoundaryError("observed mixed-model charge exceeds reservation")
        ledger.settle(ident, cost, "sha256:" + file_sha(target))
        settled = True
        boundary = verify_raw_model_boundary(saved, observed, row)
        if saved.samples[0].store.get("OpenMppStore:decision") is None:
            partial = _verify_partial_native(saved, service, quality=row.truth)
            decision = None
            provenance = None
            status = "OBSERVED_INCOMPLETE"
        else:
            decision, provenance = inspect_mixed_native_log(saved, service=service,
                row=row, observed=observed)
            write_json(directory / "decision.json", decision)
            compensation = directory / "native/compensation-evidence.json"
            asyncio.run(service._command(ROOT / "protocols/mpp/mpp008-decision-preflight.mjs",
                directory / "decision.json", decision["selected_flow"]))
            asyncio.run(service._command(ROOT / "protocols/mpp/meeting-local.mjs",
                directory / "decision.json", decision["selected_flow"], compensation))
            asyncio.run(service._command(ROOT / "protocols/mpp/verify-meeting-evidence.mjs", compensation))
            partial = []
            status = "COMPLETE"
        plan.validate()
        record = {"schema": "mpp008-paid-episode-v1", "status": status,
            "episode_id": row.episode_id, "assignment_manifest_sha256": assignment_sha,
            "provider_model_id": row.provider_model_id, "auditor_model_id": row.auditor_model_id,
            "reasoning_effort_by_role": {"provider": "high", "auditor": "high"},
            "reasoning_history": "none", "model_execution_tier": "REAL_LLM_REMOTE_APPROVED",
            "http_client_max_retries_by_role": {"provider": 0, "auditor": 0},
            "transaction_tier": "NATIVE_LOCAL_PROTOCOL", "model_request_boundary": observed,
            "raw_model_boundary": boundary, "normalized_replay_provenance": provenance,
            "ledger_run_id": ident, "model_cost_usd": str(cost),
            "inspect_sha256": file_sha(target), "usage_estimate_usd": str(estimated),
            "account_usage_before_usd": str(before), "account_usage_after_usd": str(after),
            "account_usage_delta_usd": str(delta), "fresh_public_pricing_snapshots": prices,
            "prepare_sha256": file_sha(directory / "native/prepare-evidence.json"),
            "decision_sha256": decision["decision_sha256"] if decision else None,
            "compensation_sha256": file_sha(compensation) if decision else None,
            "partial_native_operations": partial}
        write_json(directory / "episode_record.json", record)
        from .mpp008_reporting import verify_episode
        return verify_episode(row, directory, assignment_sha=assignment_sha, ledger=ledger.snapshot())
    except BaseException as exc:
        unknown = False
        secondary = []
        if reserved and not settled:
            try:
                ledger.mark_unknown(ident, type(exc).__name__)
                unknown = True
            except Exception as error:
                secondary.append("billing:" + type(error).__name__)
        partial_files = []
        removed = []
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
            "schema": "mpp008-stopped-episode-v1", "episode_id": row.episode_id,
            "assignment_manifest_sha256": assignment_sha,
            "error_type": type(exc).__name__,
            "budget_state": "SETTLED" if settled else "UNKNOWN" if unknown else
                            "UNRESOLVED" if reserved else "UNRESERVED",
            "ledger_run_id": ident, "model_calls_attempted": len(observed),
            "model_request_boundary": observed, "partial_artifacts": partial_files,
            "removed_secret_artifacts": removed, "no_retry_or_substitution": True,
            "complete_payment_claim": False, "secondary_failure_types": secondary})
        raise
