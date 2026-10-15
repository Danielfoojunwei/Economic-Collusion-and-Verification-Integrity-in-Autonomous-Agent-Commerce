"""One supervised, prospectively frozen live funded-offer pilot episode.

All inference routes through the shared USD 20 OpenRouter ledger. The native
chain is disposable and valueless. A saved episode is evidence only after the
separate read-only collector reopens Inspect and raw native receipts.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
from typing import Any

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log
from inspect_ai.model import ContentReasoning, GenerateConfig, get_model

from .mechanism_native import MechanismNative, verify_mechanism_native_evidence
from .mechanism_plan import (
    MAX_CALLS_PER_EPISODE, MAX_OUTPUT_TOKENS_PER_CALL,
    MAX_SERIALIZED_INPUT_BYTES_PER_CALL, MechanismEpisode, case_for_episode,
)
from .mechanism_reporting import load_assignment, verify_episode
from .mechanism_task import (
    BONUS_CONDITION, BONUS_CURRENCY, audit_saved_mechanism_log,
    build_mechanism_task,
)
from .remote import (
    APPROVED_MODEL_ID, PROJECT_CAP_USD, PROJECT_LEDGER_PATH,
    REQUEST_TIMEOUT_SECONDS, RemoteBoundaryError, _execution_enabled, _sha256,
    _safe_model_input_size, _usage_for, account_usage_delta_usd,
    account_usage_usd, guard_model_api,
)
from .remote_budget import BudgetLedger
from .remote_pricing import estimate_usage, pricing_snapshot, reserve_worst_case
from .w10_factorial_remote import _scan_native_log_for_secret, guard_high_reasoning
from .w11_market_log_integrity import compare_market_native_log


ROOT = Path(__file__).resolve().parents[2]
PILOT_ROOT = ROOT / "artifacts" / "gates" / "MECHANISM_PILOT"
ASSIGNMENT_DIR = PILOT_ROOT / "assignment-002"
RUNS_DIR = PILOT_ROOT / "runs-002"
SCHEDULER_SECONDS = 240
REASONING_HISTORY = "none"


def _freeze_verify() -> None:
    from scripts.freeze_mechanism_pilot import verify

    verify()


def _run_id(assignment_sha: str, episode_id: str) -> str:
    return f"mechanism-{assignment_sha[:12]}-{episode_id}"


def _episode_dir(runs_dir: Path, row: MechanismEpisode) -> Path:
    return Path(runs_dir) / "episodes" / row.episode_id


def _fresh_budget_boundary(
    plan: MechanismPilotPlan, frozen: dict[str, Any], assignment_sha: str,
    row: MechanismEpisode, next_index: int,
) -> tuple[dict[str, Any], Decimal, dict[str, Any]]:
    """Recheck current price and all remaining headroom before reservation."""
    _freeze_verify()
    now_frozen, now_sha, now_rows = load_assignment(plan.assignment_dir)
    if (now_sha != assignment_sha or now_frozen != frozen
            or row != next(item for item in now_rows if item.episode_id == row.episode_id)):
        raise RemoteBoundaryError("assigned pilot row or source changed before reservation")
    snapshot = BudgetLedger(plan.ledger_path).snapshot()
    if (snapshot["blocked"] or snapshot["cap_usd"] != "20"
            or snapshot["unknown_run_ids"]
            or _run_id(assignment_sha, row.episode_id) in snapshot["runs"]):
        raise RemoteBoundaryError("canonical budget state changed before reservation")
    rates = pricing_snapshot(plan.model_id)
    current = reserve_worst_case(
        rates, plan.max_calls, plan.max_input_bytes, plan.max_output_tokens)
    reserve = max(current, Decimal(frozen["worst_case_reserve_usd_per_episode"]))
    if reserve * Decimal(len(now_rows) - next_index) > Decimal(snapshot["available_usd"]):
        raise RemoteBoundaryError("full remaining pilot worst-case reserve exceeds USD headroom")
    return rates, reserve, snapshot


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_bytes(json.dumps(data, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False, allow_nan=False).encode() + b"\n")
    os.chmod(path, 0o600)


@dataclass(frozen=True)
class MechanismPilotPlan:
    assignment_dir: Path = ASSIGNMENT_DIR
    runs_dir: Path = RUNS_DIR
    ledger_path: Path = PROJECT_LEDGER_PATH
    model_id: str = APPROVED_MODEL_ID
    cap_usd: Decimal = PROJECT_CAP_USD
    max_calls: int = MAX_CALLS_PER_EPISODE
    max_input_bytes: int = MAX_SERIALIZED_INPUT_BYTES_PER_CALL
    max_output_tokens: int = MAX_OUTPUT_TOKENS_PER_CALL
    reasoning_history: str = REASONING_HISTORY

    def validate(self) -> tuple[dict[str, Any], str, tuple[MechanismEpisode, ...]]:
        if (self.assignment_dir.resolve() != ASSIGNMENT_DIR.resolve()
                or self.runs_dir.resolve() != RUNS_DIR.resolve()
                or self.ledger_path.resolve() != PROJECT_LEDGER_PATH.resolve()):
            raise RemoteBoundaryError("pilot must use canonical frozen assignment, runs and ledger")
        if self.model_id != APPROVED_MODEL_ID or self.cap_usd != PROJECT_CAP_USD:
            raise RemoteBoundaryError("pilot model or USD 20 cap differs from approval")
        if (self.max_calls != MAX_CALLS_PER_EPISODE
                or self.max_input_bytes != MAX_SERIALIZED_INPUT_BYTES_PER_CALL
                or self.max_output_tokens != MAX_OUTPUT_TOKENS_PER_CALL
                or self.reasoning_history != REASONING_HISTORY):
            raise RemoteBoundaryError("pilot model limits differ from prospective freeze")
        _freeze_verify()
        frozen, assignment_sha, rows = load_assignment(self.assignment_dir)
        if (frozen.get("reasoning_effort") != "high"
                or frozen.get("reasoning_history") != REASONING_HISTORY):
            raise RemoteBoundaryError("frozen reasoning configuration differs from follow-up")
        return frozen, assignment_sha, rows


def preflight(plan: MechanismPilotPlan) -> dict[str, Any]:
    """Reopen frozen order, prior episodes, current rates and full remaining cap."""
    frozen, assignment_sha, rows = plan.validate()
    ledger = BudgetLedger(plan.ledger_path).snapshot()
    if ledger["blocked"] or ledger["cap_usd"] != "20" or ledger["unknown_run_ids"]:
        raise RemoteBoundaryError("shared USD 20 project ledger is blocked")
    ordered = {row.episode_id: row for row in rows}
    if set(ordered) != set(frozen["execution_order"]):
        raise RemoteBoundaryError("frozen execution order is incomplete")
    next_index = None
    for index, episode_id in enumerate(frozen["execution_order"]):
        row = ordered[episode_id]
        directory = _episode_dir(plan.runs_dir, row)
        if (directory / "STOPPED.json").exists():
            raise RemoteBoundaryError("earlier assigned episode stopped; no rerun or later calls")
        if (directory / "episode_record.json").exists():
            if next_index is not None:
                raise RemoteBoundaryError("later episode exists after a gap in frozen order")
            prior = verify_episode(
                row, directory, assignment_sha=assignment_sha,
                frozen=frozen, ledger=ledger,
            )
            if prior["auditor_read"] is not True or prior["single_post_adherence"] is not True:
                raise RemoteBoundaryError("prior exact-read or single-post exposure failed; later calls stopped")
        elif next_index is None:
            if directory.exists():
                raise RemoteBoundaryError("assigned episode directory exists without complete record")
            next_index = index
        elif directory.exists():
            raise RemoteBoundaryError("later assigned episode directory exists after pending row")
    if next_index is None:
        raise RemoteBoundaryError("all four assigned pilot episodes have run")
    row = ordered[frozen["execution_order"][next_index]]
    if _run_id(assignment_sha, row.episode_id) in ledger["runs"]:
        raise RemoteBoundaryError("assigned ledger run ID already exists")
    fresh_rates, reserve, checked_ledger = _fresh_budget_boundary(
        plan, frozen, assignment_sha, row, next_index)
    remaining = len(rows) - next_index
    full_remaining = reserve * Decimal(remaining)
    case_for_episode(row)
    return {
        "mode": "dry-run", "ready_to_execute": True,
        "assignment_manifest_sha256": assignment_sha,
        "next_episode_id": row.episode_id, "next_arm": row.arm,
        "next_index": next_index, "remaining_episodes": remaining,
        "model_id": plan.model_id, "reasoning_effort": "high",
        "reasoning_history": plan.reasoning_history,
        "max_calls": plan.max_calls,
        "max_serialized_input_bytes": plan.max_input_bytes,
        "max_output_tokens_per_call": plan.max_output_tokens,
        "next_reservation_usd": format(reserve, "f"),
        "full_remaining_reservation_usd": format(full_remaining, "f"),
        "shared_ledger_available_usd": checked_ledger["available_usd"],
        "shared_ledger_last_hash": checked_ledger["last_hash"],
        "source_inventory_sha256": sha256(json.dumps(
            frozen["source_sha256"], sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest(),
        "fresh_pricing": fresh_rates,
    }


def _archive_inspect(directory: Path, location: str | Path) -> Path:
    source = Path(location)
    target = directory / "inspect.eval"
    if not source.is_file() or target.exists():
        raise RemoteBoundaryError("native Inspect archive missing or duplicate")
    shutil.copyfile(source, target)
    os.chmod(target, 0o600)
    if _sha256(source) != _sha256(target):
        raise RemoteBoundaryError("native Inspect archive copy changed")
    return target


def _preserve_partial_inspect(directory: Path) -> list[dict[str, str]]:
    """Keep Inspect's durable work logs even if eval raised after billed calls."""
    candidates = sorted((directory / "inspect_work").rglob("*.eval")) \
        if (directory / "inspect_work").exists() else []
    result = []
    for candidate in candidates:
        result.append({"path": str(candidate.relative_to(directory)),
                       "sha256": _sha256(candidate)})
    if not (directory / "inspect.eval").exists() and len(candidates) == 1:
        _archive_inspect(directory, candidates[0])
    return result


def _require_auditor_native_bonus_proof(audit: dict[str, Any],
                                        native: MechanismNative) -> None:
    """Bind trusted auditor view/input to a funded local receipt before verdict."""
    obligation = native.obligation
    if obligation is None or audit.get("trusted_bonus_proof_seen_before_verdict") is not True:
        raise RemoteBoundaryError("trusted bonus proof did not reach auditor before verdict")
    proof = audit.get("auditor_verified_bonus")
    expected = {
        "chain_id": obligation.chain_id,
        "core_address": obligation.core_address,
        "job_id": obligation.job_id,
        "provider_address": obligation.provider_address,
        "auditor_address": obligation.auditor_address,
        "token_address": obligation.token_address,
        "condition": BONUS_CONDITION,
        "currency": BONUS_CURRENCY,
    }
    if native.bonus is None:
        expected.update({
            "status": "NONE", "execution_tier": None,
            "proposal_id": None, "amount_minor": None,
            "escrow_address": None, "funding_tx_hash": None,
            "receipt_sha256": None,
        })
    else:
        if native.bonus["status"] != "FUNDED":
            raise RemoteBoundaryError("bonus was not verified funded before auditor verdict")
        expected.update({
            "status": "VERIFIED_NATIVE_LOCAL",
            "execution_tier": "NATIVE_LOCAL_PROTOCOL",
            "proposal_id": native.bonus["proposal_id"],
            "amount_minor": native.bonus["amount_minor"],
            "escrow_address": native.bonus["escrow_address"],
            "funding_tx_hash": native.bonus["funding_tx_hash"],
            "receipt_sha256": native.bonus["funding_receipt_sha256"],
        })
    if proof != expected or audit.get("trusted_bonus_status") != expected["status"]:
        raise RemoteBoundaryError("auditor trusted bonus proof differs from funded native receipt")


def _has_reasoning_block(messages: Any) -> bool:
    """Inspect must strip prior opaque reasoning before its API boundary."""
    return any(
        isinstance(part, ContentReasoning)
        for message in messages
        for part in (message.content if isinstance(message.content, list) else ())
    )


def _capture_model_boundary(model: Any, plan: MechanismPilotPlan) -> list[dict[str, Any]]:
    """Enforce the v2 history policy at the actual forwarded API input."""
    observed: list[dict[str, Any]] = []
    original = model.api.generate

    async def bounded_generate(input: Any, tools: Any, tool_choice: Any,
                               config: GenerateConfig) -> Any:
        size = _safe_model_input_size(input, tools)
        record = {
            "call_index": len(observed) + 1,
            "serialized_input_bytes": size,
            "local_boundary_passed": False,
        }
        observed.append(record)
        if (config.reasoning_effort != "high"
                or config.reasoning_history != REASONING_HISTORY):
            raise RemoteBoundaryError("provider call differs from frozen reasoning policy")
        if _has_reasoning_block(input):
            raise RemoteBoundaryError("prior reasoning block reached provider API boundary")
        if size > plan.max_input_bytes or len(observed) > plan.max_calls:
            raise RemoteBoundaryError("provider request exceeds frozen call or byte cap")
        if (config.max_tokens != plan.max_output_tokens
                or config.max_retries != 0):
            raise RemoteBoundaryError("provider call differs from frozen output or retry limit")
        record["local_boundary_passed"] = True
        return await original(input, tools, tool_choice, config)

    model.api.generate = bounded_generate
    return observed


def _verify_saved_model_boundary(
    log: Any, plan: MechanismPilotPlan, attempts: dict[str, int],
    observed: list[dict[str, Any]],
) -> dict[str, Any]:
    """Match every archived model event to an actual bounded API invocation."""
    head_config = log.eval.model_generate_config
    if (log.eval.model != f"openrouter/{plan.model_id}"
            or head_config is None
            or head_config.reasoning_effort != "high"
            or head_config.reasoning_history != REASONING_HISTORY
            or head_config.max_tokens != plan.max_output_tokens
            or head_config.max_retries != 0
            or len(log.samples) != 1):
        raise RemoteBoundaryError("saved model route or sample count differs from approval")
    events = [event for event in log.samples[0].events if event.event == "model"]
    if (not events or len(events) != attempts["attempted"]
            or len(events) != len(observed) or len(events) > plan.max_calls
            or any(record.get("local_boundary_passed") is not True
                   for record in observed)):
        raise RemoteBoundaryError("saved model events differ from bounded API calls")
    event_requests: list[dict[str, Any]] = []
    for call_index, (event, boundary) in enumerate(zip(events, observed), start=1):
        config = event.config
        size = _safe_model_input_size(event.input, event.tools)
        if (event.model != f"openrouter/{plan.model_id}"
                or config.reasoning_effort != "high"
                or config.reasoning_history != REASONING_HISTORY
                or config.max_tokens != plan.max_output_tokens
                or config.max_retries != 0
                or _has_reasoning_block(event.input)
                or event.error is not None or event.cache is not None
                or event.retries not in (None, 0)
                or size > plan.max_input_bytes
                or boundary["call_index"] != call_index
                or boundary["serialized_input_bytes"] != size):
            raise RemoteBoundaryError("saved model event differs from actual bounded request")
        event_requests.append({
            "call_index": call_index, "model_event_uuid": event.uuid,
            "serialized_input_bytes": size,
        })
    if attempts["max_input_bytes_seen"] != max(
            request["serialized_input_bytes"] for request in event_requests):
        raise RemoteBoundaryError("saved request maximum differs from API guard")
    return {
        "max_calls": plan.max_calls,
        "max_serialized_input_bytes_per_call": plan.max_input_bytes,
        "max_output_tokens_per_call": plan.max_output_tokens,
        "event_requests": event_requests,
    }


def execute_one(plan: MechanismPilotPlan) -> dict[str, Any]:
    """Spend at most one assigned episode; no loop, retry or seed substitution."""
    preview = preflight(plan)
    _execution_enabled()
    frozen, assignment_sha, rows = plan.validate()
    row = next(item for item in rows if item.episode_id == preview["next_episode_id"])
    directory = _episode_dir(plan.runs_dir, row)
    directory.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    directory.mkdir(mode=0o700, exist_ok=False)
    os.chmod(directory, 0o700)
    native_path = directory / "native_evidence.json"
    inspect_path = directory / "inspect.eval"
    ledger = BudgetLedger(plan.ledger_path)
    run_id = _run_id(assignment_sha, row.episode_id)
    attempts: dict[str, int] = {"attempted": 0, "max_input_bytes_seen": 0}
    observed_requests: list[dict[str, Any]] = []
    reserved = False
    settled = False
    stage = "native_setup"
    try:
        case, artifact = case_for_episode(row)
        with MechanismNative(row, directory / "native",
                             assignment_manifest_sha256=assignment_sha) as native:
            obligation = native.open_job()
            task = build_mechanism_task(
                case, artifact, episode_id=row.episode_id, arm=row.arm,
                obligation=obligation, funding_tier="NATIVE_LOCAL_PROTOCOL",
                submit_claim=native.submit_claim,
                fund_bonus=native.fund_bonus if row.arm == "DIRECT_OFFER_CAPABILITY" else None,
                budget_units=4, check_cost_units=1,
                scheduler_seconds=SCHEDULER_SECONDS,
            )
            stage = "model_boundary_setup"
            usage_before = account_usage_usd()
            config = GenerateConfig(
                reasoning_effort="high", reasoning_history=plan.reasoning_history,
                max_tokens=plan.max_output_tokens,
                max_retries=0, timeout=REQUEST_TIMEOUT_SECONDS,
                max_connections=1, cache=False,
            )
            model = get_model(
                f"openrouter/{plan.model_id}", config=config, memoize=False,
                base_url="https://openrouter.ai/api/v1", max_retries=0,
                stream=False, responses_api=False,
            )
            attempts = guard_model_api(
                model, max_calls=plan.max_calls,
                max_input_bytes=plan.max_input_bytes,
                max_output_tokens=plan.max_output_tokens,
            )
            guard_high_reasoning(model)
            observed_requests = _capture_model_boundary(model, plan)
            work = directory / "inspect_work"
            work.mkdir(mode=0o700)
            fresh_rates, current_reserve, _ = _fresh_budget_boundary(
                plan, frozen, assignment_sha, row, preview["next_index"])
            stage = "budget_reservation"
            reserved_snapshot = ledger.reserve(
                run_id, current_reserve, plan.cap_usd,
                metadata={"model_id": plan.model_id, "episode_id": row.episode_id,
                          "assignment_sha": assignment_sha},
            )
            reserved = True
            if (Decimal(reserved_snapshot["available_usd"])
                    < current_reserve * Decimal(preview["remaining_episodes"] - 1)):
                raise RemoteBoundaryError(
                    "concurrent ledger spending consumed full remaining pilot headroom")
            stage = "provider_request"
            logs = inspect_eval(
                task, model=model, sample_id=row.task_id,
                max_samples=1, max_tasks=1, epochs=1,
                retry_on_error=0, fail_on_error=True,
                time_limit=SCHEDULER_SECONDS, token_limit=20_000,
                message_limit=40, turn_limit=10,
                log_dir=str(work), log_format="eval", log_model_api=False,
                display="none", log_level="error",
            )
            if len(logs) != 1 or not logs[0].location:
                raise RemoteBoundaryError("one native Inspect log is required")
            source = Path(logs[0].location)
            _archive_inspect(directory, source)
            source_unresolved = read_eval_log(str(source), resolve_attachments=False)
            source_resolved = read_eval_log(str(source), resolve_attachments=True)
            saved = read_eval_log(str(inspect_path), resolve_attachments=True)
            _scan_native_log_for_secret(inspect_path, saved,
                                        os.environ["OPENROUTER_API_KEY"])
            archive_audit = compare_market_native_log(
                logs[0], source_unresolved, source_resolved, saved,
                source_path=source, saved_path=inspect_path,
            )
            usage = _usage_for(logs[0], plan.model_id)
            usage_after = account_usage_usd()
            account_delta = account_usage_delta_usd(usage_before, usage_after)
            cost = max(estimate_usage(fresh_rates, usage,
                                      calls=attempts["attempted"]), account_delta)
            if cost > current_reserve:
                raise RemoteBoundaryError("model usage exceeds prospectively reserved cap")
            ledger.settle(run_id, cost, "sha256:" + _sha256(inspect_path))
            settled = True
            stage = "saved_log_and_native_audit"
            request_boundary = _verify_saved_model_boundary(
                saved, plan, attempts, observed_requests)
            audit = audit_saved_mechanism_log(
                saved, case, artifact, episode_id=row.episode_id, arm=row.arm,
                require_delivery=False,
            )
            _require_auditor_native_bonus_proof(audit, native)
            score = saved.samples[0].scores["mechanism_score"].metadata
            verdict = score.get("V")
            if (verdict not in {"ACCEPT", "REJECT"}
                    or score.get("Y") != row.truth
                    or audit["verdict"] != verdict
                    or native.submission is None):
                raise RemoteBoundaryError("private score, model submission or saved verdict differs")
            _freeze_verify()
            native.verify_open_job()
            stage = "official_and_bonus_settlement"
            native.settle_job(verdict, row.artifact_digest)
            saved_native = native.save_evidence()
            shutil.copyfile(saved_native, native_path)
            os.chmod(native_path, 0o600)
            native_summary = verify_mechanism_native_evidence(native_path)
            if (native_summary["episode_id"] != row.episode_id
                    or native_summary["verdict"] != verdict
                    or native_summary["submission_artifact_digest"] != row.artifact_digest):
                raise RemoteBoundaryError("saved native payment differs from scheduled episode")
            record = {
                "status": "COMPLETE", "episode_id": row.episode_id,
                "pair_id": row.pair_id, "arm": row.arm, "truth_block": row.block_id,
                "assignment_manifest_sha256": assignment_sha,
                "source_sha256": frozen["source_sha256"],
                "model_tier": "REAL_LLM_REMOTE_APPROVED",
                "payment_tier": "NATIVE_LOCAL_PROTOCOL",
                "model_id": plan.model_id, "reasoning_effort": "high",
                "reasoning_history": plan.reasoning_history,
                "model_request_boundary": request_boundary,
                "native_inspect_sha256": _sha256(inspect_path),
                "native_payment_sha256": _sha256(native_path),
                "native_archive_integrity": archive_audit,
                "model_calls": attempts["attempted"],
                "max_input_bytes_seen": attempts["max_input_bytes_seen"],
                "model_cost_usd_provisional_estimate": format(cost, "f"),
                "account_usage_delta_usd": format(account_delta, "f"),
                "ledger_run_id": run_id,
                "ledger_last_hash": ledger.snapshot()["last_hash"],
                "auditor_read": audit["exact_message_reached_auditor_input"],
                "single_post_adherence": audit["single_post_adherence"],
                "read_once_before_verdict": audit["read_once_before_verdict"],
                "trusted_bonus_status": audit["trusted_bonus_status"],
                "trusted_bonus_proof_seen_before_verdict":
                    audit["trusted_bonus_proof_seen_before_verdict"],
                "verdict": verdict,
                "job_status": native_summary["job_status"],
                "bonus_status": native_summary["bonus_status"],
                "provider_payout_minor_units": native_summary["provider_payout_minor_units"],
                "bonus_amount_minor_units": native_summary["bonus_amount_minor_units"],
            }
        _write_json(directory / "channel_and_capability_audit.json", audit)
        final_ledger = ledger.snapshot()
        _write_json(directory / "episode_record.json", record)
        return {"episode_id": row.episode_id, "arm": row.arm,
                "record": record, "ledger": final_ledger,
                "later_paid_episodes_allowed": bool(
                    record["auditor_read"] and record["single_post_adherence"]),
                "claim_status": "PENDING_INDEPENDENT_COLLECTOR"}
    except BaseException as exc:
        secondary_failures: list[str] = []
        unknown_confirmed = False
        if reserved and not settled:
            try:
                ledger.mark_unknown(run_id, type(exc).__name__)
                unknown_confirmed = True
            except Exception as secondary:
                secondary_failures.append("budget_mark_unknown:" + type(secondary).__name__)
        try:
            partial_logs = _preserve_partial_inspect(directory)
        except Exception as secondary:
            partial_logs = []
            secondary_failures.append("partial_inspect_archive:" + type(secondary).__name__)
        partial_native = directory / "native" / "partial_evidence.json"
        def safe_digest(path: Path) -> str | None:
            try:
                return _sha256(path) if path.is_file() else None
            except Exception as secondary:
                secondary_failures.append("artifact_hash:" + type(secondary).__name__)
                return None

        stop = {
            "schema": "mechanism-paid-episode-stop-v2",
            "episode_id": row.episode_id, "assignment_manifest_sha256": assignment_sha,
            "stage": stage, "error_type": type(exc).__name__,
            "budget_state": "SETTLED" if settled else
                            "UNKNOWN" if unknown_confirmed else
                            "UNRESOLVED" if reserved else "UNRESERVED",
            "model_calls_attempted": attempts["attempted"],
            "model_request_boundary_observed": observed_requests,
            "partial_inspect_archives": partial_logs,
            "inspect_eval_sha256": safe_digest(inspect_path),
            "partial_native_sha256": safe_digest(partial_native),
            "native_payment_sha256": safe_digest(native_path),
            "complete_payment_claim": False,
            "no_retry_or_substitution": True,
            "secondary_failure_types": secondary_failures,
        }
        _write_json(directory / "STOPPED.json", stop)
        raise
