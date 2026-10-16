#!/usr/bin/env python3
"""Two fixed exploratory free-model ORBIT/native MPP controls.

Default is a network-free source dry run. --execute is a separate post-pilot
experiment on a fresh disposable Tempo chain. It never resumes or changes the
frozen ten-row MPP010 study, and it stops both arms on the first uncertainty.
"""

from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ.setdefault("XDG_DATA_HOME", str(ROOT.parent / ".local/share"))
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT.parent / ".cache"))
os.environ.setdefault("XDG_CONFIG_HOME", str(ROOT.parent / ".config"))
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log

from agent_economic_trust.free_collusion_probe import (
    MPP, OpenRouterTransport,
)
from agent_economic_trust.free_mpp_native_orbit_adapter import (
    ARMS, FreeNativeBoundaryError, ZeroPriceModelGuard, assigned_row,
    bind_reasoning_provenance, build_native_task, configure_free_models, prospective_assignment,
    review_guard_journal,
)
from agent_economic_trust.free_mpp_native_orbit_chain import (
    FreeOrbitNativeService, RPC_URL, prepare_overlay, validate_marker,
)
from agent_economic_trust.mpp010_boundary import verify_raw_model_boundary
from agent_economic_trust.mpp010_plan import (
    EVAL_TOKEN_LIMIT, MAX_CALLS_PER_EPISODE, SCHEDULER_SECONDS,
)
from scripts.review_free_collusion_probe import review as review_text_study
from scripts.review_free_mpp_native_orbit import _source_hashes, review as review_native
from scripts.review_free_mpp_native_orbit import _verify_control_prompt_boundary


FROZEN = ROOT / "artifacts/prospective/FREE_MPP_NATIVE_ORBIT001/assignment.json"


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _write(path: Path, value: dict) -> None:
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def frozen_assignment() -> dict:
    if not FROZEN.is_file():
        raise FreeNativeBoundaryError("prospective native ORBIT assignment is not frozen")
    saved = json.loads(FROZEN.read_bytes())
    expected = {**prospective_assignment(), "source_files_sha256": _source_hashes()}
    if saved != expected:
        raise FreeNativeBoundaryError("prospective assignment or pinned source changed")
    return saved


def _advancing_local_chain() -> tuple[int, int]:
    def block() -> int:
        request = Request(RPC_URL, b'{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}',
                          {"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=3) as response:
            result = json.load(response)
        if result.get("id") != 1 or not isinstance(result.get("result"), str):
            raise FreeNativeBoundaryError("isolated Tempo RPC block response invalid")
        return int(result["result"], 16)
    first = block()
    time.sleep(1.1)
    second = block()
    if second <= first:
        raise FreeNativeBoundaryError("isolated Tempo chain is not advancing")
    return first, second


def _terminal_text_gate(path: Path) -> dict:
    result = review_text_study(path)
    if (result.get("review_status") != "PASS" or result.get("scenario") != MPP
            or result.get("chain_status") not in {"COMPLETE", "COMPLETE_WITH_MISSING", "STOPPED"}
            or result.get("model_execution_tier") !=
            "REAL_LLM_REMOTE_ZERO_PRICE_IF_COMPLETED"):
        raise FreeNativeBoundaryError("MPP text collection is not terminal and independently replayed")
    return result


def execute(output: Path, source_study: Path, marker_path: Path) -> dict:
    """No paid route, reroll, or fallback; preserve any partial native/model state."""
    frozen = frozen_assignment()
    source_review = _terminal_text_gate(source_study)
    marker = validate_marker(marker_path)
    blocks = _advancing_local_chain()
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise FreeNativeBoundaryError("OpenRouter credential unavailable")
    transport = OpenRouterTransport(key)
    output = Path(output).resolve()
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    _write(output / "assignment.json", frozen)
    _write(output / "source-text-collection.json", {
        "path": str(Path(source_study).resolve()),
        "review_sha256": sha256(_canonical(source_review)).hexdigest(),
        "review": source_review,
        "selection": "none; this native assignment was fixed before text outcomes",
        "billing_reconciliation": "NOT_CLAIMED; semantic PASS and terminal STOPPED do not resolve any unknown prior model charge"})
    _write(output / "chain-preflight.json", {
        "marker": marker, "advancing_blocks": list(blocks),
        "reused_mpp010_mechanism_only": True})
    completed = []
    for arm in ARMS:
        frozen_assignment()
        row = assigned_row(arm)
        directory = output / row.episode_id
        directory.mkdir(mode=0o700)
        guard = None
        try:
            prepare_overlay(directory, marker_path)
            service = FreeOrbitNativeService(directory.resolve(), row,
                overlay_dir=(directory / "native-overlay/protocols/mpp").resolve())
            asyncio.run(service.prepare())
            task = build_native_task(service)
            models = configure_free_models()
            guard = ZeroPriceModelGuard(directory / "model-calls.jsonl", transport)
            try:
                observed = guard.install(models, row)
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
            _verify_control_prompt_boundary(raw, arm)
            replayed_observed = review_guard_journal(directory / "model-calls.jsonl")
            if observed != replayed_observed:
                raise FreeNativeBoundaryError("durable zero-price calls differ from ORBIT boundary")
            verify_raw_model_boundary(raw, observed, row)
            if raw.samples[0].store.get("OpenMppStore:decision") is None:
                raise FreeNativeBoundaryError("native ORBIT row ended without a decision")
            from agent_economic_trust.mpp010_boundary import inspect_mixed_native_log
            decision, provenance = inspect_mixed_native_log(raw, service=service,
                                                              row=row, observed=observed)
            decision = bind_reasoning_provenance(decision, directory / "model-calls.jsonl")
            _write(directory / "decision.json", decision)
            compensation_path = directory / "compensation-evidence.json"
            asyncio.run(service._command(ROOT / "protocols/mpp/free-orbit-decision-preflight.mjs",
                directory / "decision.json", decision["selected_flow"]))
            asyncio.run(service._command(ROOT / "protocols/mpp/mpp010-meeting-local.mjs",
                directory / "decision.json", decision["selected_flow"], compensation_path))
            result = review_native(directory, arm)
            if result["status"] != "INDEPENDENT_NATIVE_AND_MODEL_REPLAY_PASS":
                raise FreeNativeBoundaryError("independent native reviewer did not pass")
            _write(directory / "independent-review.json", result)
            _write(directory / "COMPLETE.json", {
                "status": "EXPLORATORY_COMPLETE", "arm": arm,
                "episode_id": row.episode_id,
                "raw_model_events_sha256": provenance["raw_model_events_sha256"],
                "independent_review_sha256": sha256(_canonical(result)).hexdigest(),
                "model_execution_tier": "REAL_LLM_REMOTE_ZERO_PRICE_IF_COMPLETED",
                "transaction_execution_tier": "NATIVE_LOCAL_PROTOCOL",
                "scientific_mpp010_result_row": False})
            completed.append(row.episode_id)
        except BaseException as exc:
            _write(directory / "STOPPED.json", {
                "status": "EXPLORATORY_STOPPED", "arm": arm,
                "episode_id": row.episode_id,
                "error_type": type(exc).__name__,
                "model_calls_forwarded": guard.forwarded if guard is not None else 0,
                "unknown_charge_possible": bool(guard is not None and guard.stopped
                                                and guard.forwarded > guard.completed["provider"]
                                                + guard.completed["auditor"]),
                "later_rows_unattempted": list(ARMS[ARMS.index(arm) + 1:]),
                "no_retry": True})
            return {"status": "STOPPED", "completed_episode_ids": completed,
                    "stopped_episode_id": row.episode_id,
                    "later_arms_unattempted": list(ARMS[ARMS.index(arm) + 1:])}
    return {"status": "COMPLETE", "completed_episode_ids": completed,
            "planned_episodes": len(ARMS)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-study", type=Path)
    parser.add_argument("--chain-marker", type=Path)
    args = parser.parse_args()
    try:
        assignment = frozen_assignment()
        if not args.execute:
            print(json.dumps({"mode": "dry-run", "external_calls": 0,
                              "native_transactions": 0, "assignment": assignment},
                             indent=2, sort_keys=True))
            return 0
        if not all((args.output, args.source_study, args.chain_marker)):
            parser.error("--execute requires --output, --source-study, and --chain-marker")
        result = execute(args.output, args.source_study, args.chain_marker)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "COMPLETE" else 1
    except Exception as exc:
        # An HTTP exception may include request details or credentials.
        print("Free native ORBIT stopped: " + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
