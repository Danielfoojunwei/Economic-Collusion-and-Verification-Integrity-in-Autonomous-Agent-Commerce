"""Fail-stop one-row paid runner for the FEE011 inherited fee assignment.

Import/preflight are read-only. This runner reuses the exact FEE010 rows and
task/native controllers, while assigning fresh FEE011 ledger IDs and archives.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import os
import shutil

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log

from .erc8183_fee_native import FeeNativeController
from .erc8183_fee_native_verifier import verify_file as verify_native_file
from .erc8183_fee_plan import CANONICAL_LEDGER, PROVIDER_CALLS, AUDITOR_CALLS, ROWS
from .erc8183_fee_remote import (_enabled, _models, _post_reserve,
    _post_settle, _usage_estimate, fresh_budget, guard_model_apis,
    required_headroom, verify_boundary)
from .erc8183_fee_task import erc8183_fee_invoice_orbit
from .mpp005_boundary import (RemoteBoundaryError, account_usage_delta_usd,
    account_usage_usd, assert_no_key, file_sha, write_json)
from .remote_budget import BudgetLedger


ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "artifacts/gates/ERC8183_FEE011/runs-001"


def _canonical_root() -> None:
    if ROOT.resolve() != CANONICAL_LEDGER.parents[2].resolve():
        raise RemoteBoundaryError("FEE011 paid runner must run in canonical shared-ledger checkout")


def run_id(assignment_sha: str, episode_id: str) -> str:
    return f"fee011-{assignment_sha[:12]}-{episode_id}"


@dataclass(frozen=True)
class Fee011Plan:
    ledger_path: Path = CANONICAL_LEDGER
    runs_dir: Path = RUNS

    def validate(self):
        _canonical_root()
        from scripts.fee011_freeze import verify
        if (self.ledger_path.resolve() != CANONICAL_LEDGER.resolve()
                or self.runs_dir.resolve() != RUNS.resolve()):
            raise RemoteBoundaryError("FEE011 must use frozen paths and canonical USD50 ledger")
        return verify()


def preflight(plan: Fee011Plan = Fee011Plan()) -> dict:
    _canonical_root()
    from scripts.fee011_collect import verify_episode
    frozen, assignment_sha, rows = plan.validate()
    ledger = BudgetLedger(plan.ledger_path).snapshot()
    next_index = None
    for index, row in enumerate(rows):
        directory = plan.runs_dir / "episodes" / row.episode_id
        if (directory / "STOPPED.json").exists():
            raise RemoteBoundaryError("earlier FEE011 row stopped; no retry or later calls")
        if (directory / "episode_record.json").is_file():
            if next_index is not None:
                raise RemoteBoundaryError("completed FEE011 row after execution gap")
            verify_episode(row, directory, assignment_sha=assignment_sha, ledger=ledger)
        elif directory.exists():
            raise RemoteBoundaryError("partial assigned FEE011 row exists; no retry")
        elif next_index is None:
            next_index = index
    if next_index is None:
        raise RemoteBoundaryError("all inherited FEE011 rows attempted")
    row = rows[next_index]
    ident = run_id(assignment_sha, row.episode_id)
    if ident in ledger["runs"]:
        raise RemoteBoundaryError("assigned FEE011 ledger ID already exists")
    _, reserve, state = fresh_budget(frozen, len(rows) - next_index)
    return {"status": "PREFLIGHT_PASS_NO_CALL", "next_episode_id": row.episode_id,
            "next_index": next_index, "assignment_manifest_sha256": assignment_sha,
            "original_assignment_sha256": frozen["original_assignment_sha256"],
            "per_row_reserve_usd": str(reserve),
            "full_remaining_headroom_usd": str(required_headroom(
                reserve, len(rows) - next_index)),
            "ledger_available_usd": state["available_usd"], "ledger_seq": state["seq"],
            "reasoning_effort_by_role": {"provider": "high", "auditor": "high"},
            "role_models": frozen["role_models"]}


def execute_one(plan: Fee011Plan = Fee011Plan()) -> dict:
    _canonical_root()
    preview = preflight(plan)
    _enabled()
    from scripts.fee011_collect import verify_episode
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
            "episode_id": row.episode_id, "assignment_sha": assignment_sha,
            "original_fee010_assignment_sha": frozen["original_assignment_sha256"]})
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
                raise RemoteBoundaryError("one saved FEE011 Inspect log required")
            raw = Path(logs[0].location)
            assert_no_key(raw)
            target = directory / "inspect.eval"
            shutil.copyfile(raw, target)
            os.chmod(target, 0o600)
            if file_sha(raw) != file_sha(target):
                raise RemoteBoundaryError("FEE011 Inspect archive copy changed")
            saved = read_eval_log(str(target), resolve_attachments=True)
            estimate = _usage_estimate(saved, prices, observed)
            delta = account_usage_delta_usd(before, account_usage_usd())
            cost = max(estimate, delta)
            if cost > reserve:
                raise RemoteBoundaryError("observed FEE011 model cost exceeds reservation")
            ledger.settle(ident, cost, "sha256:" + file_sha(target))
            settled = True
            _post_settle(ledger, reserve, ROWS - preview["next_index"] - 1)
            boundary = verify_boundary(saved, observed, row)
        native_path = directory / "erc8183" / (
            "native-evidence.json" if native.verdict else "native-partial.json")
        native_result = verify_native_file(native_path, row)
        status = "COMPLETE" if native.verdict else "OBSERVED_INCOMPLETE"
        plan.validate()
        record = {"schema": "fee011-paid-episode-v1", "status": status,
                  "episode_id": row.episode_id, "assignment_manifest_sha256": assignment_sha,
                  "original_fee010_assignment_sha256": frozen["original_assignment_sha256"],
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
            "schema": "fee011-stopped-episode-v1", "episode_id": row.episode_id,
            "assignment_manifest_sha256": assignment_sha, "error_type": type(exc).__name__,
            "ledger_run_id": ident, "budget_state": "SETTLED" if settled else
                "UNKNOWN" if unknown else "UNRESOLVED" if reserved else "UNRESERVED",
            "model_request_boundary": observed, "partial_artifacts": partial,
            "no_retry_or_substitution": True, "complete_native_claim": False})
        raise
