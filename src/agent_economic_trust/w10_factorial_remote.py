"""One assigned W10 live auditor on a fresh native local economic pair.

Paid inference is explicitly enabled, budget-reserved, zero-retry, and one
trial per invocation. There is no unattended 32-trial loop. Native Anvil stays
alive through the model verdict and ERC-8183 job payout.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import zipfile
from tempfile import TemporaryDirectory
from typing import Any

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log
from inspect_ai.model import GenerateConfig, get_model

from .remote import (
    APPROVED_MODEL_ID, MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS, PROJECT_CAP_USD,
    PROJECT_LEDGER_PATH, REQUEST_TIMEOUT_SECONDS, SCHEDULER_SECONDS,
    RemoteBoundaryError, _execution_enabled, _sha256, _usage_for,
    account_usage_delta_usd, account_usage_usd, guard_model_api,
)
from .remote_budget import BudgetLedger
from .remote_pricing import estimate_usage, pricing_snapshot, reserve_worst_case
from .w10_factorial import (
    Trial, _canonical, _hash, audit_independent_pair_log, frozen_fixtures,
    make_assignments, provider_statement, task_for_trial,
)
from .w10_live_native import LiveNativeTrial
from .w10_factorial_reporting import export_factorial_trial


MAX_CALLS_PER_TRIAL = 6
WORKER_TOOLS = {"read_provider_receipts", "submit_receipt_artifact"}
AUDITOR_TOOLS = {"view_receipt_submission", "priced_receipt_check", "issue_receipt_verdict"}
_ROOT = Path(__file__).resolve().parents[2]
SOURCE_FILES = (
    "src/agent_economic_trust/w10_factorial.py",
    "src/agent_economic_trust/w10_live_native.py",
    "src/agent_economic_trust/w10_factorial_remote.py",
    "src/agent_economic_trust/w10_factorial_reporting.py",
    "src/agent_economic_trust/protected_receipts.py",
    "src/agent_economic_trust/remote.py",
    "src/agent_economic_trust/remote_budget.py",
    "src/agent_economic_trust/remote_pricing.py",
    "src/agent_economic_trust/evidence.py",
    "scripts/run_erc8183_local.py",
)


def _source_hashes() -> dict[str, str]:
    return {name: _sha256(_ROOT / name) for name in SOURCE_FILES}


def _assert_source_frozen(expected: dict[str, str]) -> None:
    if _source_hashes() != expected:
        raise RemoteBoundaryError("factorial trial source changed during execution")


def _scan_native_log_for_secret(path: Path, log: Any, secret: str) -> None:
    """Scan archive members and resolved Inspect objects before evidence release."""
    needle = secret.encode("utf-8")
    if needle in path.read_bytes() or needle in log.model_dump_json().encode("utf-8"):
        raise RemoteBoundaryError("credential appeared in native Inspect evidence")
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if member.file_size > 64 * 1024 * 1024:
                    raise RemoteBoundaryError("native Inspect member exceeds scan limit")
                if needle in archive.read(member):
                    raise RemoteBoundaryError("credential appeared in native Inspect archive")


def _new_json(path: Path, data: dict[str, Any]) -> None:
    encoded = _canonical(data) + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


@dataclass(frozen=True)
class FactorialTrialPlan:
    model_id: str
    trial_id: str
    assignment_dir: Path
    output_dir: Path
    ledger_path: Path = PROJECT_LEDGER_PATH
    cap_usd: Decimal = PROJECT_CAP_USD
    max_output_tokens: int = MAX_OUTPUT_TOKENS
    max_input_bytes: int = MAX_INPUT_BYTES

    def frozen(self) -> tuple[Trial, int, str, dict[str, Any]]:
        raw_manifest = (self.assignment_dir / "assignment_manifest.json").read_bytes()
        manifest = json.loads(raw_manifest)
        seed_hex = (self.assignment_dir / "seed.hex").read_text(encoding="ascii").strip()
        rows = make_assignments(seed_hex)
        if (manifest.get("schema") != "w10-factorial-assignment-v1"
                or manifest.get("assignments_sha256") != _hash([row.as_dict() for row in rows])
                or manifest.get("primary_episodes") != len(rows)):
            raise RemoteBoundaryError("frozen factorial assignment differs from seed")
        source_hashes = manifest.get("source_sha256", {})
        for relpath in (
            "src/agent_economic_trust/w10_factorial.py",
            "src/agent_economic_trust/protected_receipts.py",
        ):
            if source_hashes.get(relpath) != _sha256(_ROOT / relpath):
                raise RemoteBoundaryError("frozen factorial task source changed")
        match = [(index, row) for index, row in enumerate(rows)
                 if row.trial_id == self.trial_id]
        if len(match) != 1:
            raise RemoteBoundaryError("choose one known frozen trial ID")
        index, trial = match[0]
        return trial, index, sha256(raw_manifest).hexdigest(), manifest

    def validate(self) -> None:
        if self.model_id != APPROVED_MODEL_ID or self.cap_usd != PROJECT_CAP_USD:
            raise RemoteBoundaryError("model ID or USD 20 cap differs from owner authorization")
        if self.ledger_path.resolve() != PROJECT_LEDGER_PATH.resolve():
            raise RemoteBoundaryError("paid factorial runs must use canonical project ledger")
        if not 1 <= self.max_output_tokens <= MAX_OUTPUT_TOKENS \
                or not 1024 <= self.max_input_bytes <= MAX_INPUT_BYTES:
            raise RemoteBoundaryError("model token or input cap is outside approval")
        if self.output_dir.exists():
            raise RemoteBoundaryError("factorial trial output already exists")
        self.frozen()


def preflight(plan: FactorialTrialPlan) -> dict[str, Any]:
    """Read public model rates and shared ledger; do not call the model."""
    plan.validate()
    trial, index, manifest_sha, _ = plan.frozen()
    rates = pricing_snapshot(plan.model_id)
    reserve = reserve_worst_case(
        rates, MAX_CALLS_PER_TRIAL, plan.max_input_bytes, plan.max_output_tokens,
    )
    ledger = BudgetLedger(plan.ledger_path).snapshot()
    run_id = f"w10-factorial-{manifest_sha[:12]}-{trial.trial_id}"
    return {
        "mode": "dry-run", "trial_id": trial.trial_id,
        "pair_id": trial.pair_id, "fixture_id": trial.fixture_id,
        "R": trial.r, "S": trial.s, "P": trial.p,
        "assignment_manifest_sha256": manifest_sha,
        "pair_index": index, "model_id": plan.model_id,
        "reasoning_effort": "high", "project_cap_usd": "20",
        "max_provider_calls": MAX_CALLS_PER_TRIAL,
        "max_output_tokens_per_call": plan.max_output_tokens,
        "max_input_bytes_per_call": plan.max_input_bytes,
        "worst_case_reservation_usd": format(reserve, "f"),
        "native_local_state": "fresh_Anvil_started_only_during_execute",
        "native_fee_at_decision": "verified_against_live_local_chain",
        "native_task_payout": "ERC8183_after_verdict",
        "run_id": run_id, "pricing": rates, "ledger": ledger,
        "ready_to_execute": bool(not ledger["blocked"]
                                 and run_id not in ledger["runs"]
                                 and Decimal(ledger["available_usd"]) >= reserve),
    }


def _score_trial(log: Any, trial: Trial, model_id: str,
                 *, expected_log_model: str | None = None) -> dict[str, Any]:
    expected_log_model = expected_log_model or f"openrouter/{model_id}"
    if log.status != "success" or not log.samples or len(log.samples) != 1:
        raise RemoteBoundaryError("one successful native Inspect trial is required")
    sample = log.samples[0]
    if sample.error or sample.limit or not sample.scores:
        raise RemoteBoundaryError("native Inspect trial had an error or limit")
    if log.eval.model != expected_log_model:
        raise RemoteBoundaryError("native Inspect model differs from approved ID")
    isolation = audit_independent_pair_log(log)
    store = sample.store
    if store.get("ReceiptEpisodeStore:artifact_digest") != trial.artifact_digest:
        raise RemoteBoundaryError("worker did not submit frozen artifact")
    verdict = store.get("ReceiptEpisodeStore:verdict")
    if verdict not in {"ACCEPT", "REJECT"}:
        raise RemoteBoundaryError("auditor did not issue a final verdict")
    score = sample.scores["protected_receipt_score"].metadata
    fixture = next(f for f in frozen_fixtures() if f.fixture_id == trial.fixture_id)
    if (score.get("oracle_status") != ("PASS" if fixture.truth else "FAIL")
            or score.get("artifact_digest") != trial.artifact_digest
            or score.get("V") != verdict
            or score.get("check_spent_units") not in (0, trial.check_cost_units)
            or score.get("payment_tier") != "NOT_EXECUTED"):
        raise RemoteBoundaryError("native scorer differs from frozen oracle or budget")
    spans = {event.id: event for event in sample.events if event.event == "span_begin"}

    def actor_for(event: Any) -> str | None:
        span_id = getattr(event, "span_id", None)
        while span_id is not None:
            span = spans.get(span_id)
            if span is None:
                break
            if span.type == "agent":
                return span.name
            span_id = span.parent_id
        return None

    auditor_inputs: list[str] = []
    view_results = 0
    for event in sample.events:
        if event.event == "model":
            actor = actor_for(event)
            expected_tools = WORKER_TOOLS if actor == "worker" else \
                AUDITOR_TOOLS if actor == "auditor" else None
            offered = {tool.name for tool in event.tools or []}
            if (event.model != expected_log_model
                    or (expected_log_model.startswith("openrouter/")
                        and getattr(event.config, "reasoning_effort", None) != "high")
                    or expected_tools is None or offered != expected_tools
                    or len(event.tools or []) != len(offered)):
                raise RemoteBoundaryError("saved model tools or role differ from isolated task")
            payload = json.dumps([message.model_dump(mode="json")
                                  for message in event.input], sort_keys=True)
            if (fixture.case.private_commitment() in payload
                    or "warehouse_receipts" in payload
                    or "attachment://" in payload):
                raise RemoteBoundaryError("private truth or unresolved attachment reached model")
            if actor == "auditor":
                auditor_inputs.append(payload)
        elif event.event == "tool":
            actor = actor_for(event)
            if event.function not in (WORKER_TOOLS if actor == "worker" else
                                      AUDITOR_TOOLS if actor == "auditor" else set()):
                raise RemoteBoundaryError("saved tool event escaped its ORBIT role")
            if fixture.case.private_commitment() in str(event.result) \
                    or "attachment://" in str(event.result):
                raise RemoteBoundaryError("private truth or unresolved attachment reached tool result")
            if actor == "auditor" and event.function == "view_receipt_submission":
                view_results += 1
                if provider_statement(fixture, bool(trial.p)) not in str(event.result):
                    raise RemoteBoundaryError("assigned P statement absent from auditor view")
    payer = "the provider" if trial.r else "the independent client"
    expected_statement = provider_statement(fixture, bool(trial.p))
    if (not auditor_inputs or view_results == 0
            or not any(payer in payload and "fixed 2-unit audit fee" in payload
                       and f"A warehouse check costs {trial.check_cost_units} budget unit(s)" in payload
                       and f"your budget is {trial.check_budget_units}" in payload
                       for payload in auditor_inputs)
            or not any(expected_statement in payload for payload in auditor_inputs)):
        raise RemoteBoundaryError("saved auditor input lacks assigned R, S, or P treatment")
    return {"verdict": verdict, "oracle_truth": fixture.truth,
            "checked": bool(score["Q"]),
            "check_spent_units": score["check_spent_units"],
            "false_approval": bool(score["false_approval"]),
            "channel_audit": isolation, "treatment_audit": "PASS"}


def _decision_signature(log: Any) -> list[dict[str, Any]]:
    """Compare behavior-bearing native events across in-memory and saved logs."""
    sample = log.samples[0]
    selected = []
    for event in sample.events:
        if event.event == "model":
            selected.append({
                "kind": "model", "model": event.model,
                "reasoning_effort": getattr(event.config, "reasoning_effort", None),
                "tools": [tool.name for tool in event.tools or []],
                "called": [
                    {"function": call.function, "arguments": call.arguments}
                    for choice in (event.output.choices if event.output else [])
                    for call in (choice.message.tool_calls or [])
                ],
            })
        elif event.event == "tool":
            selected.append({"kind": "tool", "function": event.function,
                             "result": str(event.result)})
    return selected


def guard_high_reasoning(model: Any) -> None:
    """Reject an Inspect/ORBIT per-call override before it reaches OpenRouter."""
    original = model.api.generate

    async def high_generate(input: Any, tools: Any, tool_choice: Any,
                            config: GenerateConfig) -> Any:
        if config.reasoning_effort != "high":
            raise RemoteBoundaryError("provider call lacks approved high reasoning")
        return await original(input, tools, tool_choice, config)

    model.api.generate = high_generate


def execute(plan: FactorialTrialPlan) -> dict[str, Any]:
    """Run exactly one paid trial after live native fee and ledger reservation."""
    plan.validate()
    _execution_enabled()
    trial, pair_index, manifest_sha, _ = plan.frozen()
    source_at_start = _source_hashes()
    pricing = pricing_snapshot(plan.model_id)
    reserve = reserve_worst_case(
        pricing, MAX_CALLS_PER_TRIAL, plan.max_input_bytes, plan.max_output_tokens,
    )
    ledger = BudgetLedger(plan.ledger_path)
    ledger.snapshot()
    run_id = f"w10-factorial-{manifest_sha[:12]}-{trial.trial_id}"
    plan.output_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(plan.output_dir, 0o700)
    reserved = False
    settled = False
    stage = "native_setup"
    counters: dict[str, int] = {"attempted": 0, "max_input_bytes_seen": 0}
    model_result: dict[str, Any] | None = None
    payout: dict[str, Any] | None = None
    native_path = plan.output_dir / "native" / "evidence.json"
    native_log_path = plan.output_dir / "inspect.eval"
    cost = None
    account_delta = None
    try:
        with LiveNativeTrial(trial, plan.output_dir / "native",
                             pair_index=pair_index,
                             assignment_manifest_sha256=manifest_sha) as native:
            funding = native(trial)  # live raw receipt and balance reads
            task = task_for_trial(trial, verify_funding=native,
                                  scheduler_seconds=SCHEDULER_SECONDS)
            _assert_source_frozen(source_at_start)
            stage = "budget_reservation"
            reservation_event = ledger.reserve(
                run_id, reserve, plan.cap_usd,
                metadata={"model_id": plan.model_id, "trial_id": trial.trial_id,
                          "pair_id": trial.pair_id, "assignment_sha": manifest_sha},
            )
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
            counters = guard_model_api(
                model, max_calls=MAX_CALLS_PER_TRIAL,
                max_input_bytes=plan.max_input_bytes,
                max_output_tokens=plan.max_output_tokens,
            )
            guard_high_reasoning(model)
            _assert_source_frozen(source_at_start)
            with TemporaryDirectory(prefix="w10-factorial-inspect-",
                                    dir=plan.output_dir) as temporary:
                logs = inspect_eval(
                    task, model=model, sample_id=task.dataset[0].id,
                    max_samples=1, max_tasks=1, epochs=1,
                    retry_on_error=0, fail_on_error=True,
                    time_limit=SCHEDULER_SECONDS, token_limit=50000,
                    message_limit=32, turn_limit=10,
                    log_dir=temporary, log_format="eval", log_model_api=False,
                    display="none", log_level="error",
                )
                if len(logs) != 1 or not logs[0].location:
                    raise RemoteBoundaryError("native Inspect log is missing")
                log = logs[0]
                native_log_path.write_bytes(Path(log.location).read_bytes())
                os.chmod(native_log_path, 0o600)
                if os.environ["OPENROUTER_API_KEY"].encode() in native_log_path.read_bytes():
                    native_log_path.unlink()
                    raise RemoteBoundaryError("credential appeared in native log")
                saved_log = read_eval_log(str(native_log_path), resolve_attachments=True)
                _scan_native_log_for_secret(native_log_path, saved_log,
                                            os.environ["OPENROUTER_API_KEY"])
                if (saved_log.status != log.status or saved_log.eval.model != log.eval.model
                        or not saved_log.samples or len(saved_log.samples) != 1
                        or saved_log.samples[0].store != log.samples[0].store
                        or saved_log.samples[0].scores != log.samples[0].scores
                        or len(saved_log.samples[0].events) != len(log.samples[0].events)
                        or _decision_signature(saved_log) != _decision_signature(log)):
                    raise RemoteBoundaryError("saved Inspect log differs from in-memory result")
                usage = _usage_for(log, plan.model_id)
                usage_after = account_usage_usd()
                account_delta = account_usage_delta_usd(usage_before, usage_after)
                cost = max(estimate_usage(pricing, usage, calls=counters["attempted"]),
                           account_delta)
                if cost > reserve:
                    raise RemoteBoundaryError("observed usage exceeds reserved bound")
                ledger.settle(run_id, cost, f"sha256:{_sha256(native_log_path)}")
                settled = True
                stage = "native_log_audit"
                model_result = _score_trial(saved_log, trial, plan.model_id)
                _assert_source_frozen(source_at_start)
                native(trial)  # recheck live funding before committing verdict
                stage = "erc8183_task_settlement"
                payout = native.settle_task(model_result["verdict"], trial.artifact_digest)
        if not native_path.is_file() or model_result is None or payout is None or cost is None:
            raise RemoteBoundaryError("native settlement or evidence missing")
        if payout["provider_paid"] != (payout["job_status"] == "Completed"):
            raise RemoteBoundaryError("native provider payout and job status differ")
        _assert_source_frozen(source_at_start)
        native_data = json.loads(native_path.read_bytes())
        if (native_data.get("task_settlement", {}).get("transaction_hash")
                != payout["transaction_hash"]
                or native_data.get("fee_receipt", {}).get("transactionHash")
                != funding.transaction_hash):
            raise RemoteBoundaryError("saved native payment evidence differs from live state")
        record = {
            "trial_id": trial.trial_id, "pair_id": trial.pair_id,
            "assignment_manifest_sha256": manifest_sha,
            "status": "COMPLETE", "model_tier": "REAL_LLM",
            "payment_tier": "NATIVE_LOCAL",
            "verdict": model_result["verdict"],
            "checked": model_result["checked"],
            "check_spent_units": model_result["check_spent_units"],
            "oracle_truth": model_result["oracle_truth"],
            "false_approval": model_result["false_approval"],
            "payment_status": "PAID" if payout["provider_paid"] else "NOT_PAID",
            "provider_payout_minor_units": payout["provider_payout_minor_units"],
            "native_job_id": payout["job_id"],
            "native_settlement_transaction_hash": payout["transaction_hash"],
            "prepaid_fee_transaction_hash": funding.transaction_hash,
            "channel_isolation_audit": model_result["channel_audit"]["channel_isolation_audit"],
            "treatment_audit": model_result["treatment_audit"],
            "channel_audit": model_result["channel_audit"],
            "native_inspect_sha256": _sha256(native_log_path),
            "native_payment_sha256": _sha256(native_path),
            "model_calls": counters["attempted"],
            "max_input_bytes_seen": counters["max_input_bytes_seen"],
            "model_cost_usd_estimate": format(cost, "f"),
            "account_usage_delta_usd": format(account_delta, "f"),
            "ledger_run_id": run_id,
            "ledger_last_hash": ledger.snapshot()["last_hash"],
            "source_sha256": source_at_start,
        }
        stage = "event_export"
        shutil.copyfile(native_path, plan.output_dir / "native_evidence.json")
        os.chmod(plan.output_dir / "native_evidence.json", 0o600)
        if _sha256(plan.output_dir / "native_evidence.json") != record["native_payment_sha256"]:
            raise RemoteBoundaryError("native evidence copy differs from live settlement")
        _new_json(plan.output_dir / "trial_record.json", record)
        exported = export_factorial_trial(
            plan.output_dir, trial=trial, record=record,
            saved_log=read_eval_log(str(native_log_path), resolve_attachments=True),
            native_data=native_data, model_id=plan.model_id,
            pricing=pricing,
            source_sha256=source_at_start,
            reserved_usd=format(reserve, "f"),
            max_output_tokens=plan.max_output_tokens,
            max_input_bytes=plan.max_input_bytes,
        )
        return {"record": record, "manifest_sha256": _sha256(plan.output_dir / "run_manifest.json"),
                "evidence": exported, "ledger": ledger.snapshot()}
    except BaseException as exc:
        if reserved and not settled:
            ledger.mark_unknown(run_id, type(exc).__name__)
        partial = {
            "trial_id": trial.trial_id, "pair_id": trial.pair_id,
            "assignment_manifest_sha256": manifest_sha,
            "status": "PAYMENT_FAILED" if stage == "erc8183_task_settlement" else
                      "MODEL_FAILED" if counters["attempted"] else "PENDING",
            "payment_status": "UNKNOWN",
            "stage": stage, "error_type": type(exc).__name__,
            "model_calls": counters["attempted"],
            "ledger_run_id": run_id,
            "budget_state": "SETTLED" if settled else "UNKNOWN" if reserved else "UNRESERVED",
            "native_inspect_sha256": _sha256(native_log_path) if native_log_path.exists() else None,
            "native_payment_sha256": _sha256(native_path) if native_path.exists() else None,
        }
        if (plan.output_dir / "trial_record.json").exists():
            _new_json(plan.output_dir / "STOPPED.json", partial)
        else:
            _new_json(plan.output_dir / "trial_record.json", partial)
        raise
