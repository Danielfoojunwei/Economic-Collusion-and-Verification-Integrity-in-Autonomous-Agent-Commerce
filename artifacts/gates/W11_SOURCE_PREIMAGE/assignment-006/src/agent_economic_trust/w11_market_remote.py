"""One supervised W11 market round per approved paid invocation.

Anvil resumes from a verified checkpoint between invocations. No command
silently iterates a market. The single canonical USD 20 ledger reserves before
the provider call; native payment remains local and valueless.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from typing import Any

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log
from inspect_ai.model import GenerateConfig, get_model

from .evidence import verify_evidence
from .remote import (
    APPROVED_MODEL_ID, MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS, PROJECT_CAP_USD,
    PROJECT_LEDGER_PATH, REQUEST_TIMEOUT_SECONDS, SCHEDULER_SECONDS,
    RemoteBoundaryError, _execution_enabled, _sha256, _usage_for,
    account_usage_delta_usd, account_usage_usd, guard_model_api,
)
from .remote_budget import BudgetLedger
from .remote_pricing import estimate_usage, pricing_snapshot, reserve_worst_case
from .w10_factorial_remote import (
    _decision_signature, _scan_native_log_for_secret, guard_high_reasoning,
)
from .w11_market_native import LiveNativeMarket, verify_market_evidence
from .w11_market_plan import (
    MarketRound, VerifiedHistoryEntry, case_for_round, digest, make_market_schedule,
)
from .w11_market_reporting import export_market_episode
from .w11_market_task import audit_saved_market_log, build_market_task


_ROOT = Path(__file__).resolve().parents[2]
_FREEZE_SCRIPT = _ROOT / "scripts/freeze_w11_market.py"
MAX_CALLS_NONE = 6
MAX_CALLS_DIRECT = 8


def _load_plan(plan_dir: Path) -> tuple[dict, str, tuple[MarketRound, ...]]:
    # Import the CLI function only here; this module is also imported from the CLI.
    import importlib.util

    spec = importlib.util.spec_from_file_location("w11_freeze_validation", _FREEZE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RemoteBoundaryError("W11 freeze validator is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.verify(plan_dir)
    raw = (plan_dir / "assignment_manifest.json").read_bytes()
    plan = json.loads(raw)
    private = json.loads((plan_dir / "private_rounds.json").read_bytes())
    rows = make_market_schedule(
        (plan_dir / "seed.hex").read_text(encoding="ascii").strip(),
        blocks=len({item["block_id"] for item in private}),
        r_values=tuple(sorted({item["r"] for item in private})),
    )
    return plan, sha256(raw).hexdigest(), rows


def _assert_source_frozen(plan: dict) -> None:
    actual = {name: _sha256(_ROOT / name) for name in plan["source_sha256"]}
    if actual != plan["source_sha256"]:
        raise RemoteBoundaryError("frozen W11 source changed before or during a model run")


def _market_rows(rows: tuple[MarketRound, ...], market_id: str) -> list[MarketRound]:
    selected = sorted((row for row in rows if row.market_id == market_id),
                      key=lambda row: row.round_index)
    if len(selected) != 4 or [row.round_index for row in selected] != list(range(4)):
        raise RemoteBoundaryError("choose one complete frozen four-round market")
    if len({row.r for row in selected}) != 1:
        raise RemoteBoundaryError("R payer changed within a market")
    return selected


def _run_id(assignment_sha: str, episode_id: str) -> str:
    return f"w11-market-{assignment_sha[:12]}-{episode_id}"


def _episode_dir(output_dir: Path, row: MarketRound) -> Path:
    return output_dir / row.market_id / "episodes" / row.episode_id


def _verify_saved_market_score(row: MarketRound, saved: Any,
                               record: dict[str, Any]) -> dict[str, Any]:
    score = saved.samples[0].scores["protected_receipt_score"].metadata
    case, artifact = case_for_round(row)
    oracle_status = sample_oracle(case, artifact)
    if (oracle_status not in {"PASS", "FAIL"}
            or type(score.get("Q")) is not bool
            or type(score.get("Y")) is not int
            or type(score.get("check_spent_units")) is not int
            or score.get("oracle_status") != oracle_status
            or score.get("Y") != (1 if oracle_status == "PASS" else 0)
            or score.get("artifact_digest") != row.artifact_digest
            or score.get("V") != record.get("verdict")
            or score.get("Q") != record.get("checked")
            or score.get("check_spent_units") != record.get("check_spent_units")
            or score.get("Y") != record.get("oracle_truth")):
        raise RemoteBoundaryError("saved W11 private scorer differs from assigned record")
    return score


def _load_prior_entries(
    rows: list[MarketRound], next_index: int, output_dir: Path,
    assignment_sha: str, ledger_snapshot: dict,
    source_sha256: dict[str, str],
) -> dict[str, VerifiedHistoryEntry]:
    """Reopen every prior log, archived native checkpoint and event chain."""
    entries: dict[str, VerifiedHistoryEntry] = {}
    for row in rows[:next_index]:
        directory = _episode_dir(output_dir, row)
        record_path = directory / "episode_record.json"
        if not record_path.is_file():
            raise RemoteBoundaryError("prior scheduled market episode lacks a final record")
        record = json.loads(record_path.read_bytes())
        native_path = directory / "native_evidence.json"
        inspect_path = directory / "inspect.eval"
        if (record.get("status") != "COMPLETE"
                or record.get("market_id") != row.market_id
                or record.get("episode_id") != row.episode_id
                or record.get("assignment_manifest_sha256") != assignment_sha
                or record.get("native_inspect_sha256") != _sha256(inspect_path)
                or record.get("native_payment_sha256") != _sha256(native_path)
                or record.get("source_sha256") != source_sha256
                or record.get("model_tier") != "REAL_LLM_REMOTE_APPROVED"
                or record.get("payment_tier") != "NATIVE_LOCAL_CHAIN"
                or record.get("ledger_run_id") != _run_id(assignment_sha, row.episode_id)):
            raise RemoteBoundaryError("prior market record differs from assigned evidence")
        saved = read_eval_log(str(inspect_path), resolve_attachments=True)
        if saved.eval.model != f"openrouter/{APPROVED_MODEL_ID}":
            raise RemoteBoundaryError("prior market model differs from approved route")
        if any(event.event == "model" and (
            event.model != f"openrouter/{APPROVED_MODEL_ID}"
            or getattr(event.config, "reasoning_effort", None) != "high"
        ) for event in saved.samples[0].events):
            raise RemoteBoundaryError("prior market model did not use high reasoning")
        audit = audit_saved_market_log(saved, row, entries=entries)
        if audit != record.get("channel_audit"):
            raise RemoteBoundaryError("prior market native channel audit differs")
        _verify_saved_market_score(row, saved, record)
        native_summary = verify_market_evidence(native_path)
        if native_summary.get("market_id") != row.market_id:
            raise RemoteBoundaryError("prior market native checkpoint is foreign")
        native_data = json.loads(native_path.read_bytes())
        native_round = next((item for item in native_data["rounds"]
                             if item["episode_id"] == row.episode_id), None)
        if (native_round is None or native_round["obligation_id"] != row.obligation_id
                or native_round["settlement"]["verdict"] != record["verdict"]
                or native_round["settlement"]["provider_payout_minor_units"]
                != record["provider_payout_minor_units"]
                or native_round["settlement"]["provider_paid"]
                != (record["payment_status"] == "PAID")):
            raise RemoteBoundaryError("prior market native settlement differs")
        verify_evidence(directory)
        manifest = json.loads((directory / "run_manifest.json").read_bytes())
        if (manifest["artifacts_sha256"].get("inspect.eval") != record["native_inspect_sha256"]
                or manifest["artifacts_sha256"].get("native_evidence.json")
                != record["native_payment_sha256"]):
            raise RemoteBoundaryError("prior market event manifest differs from originals")
        ledger_run = ledger_snapshot["runs"].get(record["ledger_run_id"])
        if (ledger_run is None or ledger_run["status"] != "SETTLED"
                or ledger_run["evidence_ref"] != "sha256:" + record["native_inspect_sha256"]
                or Decimal(ledger_run["actual_usd"])
                != Decimal(record["model_cost_usd_estimate"])
                or ledger_run["metadata"].get("model_id") != APPROVED_MODEL_ID
                or ledger_run["metadata"].get("market_id") != row.market_id
                or ledger_run["metadata"].get("episode_id") != row.episode_id
                or ledger_run["metadata"].get("assignment_sha") != assignment_sha):
            raise RemoteBoundaryError("prior paid market call lacks canonical ledger settlement")
        entries[row.episode_id] = VerifiedHistoryEntry(
            market_id=row.market_id, episode_id=row.episode_id,
            round_index=row.round_index, provider_id=row.provider_id,
            verifier_id=row.verifier_id, task_id=row.task_id,
            bid_fee_minor_units=None,
            audit_fee_payer_id=(row.provider_id if row.r else "client"),
            audit_fee_minor_units=row.audit_fee_minor_units,
            verdict=record["verdict"],
            provider_payout_minor_units=record["provider_payout_minor_units"],
            payment_status=record["payment_status"],
            native_evidence_sha256=_sha256(native_path),
            inspect_eval_sha256=_sha256(inspect_path),
            event_export_sha256=_sha256(directory / "events.jsonl"),
            verifier_status="PASS",
        )
    return entries


@dataclass(frozen=True)
class MarketEpisodePlan:
    assignment_dir: Path
    output_dir: Path
    market_id: str
    model_id: str = APPROVED_MODEL_ID
    ledger_path: Path = PROJECT_LEDGER_PATH
    cap_usd: Decimal = PROJECT_CAP_USD
    max_output_tokens: int = MAX_OUTPUT_TOKENS
    max_input_bytes: int = MAX_INPUT_BYTES

    def validate(self) -> tuple[dict, str, list[MarketRound]]:
        if self.model_id != APPROVED_MODEL_ID or self.cap_usd != PROJECT_CAP_USD:
            raise RemoteBoundaryError("W11 model ID or USD 20 cap differs from authorization")
        if self.ledger_path.resolve() != PROJECT_LEDGER_PATH.resolve():
            raise RemoteBoundaryError("W11 must use the canonical project ledger")
        if (not 1 <= self.max_output_tokens <= MAX_OUTPUT_TOKENS
                or not 1024 <= self.max_input_bytes <= MAX_INPUT_BYTES):
            raise RemoteBoundaryError("W11 per-call limit exceeds authorization")
        plan, assignment_sha, rows = _load_plan(self.assignment_dir)
        _assert_source_frozen(plan)
        return plan, assignment_sha, _market_rows(rows, self.market_id)


def preflight(plan: MarketEpisodePlan) -> dict[str, Any]:
    """No inference or local chain transaction; fail before a partial market."""
    frozen, assignment_sha, rows = plan.validate()
    snapshot = BudgetLedger(plan.ledger_path).snapshot()
    if snapshot["blocked"] or snapshot["cap_usd"] != "20":
        raise RemoteBoundaryError("shared project ledger is blocked")
    frozen_order = frozen["market_execution_order"]
    if plan.market_id not in frozen_order:
        raise RemoteBoundaryError("market is absent from frozen execution order")
    all_rows = _load_plan(plan.assignment_dir)[2]
    first_incomplete = None
    for market_id in frozen_order:
        scheduled = _market_rows(all_rows, market_id)
        done = [(_episode_dir(plan.output_dir, item) / "episode_record.json").is_file()
                for item in scheduled]
        if all(done):
            _load_prior_entries(scheduled, 4, plan.output_dir, assignment_sha,
                                snapshot, frozen["source_sha256"])
            continue
        first_incomplete = market_id
        if market_id != plan.market_id:
            raise RemoteBoundaryError("W11 cannot skip an earlier frozen market")
        break
    if first_incomplete is None:
        raise RemoteBoundaryError("all frozen markets already have four episodes")
    existing = [(_episode_dir(plan.output_dir, row) / "episode_record.json").is_file()
                for row in rows]
    next_index = next((i for i, done in enumerate(existing) if not done), len(rows))
    if any(existing[next_index:]):
        raise RemoteBoundaryError("market has a gap in completed assigned rounds")
    if any((_episode_dir(plan.output_dir, row) / "STOPPED.json").exists()
           for row in rows[next_index:]):
        raise RemoteBoundaryError("market has a stopped assigned episode")
    entries = _load_prior_entries(rows, next_index, plan.output_dir,
                                  assignment_sha, snapshot, frozen["source_sha256"])
    rates = pricing_snapshot(plan.model_id)
    per_round = [reserve_worst_case(
        rates, MAX_CALLS_DIRECT if row.communication_mode == "DIRECT" else MAX_CALLS_NONE,
        plan.max_input_bytes, plan.max_output_tokens,
    ) for row in rows]
    outstanding = sum(per_round[next_index:], Decimal("0"))
    available = Decimal(snapshot["available_usd"])
    next_row = rows[next_index] if next_index < len(rows) else None
    if next_row is not None:
        # Validate the exact view before any paid request. Missing or poisoned
        # prior entries stop here, not in a model prompt.
        build_market_task(next_row, entries=entries, fee_tier="SCRIPTED_CONTROL")
    return {
        "mode": "dry-run", "market_id": plan.market_id,
        "arm": rows[0].arm, "R": rows[0].r,
        "assignment_manifest_sha256": assignment_sha,
        "planned_market_episodes": len(rows),
        "completed_market_episodes": next_index,
        "next_episode_id": next_row.episode_id if next_row else None,
        "next_round_index": next_index if next_row else None,
        "next_offer_variant": next_row.offer_variant if next_row else None,
        "model_id": plan.model_id, "reasoning_effort": "high",
        "max_calls_next_episode": (MAX_CALLS_DIRECT if next_row and
                                   next_row.communication_mode == "DIRECT" else
                                   MAX_CALLS_NONE if next_row else 0),
        "per_round_worst_case_reservation_usd": [format(value, "f") for value in per_round],
        "next_reservation_usd": format(per_round[next_index], "f") if next_row else "0",
        "remaining_market_worst_case_usd": format(outstanding, "f"),
        "shared_ledger_available_usd": snapshot["available_usd"],
        "shared_ledger_last_hash": snapshot["last_hash"],
        "ready_to_execute": bool(next_row and available >= outstanding
                                 and _run_id(assignment_sha, next_row.episode_id)
                                 not in snapshot["runs"]),
        "pricing": rates,
        "native_state": ("resume_verified_checkpoint" if next_index else "new_local_anvil"),
        "claims": "feasibility_only_until_balanced_markets_complete",
    }


def execute_one(plan: MarketEpisodePlan) -> dict[str, Any]:
    """Execute exactly the next frozen episode, then checkpoint the market."""
    preview = preflight(plan)
    if not preview["ready_to_execute"]:
        raise RemoteBoundaryError("W11 market lacks worst-case budget or a pending episode")
    _execution_enabled()
    frozen, assignment_sha, rows = plan.validate()
    index = preview["next_round_index"]
    row = rows[index]
    ledger = BudgetLedger(plan.ledger_path)
    entries = _load_prior_entries(rows, index, plan.output_dir,
                                  assignment_sha, ledger.snapshot(), frozen["source_sha256"])
    market_dir = plan.output_dir / row.market_id
    if index == 0:
        market_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
        os.chmod(market_dir, 0o700)
    elif not market_dir.is_dir():
        raise RemoteBoundaryError("market directory is absent during resume")
    directory = _episode_dir(plan.output_dir, row)
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(directory, 0o700)
    native_log_path = directory / "inspect.eval"
    native_path = directory / "native_evidence.json"
    run_id = _run_id(assignment_sha, row.episode_id)
    reserve = Decimal(preview["next_reservation_usd"])
    rates = preview["pricing"]
    reserved = False
    settled = False
    stage = "native_setup"
    attempts = {"attempted": 0, "max_input_bytes_seen": 0}
    try:
        with LiveNativeMarket(
            row.market_id, market_dir / "native", r=row.r,
            assignment_manifest_sha256=assignment_sha,
            resume=index > 0,
        ) as native:
            funding = native.open_round(
                episode_id=row.episode_id, obligation_id=row.obligation_id,
                artifact_digest=row.artifact_digest,
                public_task_digest=row.public_task_digest,
                provider_id=row.provider_id, auditor_id=row.verifier_id,
            )
            task = build_market_task(
                row, entries=entries, fee_tier="NATIVE_LOCAL_VERIFIED",
                fee_receipt_sha256=funding["fee_receipt_sha256"],
                scheduler_seconds=SCHEDULER_SECONDS,
            )
            _assert_source_frozen(frozen)
            stage = "budget_reservation"
            ledger.reserve(run_id, reserve, plan.cap_usd,
                           metadata={"model_id": plan.model_id,
                                     "market_id": row.market_id,
                                     "episode_id": row.episode_id,
                                     "assignment_sha": assignment_sha})
            reserved = True
            stage = "provider_request"
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
            attempts = guard_model_api(
                model, max_calls=preview["max_calls_next_episode"],
                max_input_bytes=plan.max_input_bytes,
                max_output_tokens=plan.max_output_tokens,
            )
            guard_high_reasoning(model)
            _assert_source_frozen(frozen)
            with TemporaryDirectory(prefix="w11-inspect-", dir=directory) as temporary:
                logs = inspect_eval(
                    task, model=model, sample_id=row.task_id,
                    max_samples=1, max_tasks=1, epochs=1,
                    retry_on_error=0, fail_on_error=True,
                    time_limit=SCHEDULER_SECONDS, token_limit=50_000,
                    message_limit=40, turn_limit=12,
                    log_dir=temporary, log_format="eval", log_model_api=False,
                    display="none", log_level="error",
                )
                if len(logs) != 1 or not logs[0].location:
                    raise RemoteBoundaryError("W11 native Inspect log is missing")
                log = logs[0]
                native_log_path.write_bytes(Path(log.location).read_bytes())
                os.chmod(native_log_path, 0o600)
                saved = read_eval_log(str(native_log_path), resolve_attachments=True)
                _scan_native_log_for_secret(native_log_path, saved,
                                            os.environ["OPENROUTER_API_KEY"])
                if (saved.status != log.status or saved.eval.model != log.eval.model
                        or not saved.samples or len(saved.samples) != 1
                        or saved.samples[0].store != log.samples[0].store
                        or saved.samples[0].scores != log.samples[0].scores
                        or _decision_signature(saved) != _decision_signature(log)):
                    raise RemoteBoundaryError("saved W11 Inspect log differs from model output")
                usage = _usage_for(log, plan.model_id)
                usage_after = account_usage_usd()
                account_delta = account_usage_delta_usd(usage_before, usage_after)
                cost = max(estimate_usage(rates, usage, calls=attempts["attempted"]),
                           account_delta)
                if cost > reserve:
                    raise RemoteBoundaryError("W11 model usage exceeded reserved upper bound")
                ledger.settle(run_id, cost, "sha256:" + _sha256(native_log_path))
                settled = True
            stage = "saved_native_log_audit"
            if saved.eval.model != f"openrouter/{plan.model_id}":
                raise RemoteBoundaryError("saved W11 model route differs from approval")
            audit = audit_saved_market_log(saved, row, entries=entries)
            for event in saved.samples[0].events:
                if event.event == "model" and (
                    event.model != f"openrouter/{plan.model_id}"
                    or getattr(event.config, "reasoning_effort", None) != "high"
                ):
                    raise RemoteBoundaryError("saved W11 model call differs from high reasoning")
            score = saved.samples[0].scores["protected_receipt_score"].metadata
            case, artifact = case_for_round(row)
            verdict = score.get("V")
            if (verdict not in {"ACCEPT", "REJECT"}
                    or score.get("artifact_digest") != artifact.digest()
                    or score.get("oracle_status") not in {"PASS", "FAIL"}
                    or score.get("check_spent_units") not in (0, row.check_cost_units)
                    or score.get("Y") != (1 if score["oracle_status"] == "PASS" else 0)
                    or sample_oracle(case, artifact) != score["oracle_status"]):
                raise RemoteBoundaryError("saved W11 scorer differs from private task oracle")
            _assert_source_frozen(frozen)
            native.verify_open_round(row.obligation_id)
            stage = "native_settlement"
            payout = native.settle_round(row.obligation_id, verdict, row.artifact_digest)
            shutil.copyfile(market_dir / "native" / "evidence.json", native_path)
            os.chmod(native_path, 0o600)
            native_data = json.loads(native_path.read_bytes())
            native_summary = verify_market_evidence(native_path)
            if native_summary.get("market_id") != row.market_id:
                raise RemoteBoundaryError("saved market native evidence is foreign")
            record = {
                "status": "COMPLETE", "market_id": row.market_id,
                "episode_id": row.episode_id, "round_index": row.round_index,
                "arm": row.arm, "R": row.r,
                "assignment_manifest_sha256": assignment_sha,
                "offer_variant": row.offer_variant,
                "model_tier": "REAL_LLM_REMOTE_APPROVED",
                "payment_tier": "NATIVE_LOCAL_CHAIN",
                "verdict": verdict, "checked": bool(score["Q"]),
                "check_spent_units": score["check_spent_units"],
                "oracle_truth": score["Y"],
                "payment_status": "PAID" if payout["provider_paid"] else "NOT_PAID",
                "provider_payout_minor_units": payout["provider_payout_minor_units"],
                "channel_audit": audit,
                "native_inspect_sha256": _sha256(native_log_path),
                "native_payment_sha256": _sha256(native_path),
                "model_calls": attempts["attempted"],
                "max_input_bytes_seen": attempts["max_input_bytes_seen"],
                "model_cost_usd_estimate": format(cost, "f"),
                "account_usage_delta_usd": format(account_delta, "f"),
                "ledger_run_id": run_id,
                "ledger_last_hash": ledger.snapshot()["last_hash"],
                "source_sha256": frozen["source_sha256"],
            }
            (directory / "episode_record.json").write_bytes(
                json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n")
            stage = "event_export"
            exported = export_market_episode(
                directory, row=row, saved_log=saved,
                native_data=native_data, record=record,
                assignment_manifest_sha256=assignment_sha,
                model_behavior_tier="REAL_LLM_REMOTE_APPROVED",
                model_id=plan.model_id,
                source_sha256=frozen["source_sha256"], pricing=rates,
            )
        return {"episode_id": row.episode_id, "market_id": row.market_id,
                "record": record, "export": exported,
                "next_round_index": index + 1 if index + 1 < len(rows) else None,
                "ledger": ledger.snapshot()}
    except BaseException as exc:
        if reserved and not settled:
            ledger.mark_unknown(run_id, type(exc).__name__)
        (directory / "STOPPED.json").write_text(json.dumps({
            "market_id": row.market_id, "episode_id": row.episode_id,
            "stage": stage, "error_type": type(exc).__name__,
            "budget_state": "SETTLED" if settled else "UNKNOWN" if reserved else "UNRESERVED",
            "model_calls": attempts["attempted"],
            "native_inspect_sha256": (_sha256(native_log_path) if native_log_path.is_file() else None),
            "native_payment_sha256": (_sha256(native_path) if native_path.is_file() else None),
        }, sort_keys=True) + "\n")
        raise


def sample_oracle(case: Any, artifact: Any) -> str:
    from .protected_receipts import receipt_oracle

    return receipt_oracle(case, artifact).status.value

