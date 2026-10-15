"""Fail-stop one-row ORBIT/Inspect runner for the frozen ERC-8183 fee study.

Import and preflight are read-only. Execution requires an independently saved
freeze, the project USD50 ledger, explicit model-call environment, and exact
cross-vendor role routing. No remote call is made by this module at import.
"""

from __future__ import annotations

from collections import Counter
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
from inspect_ai.model._openai import openai_chat_tools
from orbit.communication import current_identity

from .erc8183_fee_native import FeeNativeController
from .erc8183_fee_native_verifier import verify_file as verify_native_file
from .erc8183_fee_clearance import sealed_mpp009_disposition
from .erc8183_fee_plan import (AUDITOR_CALLS, CANONICAL_LEDGER, CONTINGENCY_USD,
    MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS, PROVIDER_CALLS, ROWS, SOL, SONNET,
    UNASSIGNED_RESIDUAL_USD, per_row_reserve)
from .erc8183_fee_task import erc8183_fee_invoice_orbit
from .mpp005_boundary import (RemoteBoundaryError, _safe_model_input_size,
    account_usage_delta_usd, account_usage_usd, assert_no_key, file_sha,
    write_json)
from .mpp008_budget import mpp006_contingent_exposure
from .mpp008_pricing import estimate_model_usage, pricing_snapshots
from .remote_budget import BudgetLedger


ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "artifacts/gates/ERC8183_FEE010/runs-001"
ROLE_LIMITS = {"provider": PROVIDER_CALLS, "auditor": AUDITOR_CALLS}


def _canonical_root() -> None:
    if ROOT.resolve() != CANONICAL_LEDGER.parents[2].resolve():
        raise RemoteBoundaryError("fee paid runner must run in canonical shared-ledger checkout")


def run_id(assignment_sha: str, episode_id: str) -> str:
    return f"fee010-{assignment_sha[:12]}-{episode_id}"


@dataclass(frozen=True)
class FeeLivePlan:
    ledger_path: Path = CANONICAL_LEDGER
    runs_dir: Path = RUNS

    def validate(self):
        _canonical_root()
        from scripts.freeze_erc8183_fee import verify
        from scripts.verify_erc8183_fee_readiness import installed_runtime_versions
        installed_runtime_versions()
        if (self.ledger_path.resolve() != CANONICAL_LEDGER.resolve()
                or self.runs_dir.resolve() != RUNS.resolve()):
            raise RemoteBoundaryError("fee study must use frozen paths and canonical USD50 ledger")
        return verify()


def required_headroom(per_row: Decimal, count: int) -> Decimal:
    if type(count) is not int or not 0 <= count <= ROWS:
        raise ValueError("remaining fee study count differs")
    return count * per_row + CONTINGENCY_USD + UNASSIGNED_RESIDUAL_USD


def fresh_budget(frozen: dict, remaining: int) -> tuple[dict, Decimal, dict]:
    state = BudgetLedger(CANONICAL_LEDGER).snapshot()
    if (state["cap_usd"] != "50" or state["blocked"] or state["unknown_run_ids"]
            or state["reserved_usd"] != "6.30784"):
        raise RemoteBoundaryError("shared USD50 ledger blocked or concurrently reserved")
    mpp006_contingent_exposure(state)
    if sealed_mpp009_disposition(state) != frozen["mpp009_predecessor_disposition"]:
        raise RemoteBoundaryError("sealed MPP009 predecessor differs")
    prices = pricing_snapshots()
    if {k: v["catalog_model_sha256"] for k, v in prices.items()} != {
            k: v["catalog_model_sha256"] for k, v in frozen["public_pricing_snapshot"].items()}:
        raise RemoteBoundaryError("frozen public model catalog changed")
    reserve = max(Decimal(frozen["budget_at_freeze"]["per_row_worst_case_usd"]),
                  per_row_reserve(prices))
    if required_headroom(reserve, remaining) > Decimal(state["available_usd"]):
        raise RemoteBoundaryError("remaining fee rows plus contingency exceed USD50 headroom")
    return prices, reserve, state


def _post_reserve(state: dict, reserve: Decimal, ident: str, remaining: int) -> None:
    if (state["cap_usd"] != "50" or state["blocked"] or state["unknown_run_ids"]
            or Decimal(state["reserved_usd"]) != Decimal("6.30784") + reserve
            or state["runs"].get(ident, {}).get("status") != "RESERVED"):
        raise RemoteBoundaryError("fee row reservation or shared hold differs")
    mpp006_contingent_exposure(state, additional_reservation_usd=reserve)
    if required_headroom(reserve, remaining) > Decimal(state["available_usd"]):
        raise RemoteBoundaryError("concurrent spending consumed fee block headroom")


def _post_settle(ledger: BudgetLedger, reserve: Decimal, remaining: int) -> None:
    state = ledger.snapshot()
    if (state["cap_usd"] != "50" or state["blocked"] or state["unknown_run_ids"]
            or state["reserved_usd"] != "6.30784"):
        raise RemoteBoundaryError("shared USD50 ledger blocked after fee row")
    mpp006_contingent_exposure(state)
    if required_headroom(reserve, remaining) > Decimal(state["available_usd"]):
        raise RemoteBoundaryError("settled fee row leaves insufficient block headroom")


def preflight(plan: FeeLivePlan = FeeLivePlan()) -> dict:
    _canonical_root()
    from scripts.collect_erc8183_fee import verify_episode
    frozen, assignment_sha, rows = plan.validate()
    ledger = BudgetLedger(plan.ledger_path).snapshot()
    next_index = None
    for index, row in enumerate(rows):
        directory = plan.runs_dir / "episodes" / row.episode_id
        if (directory / "STOPPED.json").exists():
            raise RemoteBoundaryError("earlier fee row stopped; no retry or later calls")
        if (directory / "episode_record.json").is_file():
            if next_index is not None:
                raise RemoteBoundaryError("completed fee row after execution gap")
            verify_episode(row, directory, assignment_sha=assignment_sha, ledger=ledger)
        elif directory.exists():
            raise RemoteBoundaryError("partial assigned fee row exists; no retry")
        elif next_index is None:
            next_index = index
    if next_index is None:
        raise RemoteBoundaryError("all assigned fee rows attempted")
    row = rows[next_index]
    ident = run_id(assignment_sha, row.episode_id)
    if ident in ledger["runs"]:
        raise RemoteBoundaryError("assigned fee row ledger ID already exists")
    _, reserve, state = fresh_budget(frozen, len(rows) - next_index)
    return {"status": "PREFLIGHT_PASS_NO_CALL", "next_episode_id": row.episode_id,
            "next_index": next_index, "assignment_manifest_sha256": assignment_sha,
            "per_row_reserve_usd": str(reserve),
            "full_remaining_headroom_usd": str(required_headroom(reserve, len(rows) - next_index)),
            "ledger_available_usd": state["available_usd"], "ledger_seq": state["seq"],
            "reasoning_effort_by_role": {"provider": "high", "auditor": "high"},
            "role_models": {"provider": SOL, "auditor": SONNET}}


def _enabled() -> None:
    if (os.environ.get("ALLOW_EXTERNAL_MODEL_CALLS", "false").lower() != "true"
            or Decimal(os.environ.get("MAX_REAL_SPEND", "0")) != Decimal("50")
            or not os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("ALLOW_TESTNET", "false").lower() == "true"
            or os.environ.get("ALLOW_MAINNET", "false").lower() == "true"):
        raise RemoteBoundaryError("explicit approved USD50 local-only model settings required")


def _models(row) -> dict[str, Any]:
    config = GenerateConfig(reasoning_effort="high", reasoning_history="none",
                            max_tokens=MAX_OUTPUT_TOKENS, max_retries=0,
                            timeout=180, max_connections=1, cache=False)
    models = {}
    for role, model_id in (("provider", row.provider_model_id),
                           ("auditor", row.auditor_model_id)):
        model = get_model("openrouter/" + model_id)
        if type(model.api).__name__ != "OpenRouterAPI" or str(model) != "openrouter/" + model_id:
            raise RemoteBoundaryError("explicit role model is not native OpenRouter")
        model.api.client.max_retries = 0
        model.config = config.model_copy(deep=True)
        if get_model("openrouter/" + model_id) is not model or model.api.client.max_retries != 0:
            raise RemoteBoundaryError("ORBIT role model is not the bounded cached route")
        models[role] = model
    return models


def _strict_tools(tools: Any, role: str, contact: str, *, api: Any = None) -> str:
    allowed = ({"acknowledge_frozen_invoice"} if role == "provider" else
               {"view_frozen_invoice", "buy_independent_invoice_check",
                "issue_fee_invoice_verdict"})
    if contact == "CHANNEL":
        allowed |= {"channel_post", "channel_read", "channel_list"}
    expected_fields = {
        "acknowledge_frozen_invoice": {}, "view_frozen_invoice": {},
        "buy_independent_invoice_check": {"request_id": "string"},
        "issue_fee_invoice_verdict": {"verdict": "string", "check_request_id": "string"},
        "channel_post": {"channel_id": "string", "message": "string"},
        "channel_read": {"channel_id": "string", "after_sequence": "integer|null",
                         "limit": "integer|null"},
        "channel_list": {"after_channel_id": "null|string"},
    }
    if api is None:
        serialized = openai_chat_tools(tools, exclude={
            "maxLength", "pattern", "minLength", "examples", "minimum", "maximum"})
        for entry in serialized:
            entry["function"]["strict"] = True
    else:
        serialized = api.tools_to_openai(tools)
    names = set()
    for entry in serialized:
        fn = entry.get("function")
        if entry.get("type") != "function" or not isinstance(fn, dict):
            raise RemoteBoundaryError("fee role has malformed tool schema")
        name, schema = fn.get("name"), fn.get("parameters")
        if (name not in allowed or name in names or fn.get("strict") is not True
                or not isinstance(schema, dict)
                or schema.get("type") != "object"
                or schema.get("additionalProperties") is not False
                or not isinstance(schema.get("properties"), dict)
                or not isinstance(schema.get("required"), list)
                or len(schema["required"]) != len(set(schema["required"]))
                or set(schema["required"]) != set(schema["properties"])):
            raise RemoteBoundaryError("fee role has non-strict or unapproved tool")
        fields = {}
        for field, definition in schema["properties"].items():
            if not isinstance(definition, dict) or "default" in definition:
                raise RemoteBoundaryError("fee role tool argument schema differs")
            if "anyOf" in definition:
                alternatives = definition["anyOf"]
                if (not isinstance(alternatives, list) or
                        any(not isinstance(x, dict) for x in alternatives)):
                    raise RemoteBoundaryError("fee role nullable argument schema differs")
                fields[field] = "|".join(sorted(x.get("type", "") for x in alternatives))
            else:
                fields[field] = definition.get("type")
        if fields != expected_fields[name]:
            raise RemoteBoundaryError("fee role tool argument set/type changed")
        names.add(name)
    if names != allowed:
        raise RemoteBoundaryError("fee role offered tool set differs")
    return json.dumps(serialized, sort_keys=True, separators=(",", ":"))


def guard_model_apis(models: dict[str, Any], row) -> list[dict]:
    observed: list[dict] = []
    expected = {"provider": "openrouter/" + row.provider_model_id,
                "auditor": "openrouter/" + row.auditor_model_id}
    for role, model in models.items():
        original = model.api.generate

        async def bounded(input, tools, tool_choice, config, *, _original=original,
                          _model=model, _role=role):
            identity = current_identity()
            actor = identity.agent_id if identity is not None else None
            size = _safe_model_input_size(input, tools)
            tool_schema = _strict_tools(tools, actor, row.contact, api=_model.api)
            reasoning = any(isinstance(part, ContentReasoning) for message in input
                            for part in (message.content if isinstance(message.content, list) else []))
            if (actor != _role or str(_model) != expected[actor]
                    or len(observed) >= PROVIDER_CALLS + AUDITOR_CALLS
                    or sum(item["role"] == actor for item in observed) >= ROLE_LIMITS[actor]
                    or size > MAX_INPUT_BYTES or reasoning
                    or _model.api.client.max_retries != 0
                    or config.reasoning_effort != "high" or config.reasoning_history != "none"
                    or config.max_tokens != MAX_OUTPUT_TOKENS or config.max_retries != 0):
                raise RemoteBoundaryError("fee role request exceeds assignment boundary")
            item = {"call_index": len(observed) + 1, "role": actor, "model": expected[actor],
                    "serialized_input_bytes": size,
                    "tool_schema_sha256": sha256(tool_schema.encode()).hexdigest(),
                    "provider_api_invoked": True, "network_forwarding": "UNOBSERVED",
                    "http_client_max_retries": 0, "completed": False}
            observed.append(item)
            result = await _original(input, tools, tool_choice, config)
            item["completed"] = True
            return result
        model.api.generate = bounded
    return observed


def verify_boundary(log: Any, observed: list[dict], row) -> dict:
    from scripts.collect_erc8183_fee import actor_for_event
    if log.status != "success" or len(log.samples or []) != 1:
        raise RemoteBoundaryError("fee Inspect log is not a successful one-row archive")
    sample = log.samples[0]
    expected = {"provider": "openrouter/" + row.provider_model_id,
                "auditor": "openrouter/" + row.auditor_model_id}
    agents = sample.metadata["experiment"]["setup"]["agents"]
    if {a["name"]: a["model"] for a in agents} != expected:
        raise RemoteBoundaryError("raw ORBIT role models differ")
    events = [e for e in sample.events if e.event == "model"]
    if len(events) != len(observed) or not events:
        raise RemoteBoundaryError("actual forwarded requests differ from Inspect log")
    counts = Counter()
    for index, (event, actual) in enumerate(zip(events, observed, strict=True)):
        role = actor_for_event(event, sample.events)
        counts[role] += 1
        schema = _strict_tools(event.tools, role, row.contact)
        expected_item = {"call_index": index + 1, "role": role,
                         "model": expected[role],
                         "serialized_input_bytes": _safe_model_input_size(event.input, event.tools),
                         "tool_schema_sha256": sha256(schema.encode()).hexdigest(),
                         "provider_api_invoked": True, "network_forwarding": "UNOBSERVED",
                         "http_client_max_retries": 0, "completed": True}
        config = event.config
        if (actual != expected_item or counts[role] > ROLE_LIMITS[role]
                or actual["serialized_input_bytes"] > MAX_INPUT_BYTES
                or event.model != expected[role] or event.error or event.cache is not None
                or event.retries not in (None, 0) or config is None
                or config.reasoning_effort != "high" or config.reasoning_history != "none"
                or config.max_tokens != MAX_OUTPUT_TOKENS or config.max_retries != 0):
            raise RemoteBoundaryError("raw model event violates assigned role/limit")
    if set(counts) != {"provider", "auditor"}:
        raise RemoteBoundaryError("both role agents must have live model events")
    return {"provider_calls": counts["provider"], "auditor_calls": counts["auditor"],
            "reasoning_effort_by_role": {"provider": "high", "auditor": "high"}}


def _usage_estimate(log: Any, prices: dict, observed: list[dict]) -> Decimal:
    usage = log.samples[0].model_usage
    counts = Counter(item["model"].removeprefix("openrouter/") for item in observed)
    if set(usage) != {"openrouter/" + name for name in counts}:
        raise RemoteBoundaryError("provider usage model keys differ from forwarded routes")
    return sum((estimate_model_usage(prices[name], usage["openrouter/" + name], count)
                for name, count in counts.items()), Decimal(0))


def execute_one(plan: FeeLivePlan = FeeLivePlan()) -> dict:
    _canonical_root()
    preview = preflight(plan)
    _enabled()
    from scripts.collect_erc8183_fee import verify_episode
    frozen, assignment_sha, rows = plan.validate()
    row = rows[preview["next_index"]]
    directory = plan.runs_dir / "episodes" / row.episode_id
    directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.mkdir(mode=0o700)
    ledger = BudgetLedger(plan.ledger_path)
    ident = run_id(assignment_sha, row.episode_id)
    observed: list[dict] = []
    reserved = settled = False
    try:
        prices, reserve, _ = fresh_budget(frozen, ROWS - preview["next_index"])
        state = ledger.reserve(ident, reserve, Decimal("50"), metadata={
            "provider_model_id": row.provider_model_id,
            "auditor_model_id": row.auditor_model_id,
            "episode_id": row.episode_id, "assignment_sha": assignment_sha})
        reserved = True
        _post_reserve(state, reserve, ident, ROWS - preview["next_index"] - 1)
        with FeeNativeController(row, directory / "erc8183") as native:
            task = erc8183_fee_invoice_orbit(row, native_prefix=native.public_prefix(),
                native_check=native.buy_check, native_settle=native.settle,
                model_behavior_tier="REAL_LLM_REMOTE_APPROVED")
            before = account_usage_usd()
            models = _models(row)
            observed = guard_model_apis(models, row)
            logs = inspect_eval(task, model=models["provider"], sample_id=row.episode_id,
                max_samples=1, max_tasks=1, epochs=1, retry_on_error=0,
                fail_on_error=True, time_limit=240, token_limit=50_000,
                message_limit=80, turn_limit=PROVIDER_CALLS + AUDITOR_CALLS,
                log_dir=str(directory / "inspect_work"), log_format="eval",
                log_model_api=False, display="none", log_level="error")
            if len(logs) != 1 or not logs[0].location:
                raise RemoteBoundaryError("one saved fee Inspect log required")
            raw = Path(logs[0].location)
            assert_no_key(raw)
            target = directory / "inspect.eval"
            shutil.copyfile(raw, target)
            os.chmod(target, 0o600)
            if file_sha(raw) != file_sha(target):
                raise RemoteBoundaryError("Inspect archive copy changed")
            saved = read_eval_log(str(target), resolve_attachments=True)
            estimate = _usage_estimate(saved, prices, observed)
            delta = account_usage_delta_usd(before, account_usage_usd())
            cost = max(estimate, delta)
            if cost > reserve:
                raise RemoteBoundaryError("observed fee model cost exceeds reservation")
            ledger.settle(ident, cost, "sha256:" + file_sha(target))
            settled = True
            _post_settle(ledger, reserve, ROWS - preview["next_index"] - 1)
            boundary = verify_boundary(saved, observed, row)
        native_path = directory / "erc8183" / (
            "native-evidence.json" if native.verdict else "native-partial.json")
        native_result = verify_native_file(native_path, row)
        status = "COMPLETE" if native.verdict else "OBSERVED_INCOMPLETE"
        plan.validate()
        record = {"schema": "erc8183-fee-paid-episode-v1", "status": status,
                  "episode_id": row.episode_id, "assignment_manifest_sha256": assignment_sha,
                  "provider_model_id": row.provider_model_id,
                  "auditor_model_id": row.auditor_model_id,
                  "model_tier": "REAL_LLM_REMOTE_APPROVED",
                  "payment_tier": "NATIVE_LOCAL_PROTOCOL",
                  "reasoning_effort_by_role": {"provider": "high", "auditor": "high"},
                  "ledger_run_id": ident, "model_cost_usd": str(cost),
                  "model_request_boundary": observed, "raw_model_boundary": boundary,
                  "inspect_sha256": file_sha(target),
                  "native_path": str(native_path.relative_to(directory)),
                  "native_sha256": file_sha(native_path), "native_status": native_result["status"],
                  "usage_estimate_usd": str(estimate), "account_usage_delta_usd": str(delta),
                  "fresh_public_pricing_snapshots": prices}
        write_json(directory / "episode_record.json", record)
        return verify_episode(row, directory, assignment_sha=assignment_sha,
                              ledger=ledger.snapshot())
    except BaseException as exc:
        if (directory / "episode_record.json").exists():
            (directory / "episode_record.json").rename(directory / "unverified_episode_record.json")
        unknown = False
        if reserved and not settled:
            try:
                ledger.mark_unknown(ident, type(exc).__name__)
                unknown = True
            except Exception:
                pass
        partial = []
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                assert_no_key(path)
                partial.append({"path": str(path.relative_to(directory)),
                                "sha256": file_sha(path)})
            except RemoteBoundaryError:
                path.unlink()
        write_json(directory / "STOPPED.json", {
            "schema": "erc8183-fee-stopped-episode-v1", "episode_id": row.episode_id,
            "assignment_manifest_sha256": assignment_sha, "error_type": type(exc).__name__,
            "ledger_run_id": ident, "budget_state": "SETTLED" if settled else
                "UNKNOWN" if unknown else "UNRESOLVED" if reserved else "UNRESERVED",
            "model_request_boundary": observed, "partial_artifacts": partial,
            "no_retry_or_substitution": True, "complete_native_claim": False})
        raise
