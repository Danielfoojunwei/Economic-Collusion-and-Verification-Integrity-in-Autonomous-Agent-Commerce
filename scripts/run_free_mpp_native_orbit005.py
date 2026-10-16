#!/usr/bin/env python3
"""Source-frozen ORBIT005 process-isolated native MPP follow-up.

Default is a network-free dry run. --execute needs a fresh, separately marked
valueless local chain. It never resumes ORBIT001-003 or MPP010 rows.
"""
from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ.setdefault("XDG_DATA_HOME", str(ROOT.parent / ".local/share"))
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT.parent / ".cache"))
os.environ.setdefault("XDG_CONFIG_HOME", str(ROOT.parent / ".config"))
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log

from agent_economic_trust import mpp010_native_service, mpp010_orbit
from agent_economic_trust.free_collusion_probe import MPP, OpenRouterTransport
from agent_economic_trust.free_mpp_native_orbit_adapter import (
    ZeroPriceModelGuard, assigned_row as old_assigned_row,
    bind_reasoning_provenance, configure_free_models, review_guard_journal,
)
from agent_economic_trust.free_mpp_native_orbit005_chain import (
    IsolatedOrbitNativeService, RPC_URL, prepare_overlay, validate_marker,
)
from agent_economic_trust.free_mpp_native_orbit_delivery import (
    delivered_market_accept, exposed_native_market_decide,
    inspect_followup_native_log, install_offer_exposure_gate,
)
from agent_economic_trust.free_mpp_native_orbit005_offer_role import (
    ARMS, FreeNativeBoundaryError, assigned_row, build_task,
    frozen_assignment, install_provider_first_gate, ordered_proposal_policy,
    standing_offer_policy,
)
from agent_economic_trust.mpp010_plan import EVAL_TOKEN_LIMIT, MAX_CALLS_PER_EPISODE, SCHEDULER_SECONDS
from scripts.review_free_collusion_probe import review as review_text_study
from scripts.review_free_mpp_native_orbit import _verify_control_prompt_boundary
from scripts.review_free_mpp_native_orbit005 import (
    review as review_native, verify_ordered_model_sequence,
    verify_wire_trace,
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _write(path: Path, value: dict) -> None:
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _archive_diagnostic(directory: Path) -> dict | None:
    """Preserve the primary Inspect status without trusting derived traces."""
    archives = list((directory / "logs").glob("*.eval"))
    if len(archives) != 1 or archives[0].is_symlink():
        return None
    path = archives[0]
    result = {"path": str(path.resolve()),
              "sha256": sha256(path.read_bytes()).hexdigest()}
    try:
        raw = read_eval_log(str(path), resolve_attachments=True)
        sample = raw.samples[0] if len(raw.samples or []) == 1 else None
        error = getattr(sample, "error", None)
        result.update(status=raw.status,
                      sample_error_type=(getattr(error, "type", None)
                                         or (type(error).__name__ if error else None)),
                      sample_error_message_sha256=(
                          sha256(str(getattr(error, "message", "")).encode()).hexdigest()
                          if error else None))
    except BaseException as exc:
        result["archive_read_error_type"] = type(exc).__name__
    return result


def _terminal_text_gate(path: Path) -> dict:
    result = review_text_study(path)
    if (result.get("review_status") != "PASS" or result.get("scenario") != MPP
            or result.get("chain_status") not in {"COMPLETE", "COMPLETE_WITH_MISSING", "STOPPED"}
            or result.get("model_execution_tier") != "REAL_LLM_REMOTE_ZERO_PRICE_IF_COMPLETED"):
        raise FreeNativeBoundaryError("MPP text study is not terminal and independently replayed")
    return result


def _advancing_local_chain() -> tuple[int, int]:
    def block() -> int:
        request = Request(RPC_URL, b'{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}',
                          {"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=3) as response:
            result = json.load(response)
        if result.get("id") != 1 or not isinstance(result.get("result"), str):
            raise FreeNativeBoundaryError("fresh Tempo RPC block response invalid")
        return int(result["result"], 16)
    first = block()
    time.sleep(1.1)
    second = block()
    if second <= first:
        raise FreeNativeBoundaryError("fresh Tempo chain is not advancing")
    return first, second


def execute_worker(output: Path, marker_path: Path, arm: str) -> dict:
    """One irrevocable row attempt; this process must run no other Inspect eval."""
    if arm not in ARMS:
        raise FreeNativeBoundaryError("unknown ORBIT005 worker arm")
    output = Path(output).resolve()
    if json.loads((output / "assignment.json").read_bytes()) != frozen_assignment():
        raise FreeNativeBoundaryError("worker assignment or source seal differs")
    intent = json.loads((output / ("worker-intent-" + arm + ".json")).read_bytes())
    if (intent.get("arm") != arm or intent.get("episode_id") != assigned_row(arm).episode_id
            or intent.get("parent_pid") != os.getppid()
            or intent.get("assignment_sha256") != sha256(
                (output / "assignment.json").read_bytes()).hexdigest()
            or not isinstance(intent.get("worker_nonce"), str)
            or len(intent["worker_nonce"]) != 64):
        raise FreeNativeBoundaryError("worker launch intent differs")
    if arm != ARMS[0] and not (output / assigned_row(ARMS[0]).episode_id / "COMPLETE.json").is_file():
        raise FreeNativeBoundaryError("prior ORBIT005 arm did not complete")
    validate_marker(marker_path)
    row = assigned_row(arm)
    directory = output / row.episode_id
    directory.mkdir(mode=0o700, exist_ok=False)
    from scripts.review_free_mpp_native_orbit005 import source_hashes
    _write(directory / "worker-start.json", {
        "schema": "orbit005-one-eval-worker-v1", "arm": arm,
        "episode_id": row.episode_id, "pid": os.getpid(),
        "parent_pid": os.getppid(), "worker_nonce": intent["worker_nonce"],
        "runner_sha256": source_hashes()["scripts/run_free_mpp_native_orbit005.py"],
        "intent_sha256": sha256((output / ("worker-intent-" + arm + ".json")).read_bytes()).hexdigest(),
    })
    guard = None
    primary_archive = None
    try:
            key = os.environ.get("OPENROUTER_API_KEY")
            if not key:
                raise FreeNativeBoundaryError("OpenRouter credential unavailable")
            transport = OpenRouterTransport(key)
            prepare_overlay(directory, marker_path)
            service = IsolatedOrbitNativeService(directory.resolve(), row,
                overlay_dir=(directory / "native-overlay/protocols/mpp").resolve())
            asyncio.run(service.prepare())
            task = build_task(service)
            models = configure_free_models()
            guard = ZeroPriceModelGuard(directory / "model-calls.jsonl", transport)
            # The reused guard's row argument is only a route/cap token. Its
            # source checks no IDs or economics after membership; new IDs are
            # separately checked by build_task and both reviewers.
            route_row = old_assigned_row(arm)
            if ((route_row.provider_model_id, route_row.auditor_model_id) !=
                    (row.provider_model_id, row.auditor_model_id)):
                raise FreeNativeBoundaryError("reused guard route pair differs")
            try:
                observed = guard.install(models, route_row)
                install_provider_first_gate(models)
                install_offer_exposure_gate(models, guard, directory / "offer-delivery.json")
                with standing_offer_policy(), ordered_proposal_policy(), \
                     patch.object(mpp010_orbit, "market_accept", delivered_market_accept), \
                     patch.object(mpp010_native_service, "native_market_decide", exposed_native_market_decide):
                    logs = inspect_eval(task, model=models["provider"],
                        sample_id=row.trial_id, max_samples=1, max_tasks=1,
                        epochs=1, retry_on_error=0, fail_on_error=True,
                        time_limit=SCHEDULER_SECONDS, token_limit=EVAL_TOKEN_LIMIT,
                        message_limit=80, turn_limit=MAX_CALLS_PER_EPISODE,
                        log_dir=str(directory / "logs"), log_format="eval",
                        log_model_api=False, display="none", log_level="error")
            finally:
                guard.restore()
            if len(logs) != 1 or not logs[0].location:
                raise FreeNativeBoundaryError("one raw Inspect archive required")
            raw = read_eval_log(logs[0].location, resolve_attachments=True)
            sample = raw.samples[0] if len(raw.samples or []) == 1 else None
            error = getattr(sample, "error", None)
            primary_archive = _archive_diagnostic(directory)
            if raw.status != "success" or sample is None or error:
                raise FreeNativeBoundaryError("raw Inspect archive stopped before derived offer review")
            verify_ordered_model_sequence(raw)
            _verify_control_prompt_boundary(raw, arm)
            replayed_observed = review_guard_journal(directory / "model-calls.jsonl")
            if observed != replayed_observed:
                raise FreeNativeBoundaryError("durable zero-price calls differ from ORBIT boundary")
            trace_path = directory / "offer-delivery.json"
            if not trace_path.is_file():
                raise FreeNativeBoundaryError(
                    "raw Inspect row lacked successful provider-offer acceptance and exact delivery")
            trace = json.loads(trace_path.read_bytes())
            with standing_offer_policy(), ordered_proposal_policy():
                decision, provenance = inspect_followup_native_log(
                    raw, service=service, row=row, observed=observed, trace=trace)
            verify_wire_trace(directory, provenance["offer_delivery"], raw)
            decision = bind_reasoning_provenance(decision, directory / "model-calls.jsonl")
            _write(directory / "decision.json", decision)
            asyncio.run(service._command(ROOT / "protocols/mpp/free-orbit-decision-preflight.mjs",
                directory / "decision.json", decision["selected_flow"]))
            compensation_path = directory / "compensation-evidence.json"
            asyncio.run(service._command(ROOT / "protocols/mpp/mpp010-meeting-local.mjs",
                directory / "decision.json", decision["selected_flow"], compensation_path))
            result = review_native(directory, arm)
            if result["status"] != "INDEPENDENT_NATIVE_MODEL_AND_EXACT_DELIVERY_REPLAY_PASS":
                raise FreeNativeBoundaryError("independent native/delivery reviewer did not pass")
            _write(directory / "independent-review.json", result)
            _write(directory / "COMPLETE.json", {
                "status": "EXPLORATORY_FOLLOWUP_COMPLETE", "arm": arm,
                "episode_id": row.episode_id,
                "raw_model_events_sha256": provenance["raw_model_events_sha256"],
                "independent_review_sha256": sha256(_canonical(result)).hexdigest(),
                "model_execution_tier": "REAL_LLM_REMOTE_ZERO_PRICE_IF_COMPLETED",
                "transaction_execution_tier": "NATIVE_LOCAL_PROTOCOL",
                "scientific_mpp010_result_row": False})
            return {"status": "COMPLETE", "arm": arm, "episode_id": row.episode_id}
    except BaseException as exc:
        if primary_archive is None:
            primary_archive = _archive_diagnostic(directory)
        _write(directory / "STOPPED.json", {
            "status": "EXPLORATORY_FOLLOWUP_STOPPED", "arm": arm,
            "episode_id": row.episode_id, "error_type": type(exc).__name__,
            "primary_inspect_archive": primary_archive,
            "model_calls_forwarded": guard.forwarded if guard else 0,
            "unknown_charge_possible": bool(guard and
                guard.forwarded > sum(guard.completed.values())),
            "later_rows_unattempted": list(ARMS[ARMS.index(arm) + 1:]),
            "no_retry": True})
        return {"status": "STOPPED", "arm": arm, "episode_id": row.episode_id,
                "later_arms_unattempted": list(ARMS[ARMS.index(arm) + 1:])}


def _run_workers(output: Path, marker_path: Path) -> dict:
    """Parent dispatches sequential workers; any uncertain exit stops the block."""
    completed = []
    assignment_sha = sha256((output / "assignment.json").read_bytes()).hexdigest()
    for arm in ARMS:
        row = assigned_row(arm)
        nonce = os.urandom(32).hex()
        _write(output / ("worker-intent-" + arm + ".json"), {
            "arm": arm, "episode_id": row.episode_id,
            "parent_pid": os.getpid(), "worker_nonce": nonce,
            "assignment_sha256": assignment_sha,
            "no_retry": True,
        })
        command = [sys.executable, str(ROOT / "scripts/run_free_mpp_native_orbit005.py"),
                   "--worker-arm", arm, "--output", str(output),
                   "--chain-marker", str(marker_path)]
        worker = None
        try:
            worker = subprocess.Popen(command, cwd=str(ROOT), stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE)
            _write(output / ("worker-launch-" + arm + ".json"), {
                "arm": arm, "pid": worker.pid, "worker_nonce": nonce,
                "command_sha256": sha256(_canonical(command)).hexdigest()})
            stdout, stderr = worker.communicate(timeout=900)
            result_path = output / row.episode_id / "worker-result.json"
            result = json.loads(result_path.read_bytes()) if result_path.is_file() else None
            start_path = output / row.episode_id / "worker-start.json"
            start = json.loads(start_path.read_bytes()) if start_path.is_file() else None
            _write(output / ("worker-exit-" + arm + ".json"), {
                "arm": arm, "pid": worker.pid, "exit_code": worker.returncode,
                "stdout_sha256": sha256(stdout).hexdigest(),
                "stderr_sha256": sha256(stderr).hexdigest(),
                "worker_result": result})
            if (worker.returncode != 0 or result != {
                    "status": "COMPLETE", "arm": arm, "episode_id": row.episode_id}
                    or not start or start.get("pid") != worker.pid
                    or start.get("parent_pid") != os.getpid()
                    or start.get("worker_nonce") != nonce
                    or not (output / row.episode_id / "COMPLETE.json").is_file()):
                raise FreeNativeBoundaryError("worker stopped or process proof differs")
            completed.append(row.episode_id)
        except BaseException as exc:
            if worker is not None and worker.poll() is None:
                worker.kill()
                worker.communicate()
            _write(output / "BLOCK_STOPPED.json", {
                "status": "STOPPED", "arm": arm, "episode_id": row.episode_id,
                "completed_episode_ids": completed,
                "error_type": type(exc).__name__,
                "later_arms_unattempted": list(ARMS[ARMS.index(arm) + 1:]),
                "unknown_charge_or_native_state_possible": True,
                "no_retry": True})
            return {"status": "STOPPED", "completed_episode_ids": completed,
                    "stopped_episode_id": row.episode_id,
                    "later_arms_unattempted": list(ARMS[ARMS.index(arm) + 1:])}
    return {"status": "COMPLETE", "completed_episode_ids": completed,
            "planned_episodes": len(ARMS)}


def execute(output: Path, source_study: Path, marker_path: Path) -> dict:
    frozen = frozen_assignment()
    if Path(source_study).resolve() != (ROOT / frozen["source_text_study"]).resolve():
        raise FreeNativeBoundaryError("source text study differs from frozen ORBIT005 assignment")
    source_review = _terminal_text_gate(source_study)
    if sha256(_canonical(source_review)).hexdigest() != frozen[
            "source_text_independent_review_sha256"]:
        raise FreeNativeBoundaryError("source text independent review differs from assignment")
    marker = validate_marker(marker_path)
    blocks = _advancing_local_chain()
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise FreeNativeBoundaryError("OpenRouter credential unavailable")
    output = Path(output).resolve()
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    _write(output / "assignment.json", frozen)
    _write(output / "source-text-collection.json", {
        "path": str(Path(source_study).resolve()),
        "review_sha256": sha256(_canonical(source_review)).hexdigest(),
        "review": source_review,
        "selection": "fixed ORBIT005 post-ORBIT004 displaced-provider-offer follow-up",
        "billing_reconciliation": "NOT_CLAIMED; semantic PASS does not settle prior unknown billing"})
    _write(output / "chain-preflight.json", {
        "marker": marker, "advancing_blocks": list(blocks),
        "distinct_from_orbit001_through_orbit003": True})
    return _run_workers(output, Path(marker_path).resolve())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-study", type=Path)
    parser.add_argument("--chain-marker", type=Path)
    parser.add_argument("--worker-arm", choices=ARMS)
    args = parser.parse_args()
    try:
        frozen = frozen_assignment()
        if args.worker_arm:
            if not (args.output and args.chain_marker) or args.execute or args.source_study:
                parser.error("worker requires --output and --chain-marker only")
            result = execute_worker(args.output, args.chain_marker, args.worker_arm)
            _write(Path(args.output).resolve() / assigned_row(args.worker_arm).episode_id /
                   "worker-result.json", result)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["status"] == "COMPLETE" else 1
        if not args.execute:
            print(json.dumps({"mode": "dry-run", "external_calls": 0,
                              "native_transactions": 0, "assignment": frozen},
                             indent=2, sort_keys=True))
            return 0
        if not all((args.output, args.source_study, args.chain_marker)):
            parser.error("--execute requires --output, --source-study, and --chain-marker")
        result = execute(args.output, args.source_study, args.chain_marker)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "COMPLETE" else 1
    except Exception as exc:
        # HTTP exceptions can contain request details or credentials.
        print("Free ORBIT005 stopped: " + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
