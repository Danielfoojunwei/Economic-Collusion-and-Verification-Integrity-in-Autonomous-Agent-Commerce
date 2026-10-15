"""Fail-stop, one-row-at-a-time prospective AP2 LIVE paid runner.

Importing or preflighting this module sends no model or native payment call.
Execution requires an independently frozen source/assignment and explicit paid
runtime settings. All worktrees debit the one main-checkout USD50 ledger.
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

from .ap2_live_plan import (CANONICAL_LEDGER_PATH, CONTINGENCY_USD,
    MAX_CALLS_PER_EPISODE, MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS, MODEL_ID)
from .ap2_live_purchase import NativeAuditPurchase, validate_ap2_authorization
from .ap2_live_purchase_verifier import verify_native_audit_purchase
from .ap2_live_task import ap2_live_invoice_orbit
from .ap2_live_fixture import invoice_case
from .open005_native import Open005NativeController
from .ap2_live_open005_verifier import (verify_ap2_funded_evidence as verify_open005_funded_evidence,
    verify_ap2_native_evidence as verify_open005_native_evidence)
from .remote import (REQUEST_TIMEOUT_SECONDS, RemoteBoundaryError,
    _safe_model_input_size, _usage_for, account_usage_delta_usd,
    account_usage_usd)
from .remote_budget import BudgetLedger
from .remote_pricing import estimate_usage, pricing_snapshot, reserve_worst_case
from .open005_remote import assert_no_key, write_json


ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "artifacts/gates/AP2_LIVE/runs-001"


def file_sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RemoteBoundaryError("saved evidence must be a regular file")
    return sha256(path.read_bytes()).hexdigest()


def quarantine_unverified_record(directory: Path) -> None:
    """A failed final verifier must not leave a competing COMPLETE record."""
    proposed = directory / "episode_record.json"
    rejected = directory / "unverified_episode_record.json"
    if proposed.exists():
        if rejected.exists():
            raise RemoteBoundaryError("unverified episode record was already quarantined")
        proposed.replace(rejected)


def _run_id(assignment_sha: str, episode_id: str) -> str:
    return f"ap2live-{assignment_sha[:12]}-{episode_id}"


@dataclass(frozen=True)
class Ap2LivePlan:
    ledger_path: Path = CANONICAL_LEDGER_PATH
    runs_dir: Path = RUNS
    model_id: str = MODEL_ID
    max_calls: int = MAX_CALLS_PER_EPISODE
    max_input_bytes: int = MAX_INPUT_BYTES
    max_output_tokens: int = MAX_OUTPUT_TOKENS

    def validate(self) -> tuple[dict, str, tuple]:
        from scripts.freeze_ap2_live import verify
        if (self.ledger_path.resolve() != CANONICAL_LEDGER_PATH.resolve()
                or self.runs_dir.resolve() != RUNS.resolve()
                or self.model_id != MODEL_ID or self.max_calls != MAX_CALLS_PER_EPISODE
                or self.max_input_bytes != MAX_INPUT_BYTES
                or self.max_output_tokens != MAX_OUTPUT_TOKENS):
            raise RemoteBoundaryError("AP2 LIVE runner differs from canonical frozen limits")
        return verify()


def fresh_budget(plan: Ap2LivePlan, frozen: dict,
                 remaining: int) -> tuple[dict, Decimal, dict]:
    state = BudgetLedger(plan.ledger_path).snapshot()
    if (state["cap_usd"] != "50" or state["blocked"]
            or state["unknown_run_ids"] or state["reserved_usd"] != "0"):
        raise RemoteBoundaryError("shared USD50 ledger is blocked or concurrently reserved")
    prices = pricing_snapshot(plan.model_id)
    reserve = max(Decimal(frozen["worst_case_reserve_usd_per_episode"]),
                  reserve_worst_case(prices, plan.max_calls,
                                     plan.max_input_bytes, plan.max_output_tokens))
    if reserve * remaining + CONTINGENCY_USD > Decimal(state["available_usd"]):
        raise RemoteBoundaryError("full remaining AP2 LIVE reserve exceeds USD50 headroom")
    return prices, reserve, state


def preflight(plan: Ap2LivePlan = Ap2LivePlan()) -> dict:
    """Read-only; prove full future block reserve before selecting one row."""
    from scripts.collect_ap2_live import verify_episode
    frozen, assignment_sha, rows = plan.validate()
    ledger = BudgetLedger(plan.ledger_path).snapshot()
    next_index = None
    for index, row in enumerate(rows):
        path = plan.runs_dir / "episodes" / row.episode_id
        if (path / "STOPPED.json").exists():
            raise RemoteBoundaryError("earlier AP2 LIVE row stopped; no retry or later call")
        if (path / "episode_record.json").is_file():
            if next_index is not None:
                raise RemoteBoundaryError("completed row after gap in execution order")
            verify_episode(row, path, frozen=frozen,
                           assignment_sha=assignment_sha, ledger=ledger)
        elif path.exists():
            raise RemoteBoundaryError("partial AP2 LIVE row exists; no retry")
        elif next_index is None:
            next_index = index
    if next_index is None:
        raise RemoteBoundaryError("all assigned AP2 LIVE rows already attempted")
    row = rows[next_index]
    if _run_id(assignment_sha, row.episode_id) in ledger["runs"]:
        raise RemoteBoundaryError("shared ledger run already exists for assigned row")
    _, reserve, state = fresh_budget(plan, frozen, len(rows) - next_index)
    return {"status": "PREFLIGHT_PASS_NO_CALL", "next_episode_id": row.episode_id,
            "next_index": next_index, "remaining_rows": len(rows) - next_index,
            "assignment_manifest_sha256": assignment_sha,
            "full_remaining_reserve_usd": str(reserve * (len(rows) - next_index)),
            "per_episode_reserve_usd": str(reserve),
            "contingency_usd": str(CONTINGENCY_USD),
            "available_usd": state["available_usd"],
            "ledger_seq": state["seq"]}


def guard_api(model: Any, plan: Ap2LivePlan) -> list[dict]:
    """Enforce the exact forwarded request boundary, including SDK retry=0."""
    observed: list[dict] = []
    original = model.api.generate

    async def bounded(input: Any, tools: Any, tool_choice: Any, config: Any) -> Any:
        size = _safe_model_input_size(input, tools)
        try:
            strict_tool_schemas(tools)
            schemas_valid = True
        except RemoteBoundaryError:
            schemas_valid = False
        reasoning = any(isinstance(part, ContentReasoning)
                        for message in input
                        for part in (message.content if isinstance(message.content, list) else []))
        if (len(observed) >= plan.max_calls or size > plan.max_input_bytes
                or not schemas_valid or reasoning
                or config.reasoning_effort != "high" or config.reasoning_history != "none"
                or config.max_tokens != plan.max_output_tokens or config.max_retries != 0):
            observed.append({"call_index": len(observed) + 1,
                             "serialized_input_bytes": size,
                             "local_boundary_passed": False,
                             "provider_api_invoked": False,
                             "network_forwarding": "NO_LOCAL_REJECTION",
                             "completed": False})
            raise RemoteBoundaryError("AP2 LIVE request exceeded frozen model controls")
        item = {"call_index": len(observed) + 1,
                "serialized_input_bytes": size, "local_boundary_passed": True,
                "provider_api_invoked": True,
                "network_forwarding": "UNOBSERVED", "completed": False}
        observed.append(item)
        result = await original(input, tools, tool_choice, config)
        item["completed"] = True
        return result
    model.api.generate = bounded
    return observed


def verify_model_boundary(log: Any, observed: list[dict], plan: Ap2LivePlan) -> None:
    config = log.eval.model_generate_config
    calls = [x for x in observed if x["provider_api_invoked"]]
    events = [e for e in log.samples[0].events if e.event == "model"] if log.samples else []
    if (log.eval.model != f"openrouter/{plan.model_id}" or config is None
            or config.reasoning_effort != "high" or config.reasoning_history != "none"
            or config.max_retries != 0 or config.max_tokens != plan.max_output_tokens
            or len(events) != len(calls) or len(calls) > plan.max_calls
            or any(not item["completed"] for item in calls)):
        raise RemoteBoundaryError("saved AP2 LIVE model/config differs from forwarded calls")
    for event, actual in zip(events, calls, strict=True):
        strict_tool_schemas(event.tools)
        if (event.model != f"openrouter/{plan.model_id}" or event.error
                or event.cache is not None or event.retries not in (None, 0)
                or _safe_model_input_size(event.input, event.tools)
                != actual["serialized_input_bytes"]
                or actual["serialized_input_bytes"] > plan.max_input_bytes):
            raise RemoteBoundaryError("saved AP2 LIVE model event differs from boundary")


def strict_tool_schemas(tools: Any) -> None:
    """Reject non-strict object schemas before forwarding to OpenRouter/OpenAI."""
    def check(node: Any) -> None:
        if not isinstance(node, dict):
            raise RemoteBoundaryError("model tool schema is not an object")
        properties = node.get("properties")
        if node.get("type") == "object" or properties is not None:
            if (not isinstance(properties, dict)
                    or node.get("additionalProperties") is not False
                    or set(node.get("required") or []) != set(properties)):
                raise RemoteBoundaryError("model tool object schema is not strict")
            for child in properties.values():
                check(child)
        if isinstance(node.get("items"), dict):
            check(node["items"])
        for choice in node.get("anyOf") or []:
            check(choice)
    for tool in tools:
        value = tool.model_dump(mode="json") if hasattr(tool, "model_dump") else tool
        if not isinstance(value, dict) or not isinstance(value.get("parameters"), dict):
            raise RemoteBoundaryError("model tool definition is malformed")
        check(value["parameters"])


def _enabled() -> None:
    if (os.environ.get("ALLOW_EXTERNAL_MODEL_CALLS", "false").lower() != "true"
            or Decimal(os.environ.get("MAX_REAL_SPEND", "0")) != Decimal("50")
            or not os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("ALLOW_TESTNET", "false").lower() == "true"
            or os.environ.get("ALLOW_MAINNET", "false").lower() == "true"):
        raise RemoteBoundaryError("explicit approved USD50 model settings required")


def execute_one(plan: Ap2LivePlan = Ap2LivePlan()) -> dict:
    """Execute at most one frozen row; preserve and hard-stop every failure."""
    preview = preflight(plan)
    _enabled()
    from scripts.freeze_ap2_live import ASSIGNMENT
    from scripts.collect_ap2_live import verify_episode
    frozen, assignment_sha, rows = plan.validate()
    row = rows[preview["next_index"]]
    fixture, artifact = invoice_case(row.truth)
    auth_info = frozen["authorization_records"][row.episode_id]
    auth_path = ASSIGNMENT / auth_info["path"]
    validate_ap2_authorization(
        auth_path, obligation_id=row.obligation_id,
        artifact_digest=artifact.digest(),
        issuer_public_sha256=auth_info["trusted_issuer_public_sha256"])
    directory = plan.runs_dir / "episodes" / row.episode_id
    directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.mkdir(mode=0o700)
    ledger = BudgetLedger(plan.ledger_path)
    ident = _run_id(assignment_sha, row.episode_id)
    reserved = settled = False
    observed: list[dict] = []
    inspect_path = directory / "inspect.eval"
    try:
        prices, reserve, _ = fresh_budget(plan, frozen, preview["remaining_rows"])
        after = ledger.reserve(ident, reserve, Decimal("50"),
                               metadata={"model_id": plan.model_id,
                                         "episode_id": row.episode_id,
                                         "assignment_sha": assignment_sha})
        reserved = True
        if (Decimal(after["available_usd"])
                < reserve * (preview["remaining_rows"] - 1) + CONTINGENCY_USD):
            raise RemoteBoundaryError("concurrent ledger use consumed full-block headroom")
        purchase_dir = directory / "audit-purchase"
        with NativeAuditPurchase(
            purchase_dir, auth_path, obligation_id=row.obligation_id,
            artifact_digest=artifact.digest(),
            issuer_public_sha256=auth_info["trusted_issuer_public_sha256"],
        ) as purchase:
            purchase_receipt = purchase.buy()
        purchase_verified = verify_native_audit_purchase(
            purchase_dir, auth_path, expected_obligation_id=row.obligation_id,
            expected_artifact_digest=artifact.digest(),
            expected_issuer_public_sha256=auth_info["trusted_issuer_public_sha256"])
        if purchase_verified["status"] != "PASS":
            raise RemoteBoundaryError("independent native audit purchase verifier failed")
        with Open005NativeController(
            row.native_row(), fixture, artifact, directory / "erc8183",
        ) as native:
            task = ap2_live_invoice_orbit(
                row, purchase_receipt=purchase_receipt,
                native_fund=native.fund_side_term,
                native_settle=native.settle_downstream,
                model_behavior_tier="REAL_LLM_REMOTE_APPROVED")
            before_usage = account_usage_usd()
            config = GenerateConfig(
                reasoning_effort="high", reasoning_history="none",
                max_tokens=plan.max_output_tokens, max_retries=0,
                timeout=REQUEST_TIMEOUT_SECONDS, max_connections=1, cache=False)
            model = get_model(
                f"openrouter/{plan.model_id}", config=config, memoize=False,
                base_url="https://openrouter.ai/api/v1", max_retries=0,
                stream=False, responses_api=False)
            observed = guard_api(model, plan)
            [log] = inspect_eval(
                task, model=model, sample_id=row.episode_id,
                max_samples=1, max_tasks=1, epochs=1, retry_on_error=0,
                fail_on_error=True, time_limit=240, token_limit=90_000,
                message_limit=80, turn_limit=plan.max_calls,
                log_dir=str(directory / "inspect_work"), log_format="eval",
                log_model_api=False, display="none", log_level="error")
            if not log.location:
                raise RemoteBoundaryError("saved Inspect log location is missing")
            source = Path(log.location)
            assert_no_key(source)
            shutil.copyfile(source, inspect_path)
            os.chmod(inspect_path, 0o600)
            if file_sha(source) != file_sha(inspect_path):
                raise RemoteBoundaryError("saved Inspect copy differs")
            saved = read_eval_log(str(inspect_path), resolve_attachments=True)
            if log.status != "success" or saved.status != "success":
                raise RemoteBoundaryError("Inspect row did not complete successfully")
            cost = max(estimate_usage(prices, _usage_for(log, plan.model_id),
                                      calls=sum(x["provider_api_invoked"] for x in observed)),
                       account_usage_delta_usd(before_usage, account_usage_usd()))
            if cost > reserve:
                raise RemoteBoundaryError("model usage exceeds reserved bound")
            ledger.settle(ident, cost, "sha256:" + file_sha(inspect_path))
            settled = True
            verify_model_boundary(saved, observed, plan)
        if not saved.samples or len(saved.samples) != 1:
            raise RemoteBoundaryError("saved Inspect sample count differs")
        score = saved.samples[0].scores["ap2_live_score"].metadata
        if score["requested_verdict"] in {"ACCEPT", "REJECT"}:
            native_result = verify_open005_native_evidence(directory / "erc8183")
            if native_result["verdict"] != score["dispatched_verdict"]:
                raise RemoteBoundaryError("official native consequence differs from application dispatch")
            status = "COMPLETE"
        else:
            prefix = verify_open005_funded_evidence(directory / "erc8183")
            if (prefix["status"] != "FUNDED_SUBMITTED_VERIFIED"
                    or prefix["terminal_settlement"] is not False):
                raise RemoteBoundaryError("no-verdict native prefix is not independently verified")
            status = "OBSERVED_INCOMPLETE"
        plan.validate()  # Source/assignment drift after the model is a hard stop.
        record = {"schema": "ap2-live-paid-episode-v1", "status": status,
                  "episode_id": row.episode_id,
                  "assignment_manifest_sha256": assignment_sha,
                  "model_id": plan.model_id, "reasoning_effort": "high",
                  "reasoning_history": "none", "model_tier": "REAL_LLM_REMOTE_APPROVED",
                  "transaction_tier": "NATIVE_LOCAL_PROTOCOL",
                  "ap2_payment_execution": "NONE",
                  "audit_purchase_execution": "APPLICATION_LOCAL_ERC20",
                  "ledger_run_id": ident, "model_cost_usd": str(cost),
                  "request_boundary": observed,
                  "inspect_sha256": file_sha(inspect_path),
                  "native_purchase_sha256": file_sha(
                      directory / "audit-purchase/native-audit-purchase.json"),
                  "native_erc8183_sha256": file_sha(
                      directory / "erc8183/native-evidence.json")}
        write_json(directory / "episode_record.json", record)
        return verify_episode(row, directory, frozen=frozen,
                              assignment_sha=assignment_sha, ledger=ledger.snapshot())
    except BaseException as exc:
        quarantine_unverified_record(directory)
        forwarded = any(x["provider_api_invoked"] for x in observed)
        if reserved and not settled and forwarded:
            try:
                ledger.mark_unknown(ident, type(exc).__name__)
            except Exception:
                pass
        partial = []
        for path in sorted(directory.rglob("*")):
            if path.is_file() and not path.is_symlink():
                try:
                    assert_no_key(path)
                    partial.append({"path": str(path.relative_to(directory)),
                                    "sha256": file_sha(path)})
                except RemoteBoundaryError:
                    path.unlink()
        stopped = {"schema": "ap2-live-stopped-v1", "episode_id": row.episode_id,
                   "assignment_manifest_sha256": assignment_sha,
                   "error_type": type(exc).__name__,
                   "model_request_boundary": observed,
                   "provider_api_invoked": forwarded,
                   "network_forwarding": "UNOBSERVED" if forwarded else "NO_API_INVOCATION",
                   "billing_state": "SETTLED" if settled else
                        "UNKNOWN" if forwarded else "ZERO_REQUESTS_PROVEN",
                   "partial_artifacts": partial,
                   "no_retry_or_substitution": True,
                   "complete_dual_payment_claim": False,
                   "ledger_run_id": ident}
        write_json(directory / "STOPPED.json", stopped)
        if reserved and not settled and not forwarded:
            ledger.settle(ident, Decimal("0"), "sha256:" + file_sha(directory / "STOPPED.json"))
        raise
