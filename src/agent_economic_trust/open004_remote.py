"""Guarded OPEN004 remote runner. Each invocation can run one frozen episode."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import socket
import zipfile
from typing import Any

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log
from inspect_ai.model import ContentReasoning, GenerateConfig, get_model

from .open004_plan import (EVAL_TOKEN_LIMIT, MAX_CALLS_PER_EPISODE, MAX_INPUT_BYTES,
    MAX_OUTPUT_TOKENS, MODEL_ID, SCHEDULER_SECONDS, TASK_TOKEN_LIMIT, canonical)
from .remote import (PROJECT_LEDGER_PATH, REQUEST_TIMEOUT_SECONDS, RemoteBoundaryError,
    _safe_model_input_size, _usage_for, account_usage_delta_usd, account_usage_usd)
from .remote_budget import BudgetLedger
from .remote_pricing import estimate_usage, pricing_snapshot, reserve_worst_case

ROOT = Path(__file__).resolve().parents[2]
ASSIGNMENT_DIR = ROOT / "artifacts/gates/OPEN004/assignment-invoice-001"
RUNS_DIR = ROOT / "artifacts/gates/OPEN004/runs-invoice-001"


def file_sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("evidence must be a regular file")
    return sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    raw = canonical(value) + b"\n"
    secret = os.environ.get("OPENROUTER_API_KEY", "")
    if secret and secret.encode() in raw:
        raise RemoteBoundaryError("credential detected in saved record")
    with path.open("xb") as f:
        os.chmod(path, 0o600)
        f.write(raw)


def assert_no_key(path: Path) -> None:
    """Inspect every decompressed member as well as raw container bytes."""
    secret = os.environ.get("OPENROUTER_API_KEY", "")
    if not secret:
        return
    needle = secret.encode()
    if needle in path.read_bytes():
        raise RemoteBoundaryError("credential detected in evidence")
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            if any(needle in z.read(name) for name in z.namelist()):
                raise RemoteBoundaryError("credential detected inside Inspect archive")


def run_id(assignment_sha: str, episode_id: str) -> str:
    return f"open004-{assignment_sha[:12]}-{episode_id}"


@dataclass(frozen=True)
class Open004Plan:
    assignment_dir: Path = ASSIGNMENT_DIR
    runs_dir: Path = RUNS_DIR
    ledger_path: Path = PROJECT_LEDGER_PATH
    model_id: str = MODEL_ID
    max_calls: int = MAX_CALLS_PER_EPISODE
    max_input_bytes: int = MAX_INPUT_BYTES
    max_output_tokens: int = MAX_OUTPUT_TOKENS

    def validate(self) -> tuple:
        from scripts import freeze_open004 as freezer
        if (self.assignment_dir.resolve() != ASSIGNMENT_DIR.resolve()
                or self.runs_dir.resolve() != RUNS_DIR.resolve()
                or self.ledger_path.resolve() != PROJECT_LEDGER_PATH.resolve()
                or self.model_id != MODEL_ID or self.max_calls != MAX_CALLS_PER_EPISODE
                or self.max_input_bytes != MAX_INPUT_BYTES
                or self.max_output_tokens != MAX_OUTPUT_TOKENS):
            raise RemoteBoundaryError("runner differs from canonical OPEN004 freeze")
        freezer.verify()
        return freezer.load_assignment(self.assignment_dir)


def fresh_budget(plan: Open004Plan, frozen: dict, remaining: int) -> tuple[dict, Decimal, dict]:
    from scripts import freeze_open004 as freezer
    freezer.verify()
    state = BudgetLedger(plan.ledger_path).snapshot()
    if state["blocked"] or state["unknown_run_ids"] or state["cap_usd"] != "50":
        raise RemoteBoundaryError("lifetime USD50 ledger blocked")
    rates = pricing_snapshot(plan.model_id)
    reserve = max(Decimal(frozen["worst_case_reserve_usd_per_episode"]),
                  reserve_worst_case(rates, plan.max_calls, plan.max_input_bytes, plan.max_output_tokens))
    if reserve * remaining + Decimal(frozen["contingency_reserve_usd"]) > Decimal(state["available_usd"]):
        raise RemoteBoundaryError("full remaining OPEN004 reserve exceeds USD50 headroom")
    return rates, reserve, state


def preflight(plan: Open004Plan = Open004Plan()) -> dict:
    from .open004_reporting import verify_episode
    frozen, assignment_sha, rows = plan.validate()
    by_id = {r.episode_id: r for r in rows}
    if len(by_id) != len(rows) or set(by_id) != set(frozen["execution_order"]):
        raise RemoteBoundaryError("frozen execution order differs")
    ledger = BudgetLedger(plan.ledger_path).snapshot()
    next_index = None
    for index, episode_id in enumerate(frozen["execution_order"]):
        row = by_id[episode_id]
        directory = plan.runs_dir / "episodes" / episode_id
        if (directory / "STOPPED.json").exists():
            raise RemoteBoundaryError("earlier episode stopped; no later calls or retry")
        if (directory / "episode_record.json").is_file():
            if next_index is not None:
                raise RemoteBoundaryError("completed row after gap in frozen order")
            verify_episode(row, directory, assignment_sha=assignment_sha, ledger=ledger)
        elif directory.exists():
            raise RemoteBoundaryError("partial assigned episode; no retry")
        elif next_index is None:
            next_index = index
    if next_index is None:
        raise RemoteBoundaryError("all assigned OPEN004 episodes already attempted")
    row = by_id[frozen["execution_order"][next_index]]
    if run_id(assignment_sha, row.episode_id) in ledger["runs"]:
        raise RemoteBoundaryError("episode ledger run already exists")
    rates, reserve, state = fresh_budget(plan, frozen, len(rows) - next_index)
    return {"mode": "dry-run", "ready_to_execute": True,
            "next_episode_id": row.episode_id, "next_arm": row.arm,
            "next_index": next_index, "remaining_episodes": len(rows) - next_index,
            "assignment_manifest_sha256": assignment_sha,
            "next_reservation_usd": str(reserve),
            "full_remaining_reservation_usd": str(reserve * (len(rows) - next_index)),
            "available_usd": state["available_usd"], "fresh_public_pricing": rates,
            "contingency_reserve_usd": frozen["contingency_reserve_usd"],
            "remaining_003_obligation_reserve_usd": "0",
            "model_id": plan.model_id, "reasoning_effort": "high", "max_retries": 0,
            "max_calls": plan.max_calls, "max_input_bytes": plan.max_input_bytes,
            "max_output_tokens": plan.max_output_tokens}


def guard_api(model: Any, plan: Open004Plan) -> list[dict]:
    """Enforce controls on each actual forwarded API input."""
    observed: list[dict] = []
    original = model.api.generate

    async def bounded(input: Any, tools: Any, tool_choice: Any, config: Any) -> Any:
        size = _safe_model_input_size(input, tools)
        reasoning = any(isinstance(part, ContentReasoning)
                        for m in input for part in (m.content if isinstance(m.content, list) else []))
        if (len(observed) >= plan.max_calls or size > plan.max_input_bytes or reasoning
                or config.reasoning_effort != "high" or config.reasoning_history != "none"
                or config.max_tokens != plan.max_output_tokens or config.max_retries != 0):
            raise RemoteBoundaryError("OPEN004 actual provider input exceeded frozen controls")
        item = {"call_index": len(observed) + 1, "serialized_input_bytes": size,
                "provider_api_invoked": True, "network_forwarding": "UNOBSERVED", "completed": False}
        observed.append(item)
        result = await original(input, tools, tool_choice, config)
        item["completed"] = True
        return result
    model.api.generate = bounded
    return observed


def verify_model_boundary(log: Any, observed: list[dict], plan: Open004Plan) -> None:
    config = log.eval.model_generate_config
    if (log.eval.model != f"openrouter/{plan.model_id}" or config is None
            or config.reasoning_effort != "high" or config.reasoning_history != "none"
            or config.max_retries != 0 or config.max_tokens != plan.max_output_tokens
            or not log.samples or len(log.samples) != 1):
        raise RemoteBoundaryError("saved Inspect model/config differs")
    events = [e for e in log.samples[0].events if e.event == "model"]
    if not events or len(events) != len(observed) or len(events) > plan.max_calls:
        raise RemoteBoundaryError("saved model events differ from actual calls")
    for index, (event, actual) in enumerate(zip(events, observed, strict=True)):
        c = event.config
        if (event.model != f"openrouter/{plan.model_id}" or event.error or event.cache is not None
                or event.retries not in (None, 0) or c.reasoning_effort != "high"
                or c.reasoning_history != "none" or c.max_retries != 0
                or c.max_tokens != plan.max_output_tokens
                or actual != {"call_index": index + 1,
                   "serialized_input_bytes": _safe_model_input_size(event.input, event.tools),
                   "provider_api_invoked": True, "network_forwarding": "UNOBSERVED", "completed": True}
                or actual["serialized_input_bytes"] > plan.max_input_bytes
                or any(isinstance(part, ContentReasoning) for m in event.input
                       for part in (m.content if isinstance(m.content, list) else []))):
            raise RemoteBoundaryError("saved model request violates frozen boundary")


def free_x402_port() -> int:
    """Check all three ports used sequentially by the pinned local x402 runner."""
    for _ in range(50):
        sockets = []
        try:
            base = socket.socket()
            base.bind(("127.0.0.1", 0))
            port = base.getsockname()[1]
            sockets.append(base)
            if not 1024 < port < 65480:
                continue
            for offset in (10, 11):
                s = socket.socket()
                sockets.append(s)
                s.bind(("127.0.0.1", port + offset))
            return port
        except OSError:
            pass
        finally:
            for s in sockets:
                s.close()
    raise RemoteBoundaryError("no bounded local x402 port triple available")


def _execution_enabled() -> None:
    if (os.environ.get("ALLOW_EXTERNAL_MODEL_CALLS", "false").lower() != "true"
            or Decimal(os.environ.get("MAX_REAL_SPEND", "0")) != Decimal("50")
            or not os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("ALLOW_TESTNET", "false").lower() == "true"
            or os.environ.get("ALLOW_MAINNET", "false").lower() == "true"):
        raise RemoteBoundaryError("explicit remote USD50 authorization/runtime settings required")


def execute_one(plan: Open004Plan = Open004Plan()) -> dict:
    """No loop: one assigned pair, one Inspect sample, zero retries."""
    preview = preflight(plan)
    _execution_enabled()
    from .open004_native import Open004NativeController, verify_open004_native_evidence
    from .open004_task import audit_open004_log, invoice_case, open004_invoice_orbit, x402_access_callback
    from .x402_invoice_adapter import InvoiceX402Controller
    from .x402_invoice_verifier import verify_purchase
    frozen, assignment_sha, rows = plan.validate()
    row = next(r for r in rows if r.episode_id == preview["next_episode_id"])
    task_row = row.task_episode()
    fixture, artifact = invoice_case(row.truth)
    directory = plan.runs_dir / "episodes" / row.episode_id
    directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.mkdir(mode=0o700)
    ledger = BudgetLedger(plan.ledger_path)
    ident = run_id(assignment_sha, row.episode_id)
    reserved = settled = False
    observed: list[dict] = []
    try:
        x402 = InvoiceX402Controller(frozen_fixture=fixture, frozen_artifact=artifact,
            assignment_nonce=row.episode_id,
            obligation_id=row.obligation_id, output_dir=directory / "x402", port=free_x402_port())
        access = x402_access_callback(x402)
        with Open004NativeController(task_row, fixture, artifact, directory / "erc8183") as native:
            task = open004_invoice_orbit(task_row, scheduler_seconds=SCHEDULER_SECONDS,
                model_behavior_tier="REAL_LLM_REMOTE_APPROVED", access_callback=access,
                fund_callback=native.fund_side_term, settle_callback=native.settle_downstream,
                task_token_limit=TASK_TOKEN_LIMIT, model_call_limit=MAX_CALLS_PER_EPISODE)
            usage_before = account_usage_usd()
            config = GenerateConfig(reasoning_effort="high", reasoning_history="none",
                max_tokens=plan.max_output_tokens, max_retries=0, timeout=REQUEST_TIMEOUT_SECONDS,
                max_connections=1, cache=False)
            model = get_model(f"openrouter/{plan.model_id}", config=config, memoize=False,
                base_url="https://openrouter.ai/api/v1", max_retries=0,
                stream=False, responses_api=False)
            observed = guard_api(model, plan)
            prices, reserve, _ = fresh_budget(plan, frozen, preview["remaining_episodes"])
            state = ledger.reserve(ident, reserve, Decimal("50"),
                metadata={"model_id": plan.model_id, "episode_id": row.episode_id,
                          "assignment_sha": assignment_sha})
            reserved = True
            if Decimal(state["available_usd"]) < reserve * (preview["remaining_episodes"] - 1) + Decimal(frozen["contingency_reserve_usd"]):
                raise RemoteBoundaryError("concurrent spending consumed full-block reserve")
            logs = inspect_eval(task, model=model, sample_id=row.episode_id,
                max_samples=1, max_tasks=1, epochs=1, retry_on_error=0, fail_on_error=True,
                time_limit=SCHEDULER_SECONDS, token_limit=EVAL_TOKEN_LIMIT,
                message_limit=80, turn_limit=MAX_CALLS_PER_EPISODE,
                log_dir=str(directory / "inspect_work"), log_format="eval",
                log_model_api=False, display="none", log_level="error")
            if len(logs) != 1 or not logs[0].location:
                raise RemoteBoundaryError("one Inspect log required")
            target = directory / "inspect.eval"
            source = Path(logs[0].location)
            assert_no_key(source)
            shutil.copyfile(source, target)
            os.chmod(target, 0o600)
            if file_sha(source) != file_sha(target):
                raise RemoteBoundaryError("Inspect archive copy changed")
            saved = read_eval_log(str(target), resolve_attachments=True)
            cost = max(estimate_usage(prices, _usage_for(logs[0], plan.model_id), calls=len(observed)),
                       account_usage_delta_usd(usage_before, account_usage_usd()))
            if cost > reserve:
                raise RemoteBoundaryError("model usage exceeds bounded reservation")
            ledger.settle(ident, cost, "sha256:" + file_sha(target))
            settled = True
            verify_model_boundary(saved, observed, plan)
            audit_open004_log(saved, task_row, expected_model=f"openrouter/{plan.model_id}")
        score = saved.samples[0].scores["open004_score"].metadata
        if score["V"] in {"ACCEPT", "REJECT"}:
            native_result = verify_open004_native_evidence(directory / "erc8183")
            if native_result["verdict"] != score["V"] or native_result["episode_id"] != row.episode_id:
                raise RemoteBoundaryError("official ERC8183 consequence differs from saved verdict")
        else:
            from .open004_native import verify_open004_funded_evidence
            verify_open004_funded_evidence(directory / "erc8183")
        if (directory / "x402").exists():
            verify_purchase(directory / "x402", frozen_fixture=fixture, frozen_artifact=artifact)
        # Recheck source after model execution as well as before reserving.
        plan.validate()
        record = {"schema": "open004-paid-episode-v1", "status": "COMPLETE" if score["V"] in {"ACCEPT", "REJECT"} else "OBSERVED_INCOMPLETE",
            "episode_id": row.episode_id, "assignment_manifest_sha256": assignment_sha,
            "model_id": plan.model_id, "reasoning_effort": "high", "reasoning_history": "none",
            "model_behavior_tier": "REAL_LLM_REMOTE_APPROVED",
            "transaction_tier": "NATIVE_LOCAL_PROTOCOL", "model_request_boundary": observed,
            "ledger_run_id": ident, "model_cost_usd": str(cost),
            "inspect_sha256": file_sha(target),
            "erc8183_sha256": file_sha(directory / "erc8183/native-evidence.json"),
            "x402_sha256": file_sha(directory / "x402/raw-native-x402.json")
                              if (directory / "x402/raw-native-x402.json").is_file() else None}
        write_json(directory / "episode_record.json", record)
        from .open004_reporting import verify_episode
        return verify_episode(row, directory, assignment_sha=assignment_sha, ledger=ledger.snapshot())
    except BaseException as exc:
        unknown = False
        secondary = []
        if reserved and not settled:
            try:
                ledger.mark_unknown(ident, type(exc).__name__)
                unknown = True
            except Exception as err:
                secondary.append(type(err).__name__)
        partial = []
        removed_secret_artifacts = []
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            try:
                assert_no_key(path)
                partial.append({"path": str(path.relative_to(directory)), "sha256": file_sha(path)})
            except RemoteBoundaryError:
                # The durable Inspect work file already exists when a post-write
                # scan detects a credential. Remove that unsafe artifact; retain
                # its name only, never the credential-bearing bytes or exception.
                removed_secret_artifacts.append(str(path.relative_to(directory)))
                path.unlink()
            except Exception as err:
                secondary.append("partial_inventory:" + type(err).__name__)
        write_json(directory / "STOPPED.json", {
            "schema": "open004-stopped-episode-v1", "episode_id": row.episode_id,
            "assignment_manifest_sha256": assignment_sha, "error_type": type(exc).__name__,
            "budget_state": "SETTLED" if settled else "UNKNOWN" if unknown else
                            "UNRESOLVED" if reserved else "UNRESERVED",
            "model_calls_attempted": len(observed), "model_request_boundary": observed,
            "partial_artifacts": partial, "removed_secret_artifacts": removed_secret_artifacts,
            "ledger_run_id": ident, "account_usage_status": "UNKNOWN_NOT_RECONCILED" if reserved and not settled else "NO_UNSETTLED_MODEL_BILLING",
            "no_retry_or_substitution": True, "complete_payment_claim": False,
            "secondary_failure_types": secondary})
        raise
