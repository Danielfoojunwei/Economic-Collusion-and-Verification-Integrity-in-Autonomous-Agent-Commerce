#!/usr/bin/env python3
"""Zero-paid-call 004 controls: eight arm/truth paths plus real local payments."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = str(ROOT.parent / ".local/share")
os.environ["XDG_CACHE_HOME"] = str(ROOT.parent / ".cache")
os.environ["XDG_CONFIG_HOME"] = str(ROOT.parent / ".config")
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log
from agent_economic_trust.open004_plan import (EVAL_TOKEN_LIMIT, MAX_CALLS_PER_EPISODE,
    MAX_INPUT_BYTES, TASK_TOKEN_LIMIT, SCHEDULER_SECONDS, canonical, digest, make_schedule)
from agent_economic_trust.open004_remote import file_sha, free_x402_port
from agent_economic_trust.open004_task import (ControllerReceipt, audit_open004_log,
    invoice_case, open004_invoice_orbit, x402_access_callback)
from agent_economic_trust.remote import _safe_model_input_size
from scripts.freeze_open004 import source_inventory

OFFLINE_SEED = "a4" * 32
DEFAULT_OUTPUT = ROOT / "artifacts/gates/OPEN004/offline-invoice"


def _control_model(row, *, comply: bool, check: bool):
    # Reuse the frozen deterministic choice policy that already has independent
    # tool-grant tests. This is explicitly a scripted control, never LLM evidence.
    controls = runpy.run_path(str(ROOT / "tests/test_open004_task.py"))
    return controls["scripted_model"](row, comply_with_pressure=comply, check=check), controls["MODEL"]


def _run(row, path: Path, *, comply: bool, check: bool, callbacks: dict | None = None):
    model, model_id = _control_model(row, comply=comply, check=check)
    task = open004_invoice_orbit(row, scheduler_seconds=SCHEDULER_SECONDS,
        task_token_limit=TASK_TOKEN_LIMIT, model_call_limit=MAX_CALLS_PER_EPISODE,
        **(callbacks or {}))
    [log] = inspect_eval(task, model=model, log_dir=str(path), display="none",
        log_realtime=False, retry_on_error=0, max_retries=0,
        token_limit=EVAL_TOKEN_LIMIT, turn_limit=MAX_CALLS_PER_EPISODE,
        log_model_api=False)
    saved = read_eval_log(log.location, resolve_attachments=True)
    audit = audit_open004_log(saved, row, expected_model=model_id, require_bidirectional_control=True)
    score = saved.samples[0].scores["open004_score"].metadata
    events = [e for e in saved.samples[0].events if e.event == "model"]
    sizes = [_safe_model_input_size(e.input, e.tools) for e in events]
    if len(events) > MAX_CALLS_PER_EPISODE or max(sizes) > MAX_INPUT_BYTES:
        raise ValueError("offline control exceeds prospective model boundary")
    if score["V"] not in {"ACCEPT", "REJECT"}:
        raise ValueError("offline control did not execute a final verdict")
    return {"episode_id": row.episode_id, "model_id": model_id,
            "path": str(Path(log.location)), "sha256": file_sha(Path(log.location)),
            "model_events": len(events), "max_input_bytes": max(sizes), "verified": audit["status"]}


def offline(output: Path, *, native: bool = True) -> dict:
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError("refusing to replace existing offline readiness evidence")
    output.mkdir(parents=True, mode=0o700)
    rows = make_schedule(OFFLINE_SEED)
    controls = []
    for assigned in rows:
        row = assigned.task_episode()
        entry = _run(row, output / "scripted" / row.episode_id,
                     comply=row.arm.value == "COERCIVE_STRESS", check=row.arm.value != "COERCIVE_STRESS")
        entry["path"] = str(Path(entry["path"]).relative_to(output))
        controls.append(entry)
    native_controls = []
    if native:
        from agent_economic_trust.open004_native import Open004NativeController, verify_open004_native_evidence
        from agent_economic_trust.x402_invoice_adapter import InvoiceX402Controller
        from agent_economic_trust.x402_invoice_verifier import verify_purchase
        for label, truth, arm in (("GOOD_ACCEPT", "good", "OPEN"),
                                   ("BAD_ACCEPT", "bad", "COERCIVE_STRESS"),
                                   ("BAD_REJECT", "bad", "OPEN")):
            assigned = next(r for r in rows if r.truth == truth and r.arm == arm)
            row = assigned.task_episode()
            fixture, artifact = invoice_case(truth)
            path = output / "native" / label
            path.mkdir(parents=True)
            controller = InvoiceX402Controller(frozen_fixture=fixture, frozen_artifact=artifact,
                assignment_nonce=row.episode_id, obligation_id=row.obligation_id,
                output_dir=path / "x402", port=free_x402_port())
            access = x402_access_callback(controller)
            with Open004NativeController(row, fixture, artifact, path / "erc8183") as downstream:
                native_model = _run(row, path / "inspect", comply=label != "BAD_REJECT", check=label != "BAD_ACCEPT",
                     callbacks={"access_callback": access, "fund_callback": downstream.fund_side_term,
                                "settle_callback": downstream.settle_downstream})
            verify_open004_native_evidence(path / "erc8183")
            verify_purchase(path / "x402", frozen_fixture=fixture, frozen_artifact=artifact)
            evidence = path / "erc8183/native-evidence.json"
            native_controls.append({"control": label, "path": str(evidence.relative_to(output)),
                "sha256": file_sha(evidence),
                "episode_id": row.episode_id, "model_id": native_model["model_id"],
                "inspect_path": str(Path(native_model["path"]).relative_to(output)),
                "inspect_sha256": native_model["sha256"], "x402_directory": str((path / "x402").relative_to(output)),
                "scope": "SCRIPTED_NATIVE_CONTROL_NOT_ASSIGNED_MODEL_OUTCOME"})
    report = {"schema": "open004-offline-invoice-v1", "paid_model_calls": 0,
        "seed_hex": OFFLINE_SEED, "source_inventory_sha256": digest(source_inventory()),
        "scripted_controls": controls, "native_controls": native_controls,
        "model_behavior_tier": "SCRIPTED_SIMULATION",
        "native_transaction_tier": "NATIVE_LOCAL_PROTOCOL" if native else "UNRUN"}
    (output / "report.json").write_bytes(canonical(report) + b"\n")
    if native:
        from agent_economic_trust.open004_reporting import verify_offline_controls
        verify_offline_controls(output, report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--scripted-only", action="store_true")
    a = p.parse_args()
    r = offline(a.output, native=not a.scripted_only)
    print(json.dumps({"paid_model_calls": 0, "scripted_cells": len(r["scripted_controls"]),
                      "native_controls": len(r["native_controls"])}))


if __name__ == "__main__":
    main()
