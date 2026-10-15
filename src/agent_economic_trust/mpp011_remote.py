"""One frozen MPP011 pair per explicit invocation, with a shared USD50 ledger."""
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
from urllib.request import Request, urlopen

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log
from inspect_ai.model import GenerateConfig, get_model

from .mpp005_remote import _execution_enabled
from .mpp008_budget import UNATTRIBUTED_KEY_EXPORT_RESIDUAL_USD
from .mpp011_budget import (FEE011_HOLD_USD, fee011_hold,
    mpp006_with_x402, x402_contingent_hold)
from .mpp008_pricing import estimate_model_usage
from .mpp011_boundary import (
    REQUEST_TIMEOUT_SECONDS, RemoteBoundaryError, account_usage_delta_usd,
    account_usage_usd, assert_no_key, file_sha, guard_model_apis,
    inspect_mixed_native_log, verify_raw_model_boundary, write_json,
)
from .mpp011_native_service import NativeMeetingService
from .mpp011_plan import (
    AUDITOR_CALLS, CANONICAL_LEDGER_PATH, CONTINGENCY_USD, EVAL_TOKEN_LIMIT,
    MAX_CALLS_PER_EPISODE, MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS, MODELS,
    PROVIDER_CALLS, SCHEDULER_SECONDS, digest, refreshed_catalog, reserve_pair,
)
from .mpp011_task import native_pressure_task
from .remote_budget import BudgetLedger


ROOT = Path(__file__).resolve().parents[2]
ASSIGNMENT = ROOT / "artifacts/gates/MPP011/assignment-001"
RUNS = ROOT / "artifacts/gates/MPP011/runs-001"
MPP011_RPC_URL = "http://127.0.0.1:19767"
MPP011_HTTP_URL = "http://127.0.0.1:19759"
LOCAL_TIP20 = "0x20c0000000000000000000000000000000000000"
MPP011_GENESIS_HASH = "0xb54e201b325f207061d3502a1f4022b8a57c57bc86b7851958cc21a922b26a1f"
MPP011_MARKER_TX = "0xcbfbdd6d88281a0c727e32ab709a2ac188742e188c05db6e514e5c0f0685f977"
MPP011_MARKER_BLOCK_HASH = "0x2da511a24c05b58a2a22210c4931c92c182b14e7896585243fa908039a3b0e1e"
MPP011_TREASURY = "0x8e4d1a7b8c4f7f4204eb0643c85aa7656880e18b"
GENESIS_FUNDER = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def _rpc(method: str, params: list) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                         separators=(",", ":")).encode()
    request = Request(MPP011_RPC_URL, data=payload,
                      headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=5) as response:
            result = json.loads(response.read(65536))
    except Exception as exc:
        raise RemoteBoundaryError("marked MPP010 localnet RPC unavailable") from exc
    if (result.get("error") is not None or result.get("id") != 1
            or result.get("result") is None):
        raise RemoteBoundaryError("marked MPP010 localnet RPC response invalid")
    return result["result"]


def dedicated_chain_preflight() -> dict:
    """Confirm the persistent marked MPP010 chain and TIP20 before a row."""
    if _rpc("eth_chainId", []) != "0x539":
        raise RemoteBoundaryError("MPP011 native chain ID differs")
    genesis = _rpc("eth_getBlockByNumber", ["0x0", False])
    if not isinstance(genesis, dict) or genesis.get("hash") != MPP011_GENESIS_HASH:
        raise RemoteBoundaryError("MPP011 shared-chain genesis differs")
    code = _rpc("eth_getCode", [LOCAL_TIP20, "latest"])
    if not isinstance(code, str) or code == "0x":
        raise RemoteBoundaryError("MPP011 localnet TIP20 contract unavailable")
    receipt = _rpc("eth_getTransactionReceipt", [MPP011_MARKER_TX])
    block = _rpc("eth_getBlockByNumber", ["0x2e6", False])
    if (not isinstance(receipt, dict) or not isinstance(block, dict)
            or receipt.get("transactionHash") != MPP011_MARKER_TX
            or receipt.get("blockNumber") != "0x2e6"
            or receipt.get("blockHash") != MPP011_MARKER_BLOCK_HASH
            or receipt.get("status") != "0x1"
            or receipt.get("from", "").lower() != GENESIS_FUNDER
            or receipt.get("to", "").lower() != LOCAL_TIP20
            or block.get("hash") != MPP011_MARKER_BLOCK_HASH
            or block.get("number") != "0x2e6"
            or block.get("transactions") != [MPP011_MARKER_TX]):
        raise RemoteBoundaryError("MPP011-only chain marker receipt or block differs")
    transfers = [log for log in receipt.get("logs", [])
                 if log.get("address", "").lower() == LOCAL_TIP20
                 and log.get("topics", []) == [TRANSFER_TOPIC,
                     "0x" + GENESIS_FUNDER[2:].zfill(64),
                     "0x" + MPP011_TREASURY[2:].zfill(64)]]
    if len(transfers) != 1 or int(transfers[0]["data"], 16) != 1010:
        raise RemoteBoundaryError("MPP011-only marker transfer differs")
    balance_call = {"to": LOCAL_TIP20, "data": "0x70a08231" + MPP011_TREASURY[2:].zfill(64)}
    before = _rpc("eth_call", [balance_call, "0x2e5"])
    after = _rpc("eth_call", [balance_call, "0x2e6"])
    if (not isinstance(before, str) or not isinstance(after, str)
            or int(before, 16) != 0 or int(after, 16) != 1010):
        raise RemoteBoundaryError("MPP011-only marker historical balance differs")
    return {"status": "PASS", "chain_id": 1337, "genesis_hash": MPP011_GENESIS_HASH,
            "marker_transaction_hash": MPP011_MARKER_TX,
            "marker_block_hash": MPP011_MARKER_BLOCK_HASH,
            "tip20_code_present": True, "rpc_url": MPP011_RPC_URL}


def run_id(assignment_sha: str, episode_id: str) -> str:
    return f"mpp011-{assignment_sha[:12]}-{episode_id}"


@dataclass(frozen=True)
class Mpp011Plan:
    assignment_dir: Path = ASSIGNMENT
    runs_dir: Path = RUNS
    ledger_path: Path = CANONICAL_LEDGER_PATH

    def _paths(self) -> None:
        if (self.assignment_dir.resolve() != ASSIGNMENT.resolve()
                or self.runs_dir.resolve() != RUNS.resolve()
                or self.ledger_path.resolve() != CANONICAL_LEDGER_PATH.resolve()):
            raise RemoteBoundaryError("MPP011 path differs from frozen study or shared ledger")

    def validate(self):
        from scripts import freeze_mpp011
        self._paths()
        freeze_mpp011.verify()
        return freeze_mpp011.load_assignment()

    def validate_static(self):
        from scripts import freeze_mpp011
        self._paths()
        freeze_mpp011.verify_static()
        return freeze_mpp011.load_assignment()


def _pricing_basis(snapshots: dict) -> dict:
    if set(snapshots) != set(MODELS):
        raise RemoteBoundaryError("MPP011 exact two-model price snapshot differs")
    result = {}
    for name in MODELS:
        row = snapshots[name]
        if row.get("model_id") != name:
            raise RemoteBoundaryError("MPP011 catalog model identity differs")
        result[name] = {key: value for key, value in row.items() if key != "fetched_utc"}
    return result


def _require_contingent_ledger_state(state: dict, frozen: dict) -> None:
    if (state["blocked"] or state["unknown_run_ids"] or state["cap_usd"] != "50"):
        raise RemoteBoundaryError("shared USD50 lifetime ledger blocked")
    try:
        fee011_hold(state)
        x402 = x402_contingent_hold(state)
        exposure = mpp006_with_x402(state,
            additional_reservation_usd=FEE011_HOLD_USD)
    except (KeyError, ValueError) as exc:
        raise RemoteBoundaryError("MPP006 contingent billing hold is not intact") from exc
    if exposure != frozen["prior_mpp006_contingent_exposure"]:
        raise RemoteBoundaryError("MPP006 conditional evidence differs from freeze")
    if x402 != frozen["prior_x402_contingent_exposure"]:
        raise RemoteBoundaryError("x402011 contingent evidence differs from freeze")
    _require_study_run_set(state, frozen)


def _require_study_run_set(state: dict, frozen: dict) -> None:
    """Deny concurrent billing after freeze, even when it has already settled."""
    prior = frozen["prior_ledger_run_ids"]
    assigned_sha = file_sha(ASSIGNMENT / "assignment_manifest.json")
    own = {run_id(assigned_sha, episode) for episode in frozen["execution_order"]}
    if (prior != sorted(set(prior)) or set(state["runs"]) - set(prior) - own
            or any(ident not in state["runs"] for ident in prior)
            or digest({ident: state["runs"][ident] for ident in prior}) !=
               frozen["prior_ledger_runs_sha256"]):
        raise RemoteBoundaryError("post-freeze competing ledger run or prior billing changed")


def remaining_headroom(reserves: dict[str, Decimal] | list[Decimal]) -> Decimal:
    """Retain contingency and residual after each committed row leaves the block."""
    values = list(reserves.values()) if isinstance(reserves, dict) else reserves
    if any(not isinstance(value, Decimal) or not value.is_finite() or value <= 0
           for value in values):
        raise RemoteBoundaryError("MPP011 remaining reservations must be positive")
    return sum(values, Decimal(0)) + CONTINGENCY_USD + UNATTRIBUTED_KEY_EXPORT_RESIDUAL_USD


def _fresh_budget(plan: Mpp011Plan, frozen: dict, remaining: list[Any]):
    state = BudgetLedger(plan.ledger_path).snapshot()
    _require_contingent_ledger_state(state, frozen)
    prices = refreshed_catalog()
    if _pricing_basis(prices) != _pricing_basis(frozen["public_pricing_snapshots"]):
        raise RemoteBoundaryError("MPP011 published model route, cap or price changed since freeze")
    reserves = {row.episode_id: max(
        Decimal(frozen["worst_case_reserve_usd_by_episode"][row.episode_id]),
        reserve_pair(prices, row.provider_model_id, row.auditor_model_id)) for row in remaining}
    if remaining_headroom(reserves) > Decimal(state["available_usd"]):
        raise RemoteBoundaryError("full remaining MPP011 block plus contingency exceeds shared budget")
    return prices, reserves, state


def fresh_budget(plan: Mpp011Plan, frozen: dict, remaining: list[Any]):
    from scripts import freeze_mpp011
    freeze_mpp011.verify()
    return _fresh_budget(plan, frozen, remaining)


def fresh_budget_in_service(plan: Mpp011Plan, frozen: dict, remaining: list[Any]):
    from scripts import freeze_mpp011
    freeze_mpp011.verify_static()
    return _fresh_budget(plan, frozen, remaining)


def post_reservation_budget(snapshot: dict, frozen: dict, ident: str,
                            current_reserve: Decimal, remaining: list[Decimal]) -> None:
    if (snapshot["blocked"] or snapshot["unknown_run_ids"]
            or snapshot["cap_usd"] != "50"):
        raise RemoteBoundaryError("shared ledger blocked after MPP011 reservation")
    _require_study_run_set(snapshot, frozen)
    try:
        fee011_hold(snapshot)
        x402 = x402_contingent_hold(snapshot)
        exposure = mpp006_with_x402(snapshot,
            additional_reservation_usd=FEE011_HOLD_USD + current_reserve)
    except (KeyError, ValueError) as exc:
        raise RemoteBoundaryError("MPP006 contingent hold changed after MPP011 reserve") from exc
    if exposure != frozen["prior_mpp006_contingent_exposure"]:
        raise RemoteBoundaryError("MPP006 hold differs from frozen evidence")
    if x402 != frozen["prior_x402_contingent_exposure"]:
        raise RemoteBoundaryError("x402011 hold differs from frozen evidence")
    current = snapshot["runs"].get(ident)
    if (not isinstance(current, dict) or current.get("status") != "RESERVED"
            or Decimal(current.get("reserved_usd", "-1")) != current_reserve):
        raise RemoteBoundaryError("MPP011 current reservation differs")
    if remaining_headroom(remaining) > Decimal(
            snapshot["available_usd"]):
        raise RemoteBoundaryError("concurrent spending consumed remaining MPP011 block")


def post_settlement_budget(ledger: BudgetLedger, frozen: dict,
                           remaining: list[Decimal]) -> dict:
    state = ledger.snapshot()
    _require_contingent_ledger_state(state, frozen)
    if remaining_headroom(remaining) > Decimal(
            state["available_usd"]):
        raise RemoteBoundaryError("settled MPP011 row left insufficient full-block headroom")
    return state


def preflight(plan: Mpp011Plan = Mpp011Plan()) -> dict:
    """Read-only next-row gate; source, local controls, prices and budget rechecked."""
    from .mpp011_reporting import verify_episode

    frozen, assignment_sha, rows = plan.validate()
    by_id = {row.episode_id: row for row in rows}
    if len(by_id) != 5 or set(by_id) != set(frozen["execution_order"]):
        raise RemoteBoundaryError("frozen MPP011 five-row denominator differs")
    ledger = BudgetLedger(plan.ledger_path).snapshot()
    next_index = None
    for index, episode_id in enumerate(frozen["execution_order"]):
        row = by_id[episode_id]
        directory = plan.runs_dir / "episodes" / episode_id
        if (directory / "STOPPED.json").exists():
            raise RemoteBoundaryError("earlier MPP011 row stopped; no retry or later paid calls")
        if (directory / "episode_record.json").is_file():
            if next_index is not None:
                raise RemoteBoundaryError("completed MPP011 row appears after a gap")
            verified = verify_episode(row, directory, assignment_sha=assignment_sha,
                                      ledger=ledger)
            if index == 0 and verified["status"] not in {"COMPLETE", "OBSERVED_INCOMPLETE"}:
                raise RemoteBoundaryError("first technical compatibility gate failed")
        elif directory.exists():
            raise RemoteBoundaryError("partial MPP011 episode exists; no retry")
        elif next_index is None:
            next_index = index
    if next_index is None:
        raise RemoteBoundaryError("all five MPP011 rows already attempted")
    remaining = [by_id[episode_id] for episode_id in frozen["execution_order"][next_index:]]
    row = remaining[0]
    if run_id(assignment_sha, row.episode_id) in ledger["runs"]:
        raise RemoteBoundaryError("assigned MPP011 ledger run ID already exists")
    prices, reserves, state = fresh_budget(plan, frozen, remaining)
    chain = dedicated_chain_preflight()
    return {"mode": "dry-run", "ready_to_execute": True,
            "next_episode_id": row.episode_id, "next_index": next_index,
            "next_provider_model_id": row.provider_model_id,
            "next_auditor_model_id": row.auditor_model_id,
            "first_row_compatibility_gate": next_index == 0,
            "assignment_manifest_sha256": assignment_sha,
            "next_reservation_usd": str(reserves[row.episode_id]),
            "full_remaining_reservation_usd": str(sum(reserves.values(), Decimal(0))),
            "mpp006_retained_reservation_usd": frozen["prior_mpp006_contingent_exposure"]["prior_reservation_usd"],
            "x402011_retained_reservation_usd": frozen["prior_x402_contingent_exposure"]["reserved_usd"],
            "unattributed_key_export_residual_usd": frozen["prior_mpp006_contingent_exposure"]["unattributed_key_export_residual_usd"],
            "required_headroom_usd": str(remaining_headroom(reserves)),
            "contingency_usd": str(CONTINGENCY_USD),
            "available_usd": state["available_usd"],
            "fresh_public_pricing": prices,
            "reasoning_effort_by_role": {"provider": "high", "auditor": "high"},
            "max_calls_by_role": {"provider": PROVIDER_CALLS, "auditor": AUDITOR_CALLS},
            "max_input_bytes": MAX_INPUT_BYTES, "max_output_tokens": MAX_OUTPUT_TOKENS,
            "max_retries": 0, "dedicated_chain": chain}


def _usage_estimate(log: Any, prices: dict, observed: list[dict]) -> Decimal:
    if len(log.samples or []) != 1:
        raise RemoteBoundaryError("one Inspect sample required for usage")
    usage = log.samples[0].model_usage
    counts = Counter(item["model"].removeprefix("openrouter/") for item in observed)
    if not counts or not set(counts).issubset(MODELS) or set(usage) != {
            "openrouter/" + model for model in counts}:
        raise RemoteBoundaryError("provider usage keys differ from actual assigned calls")
    return sum((estimate_model_usage(prices[model], usage["openrouter/" + model], calls)
                for model, calls in counts.items()), Decimal(0))


def _configured_models(row):
    config = GenerateConfig(reasoning_effort="high", reasoning_history="none",
        max_tokens=MAX_OUTPUT_TOKENS, max_retries=0, timeout=REQUEST_TIMEOUT_SECONDS,
        max_connections=1, cache=False)
    models = {}
    for role, model_id in (("provider", row.provider_model_id),
                           ("auditor", row.auditor_model_id)):
        model = get_model("openrouter/" + model_id)
        if type(model.api).__name__ != "OpenRouterAPI" or str(model) != "openrouter/" + model_id:
            raise RemoteBoundaryError("explicit MPP011 route is not native OpenRouter")
        model.api.client.max_retries = 0
        if model.api.client.max_retries != 0:
            raise RemoteBoundaryError("OpenRouter HTTP client retains implicit retries")
        model.config = config.model_copy(deep=True)
        if get_model("openrouter/" + model_id) is not model:
            raise RemoteBoundaryError("ORBIT explicit model lookup is not bounded instance")
        models[role] = model
    return models


def execute_one(plan: Mpp011Plan = Mpp011Plan()) -> dict:
    """Execute exactly one assigned row after explicit opt-in and all gates."""
    preview = preflight(plan)
    _execution_enabled()
    frozen, assignment_sha, rows = plan.validate()
    dedicated_chain_preflight()
    row = next(row for row in rows if row.episode_id == preview["next_episode_id"])
    directory = plan.runs_dir / "episodes" / row.episode_id
    directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.mkdir(mode=0o700)
    os.chmod(directory, 0o700)
    service = NativeMeetingService((directory / "native").resolve(), row,
                                   MPP011_RPC_URL, MPP011_HTTP_URL)
    ledger = BudgetLedger(plan.ledger_path)
    ident = run_id(assignment_sha, row.episode_id)
    observed: list[dict] = []
    reserved = settled = False
    try:
        _, prepared = asyncio.run(service.prepare())
        public_terms = service.public_terms()
        if (prepared.get("funding_policy") != "PERSISTENT_ISOLATED_CHAIN_FLOOR_TOPUP"
                or prepared.get("funding_floors_atomic") != {
                    "provider": "100000", "oracle": "20000", "client": "200000"}
                or public_terms.get("provider_funding_floor_atomic") != 100_000
                or public_terms.get("provider_funding_representation") !=
                    "MINIMUM_CERTIFIED_BALANCE_EXACT_AMOUNT_WITHHELD"):
            raise RemoteBoundaryError("MPP011 pre-model native funding floor differs")
        task = native_pressure_task(row, service=service)
        assigned_prompts = {agent["name"]: agent["system_prompt"] for agent in
            task.dataset[0].metadata["experiment"]["setup"]["agents"]}
        before = account_usage_usd()
        models = _configured_models(row)
        observed = guard_model_apis(models, row, assigned_prompts)
        remaining = [next(item for item in rows if item.episode_id == episode_id)
                     for episode_id in frozen["execution_order"][preview["next_index"]:]]
        prices, reserves, _ = fresh_budget_in_service(plan, frozen, remaining)
        reserve = reserves[row.episode_id]
        snapshot = ledger.reserve(ident, reserve, Decimal("50"), metadata={
            "provider_model_id": row.provider_model_id,
            "auditor_model_id": row.auditor_model_id,
            "episode_id": row.episode_id, "assignment_sha": assignment_sha})
        reserved = True
        post_reservation_budget(snapshot, frozen, ident, reserve,
            [reserves[item.episode_id] for item in remaining[1:]])
        logs = inspect_eval(task, model=models["provider"], sample_id=row.trial_id,
            max_samples=1, max_tasks=1, epochs=1, retry_on_error=0,
            fail_on_error=True, time_limit=SCHEDULER_SECONDS,
            token_limit=EVAL_TOKEN_LIMIT, message_limit=80,
            turn_limit=MAX_CALLS_PER_EPISODE,
            log_dir=str(directory / "inspect_work"), log_format="eval",
            log_model_api=False, display="none", log_level="error")
        if len(logs) != 1 or not logs[0].location:
            raise RemoteBoundaryError("one saved MPP011 Inspect log required")
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
            raise RemoteBoundaryError("observed MPP011 model charge exceeds reservation")
        ledger.settle(ident, cost, "sha256:" + file_sha(target))
        settled = True
        post_settlement_budget(ledger, frozen,
            [reserves[item.episode_id] for item in remaining[1:]])
        boundary = verify_raw_model_boundary(saved, observed, row)
        if saved.samples[0].store.get("OpenMppStore:decision") is None:
            from .mpp011_reporting import verify_partial_native
            partial = verify_partial_native(saved, service, row)
            decision = provenance = None
            status = "OBSERVED_INCOMPLETE"
        else:
            decision, provenance = inspect_mixed_native_log(saved, service=service,
                                                              row=row, observed=observed)
            write_json(directory / "decision.json", decision)
            compensation = directory / "native/compensation-evidence.json"
            asyncio.run(service._command(ROOT / "protocols/mpp/mpp011-decision-preflight.mjs",
                directory / "decision.json", decision["selected_flow"]))
            asyncio.run(service._command(ROOT / "protocols/mpp/mpp011-meeting-local.mjs",
                directory / "decision.json", decision["selected_flow"], compensation))
            asyncio.run(service._command(ROOT / "protocols/mpp/mpp011-verify-meeting-evidence.mjs",
                compensation))
            partial = []
            status = "COMPLETE"
        plan.validate_static()
        record = {"schema": "mpp011-paid-episode-v1", "status": status,
            "episode_id": row.episode_id, "assignment_manifest_sha256": assignment_sha,
            "provider_model_id": row.provider_model_id,
            "auditor_model_id": row.auditor_model_id,
            "reasoning_effort_by_role": {"provider": "high", "auditor": "high"},
            "reasoning_history": "none", "model_execution_tier": "REAL_LLM_REMOTE_APPROVED",
            "http_client_max_retries_by_role": {"provider": 0, "auditor": 0},
            "transaction_tier": "NATIVE_LOCAL_PROTOCOL", "model_request_boundary": observed,
            "raw_model_boundary": boundary,
            "normalized_replay_provenance": provenance,
            "ledger_run_id": ident, "model_cost_usd": str(cost),
            "inspect_sha256": file_sha(target), "usage_estimate_usd": str(estimated),
            "account_usage_before_usd": str(before),
            "account_usage_after_usd": str(after),
            "account_usage_delta_usd": str(delta),
            "fresh_public_pricing_snapshots": prices,
            "prepare_sha256": file_sha(directory / "native/prepare-evidence.json"),
            "decision_sha256": decision["decision_sha256"] if decision else None,
            "compensation_sha256": file_sha(compensation) if decision else None,
            "partial_native_operations": partial}
        write_json(directory / "episode_record.json", record)
        from .mpp011_reporting import verify_episode
        return verify_episode(row, directory, assignment_sha=assignment_sha,
                              ledger=ledger.snapshot())
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
                partial_files.append({"path": str(path.relative_to(directory)),
                                      "sha256": file_sha(path)})
            except RemoteBoundaryError:
                removed.append(str(path.relative_to(directory)))
                path.unlink()
            except Exception as error:
                secondary.append("partial_inventory:" + type(error).__name__)
        write_json(directory / "STOPPED.json", {
            "schema": "mpp011-stopped-episode-v1", "episode_id": row.episode_id,
            "assignment_manifest_sha256": assignment_sha,
            "error_type": type(exc).__name__,
            "budget_state": "SETTLED" if settled else "UNKNOWN" if unknown else
                            "UNRESOLVED" if reserved else "UNRESERVED",
            "ledger_run_id": ident, "model_calls_attempted": len(observed),
            "model_request_boundary": observed,
            "partial_artifacts": partial_files,
            "removed_secret_artifacts": removed,
            "no_retry_or_substitution": True, "complete_payment_claim": False,
            "secondary_failure_types": secondary})
        raise
