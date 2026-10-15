#!/usr/bin/env python3
"""One-time private-calendar MPP assignment; no remote inference."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from agent_economic_trust.mpp005_plan import (  # noqa: E402
    CANONICAL_LEDGER_PATH, CONTINGENCY_USD, MAX_CALLS_PER_EPISODE, MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS,
    MODEL_ID, canonical, digest, make_schedule, manifest,
)
from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402
from agent_economic_trust.remote_pricing import pricing_snapshot, reserve_worst_case  # noqa: E402

GATE = ROOT / "artifacts/gates/MPP005"
ASSIGNMENT = GATE / "assignment-meeting-001"
LOCK = GATE / "one-time-freeze.lock.json"
NATIVE_BASELINE = ROOT / "artifacts/prospective/mpp-booking-service/zero-model-001"
IMAGE = "ghcr.io/tempoxyz/tempo-localnet@sha256:86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b"
CONTAINER = "open-mpp-booking-service-debug"


def sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing or symlinked source/evidence")
    return sha256(path.read_bytes()).hexdigest()


def source_inventory() -> dict[str, str]:
    """Seal the complete first-party Python and native MPP closure."""
    files = {"AGENTS.md", "UPSTREAM_PINNED.json",
             "protocols/mpp/package.json", "protocols/mpp/package-lock.json"}
    for folder, patterns in (("src/agent_economic_trust", ("*.py",)),
                             ("scripts", ("*.py", "*.mjs")),
                             ("protocols/mpp", ("*.mjs",)),
                             ("tests", ("test_mpp005*.py", "test_meeting_booking_native.py"))):
        for pattern in patterns:
            files.update(str(p.relative_to(ROOT)) for p in (ROOT / folder).rglob(pattern)
                         if p.is_file() and "node_modules" not in p.parts)
    return {name: sha(ROOT / name) for name in sorted(files)}


def runtime_pins() -> dict:
    from agent_economic_trust.meeting_generalization import ORBIT_COMMIT, verify_orbit_source
    verify_orbit_source()
    if version("orbit") != "1.0.3" or version("inspect_ai") != "0.3.263":
        raise ValueError("ORBIT/Inspect installed versions differ")
    node = shutil.which("node")
    if not node:
        raise ValueError("Node runtime missing")
    cmd = ["docker", "--host=unix:///var/run/docker.sock", "inspect", "--format",
           "{{.Config.Image}}|{{.State.Running}}|{{.Image}}", CONTAINER]
    process = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if process.returncode:
        raise ValueError("pinned loopback MPP container unavailable")
    image, running, image_id = process.stdout.strip().split("|")
    if image != IMAGE or running != "true" or not image_id.startswith("sha256:"):
        raise ValueError("MPP container image or state differs")
    installed = {}
    for package, expected in (("mppx", "0.13.4"), ("viem", "2.57.1")):
        path = ROOT / "protocols/mpp/node_modules" / package / "package.json"
        package_json = json.loads(path.read_bytes())
        if package_json.get("name") != package or package_json.get("version") != expected:
            raise ValueError("installed MPP SDK differs from lockfile pin")
        installed[package] = {"version": expected, "package_json_sha256": sha(path)}
    return {"orbit_commit": ORBIT_COMMIT, "orbit_version": version("orbit"),
            "inspect_ai_version": version("inspect_ai"), "node_sha256": sha(Path(node).resolve()),
            "mpp_image": IMAGE, "mpp_image_id": image_id,
            "mpp_package_lock_sha256": sha(ROOT / "protocols/mpp/package-lock.json"),
            "installed_mpp_sdk": installed,
            "container": CONTAINER, "rpc_url": "http://127.0.0.1:19567",
            "http_url": "http://127.0.0.1:19559", "chain_id": 1337}


def offline_readiness(sources: dict[str, str]) -> dict:
    """Independently reopen saved local receipts and mock-model actions."""
    from inspect_ai.log import read_eval_log
    from agent_economic_trust.meeting_booking_market import BookingMarket
    from agent_economic_trust.open_mpp_native_service import NativeMeetingService, inspect_native_service_log
    from agent_economic_trust.open_mpp_smoke import MODEL
    summary_path = NATIVE_BASELINE / "summary.json"
    summary = json.loads(summary_path.read_bytes())
    if summary.get("status") != "PASS" or summary.get("remote_model_calls") != 0 or len(summary.get("rows", [])) != 5:
        raise ValueError("native zero-model controls incomplete")
    checked = accepted_bad = honest_good = 0
    records = []
    for row in summary["rows"]:
        directory = NATIVE_BASELINE / row["trial_id"]
        logs = list((directory / "logs").glob("*.eval"))
        if len(logs) != 1:
            raise ValueError("native control lacks one Inspect archive")
        service = NativeMeetingService(directory.resolve())
        log = read_eval_log(str(logs[0]), resolve_attachments=True)
        decision = asyncio.run(inspect_native_service_log(log, service=service,
            quality=row["quality"], expected_model=MODEL))
        if decision["decision_sha256"] != row["decision_sha256"]:
            raise ValueError("native baseline action commitment differs")
        asyncio.run(service._command(ROOT / "protocols/mpp/verify-meeting-evidence.mjs",
                                    directory / "compensation-evidence.json"))
        checked += bool(row["check_debit_executed"])
        accepted_bad += row["quality"] == "BAD" and row["false_approval"] and decision["verdict"] == "ACCEPT"
        honest_good += row["quality"] == "GOOD" and decision["verdict"] == "ACCEPT"
        records.append({"trial_id": row["trial_id"], "inspect_sha256": sha(logs[0]),
                        "compensation_sha256": sha(directory / "compensation-evidence.json"),
                        "decision_sha256": decision["decision_sha256"]})
    if checked < 2 or accepted_bad != 1 or honest_good != 2:
        raise ValueError("native positive/negative controls differ")
    for arm in ("OPEN", "COERCIVE_STRESS"):
        market = BookingMarket("BAD", condition=arm)
        market.propose("provider", 10000, 20000, "scripted check feasibility probe")
        market.accept("auditor")
        if market.check("auditor")["status"] != "FAIL":
            raise ValueError("BAD paid check unavailable or incorrect")
    return {"status": "PASS", "model_calls": 0,
            "baseline_summary_sha256": sha(summary_path), "native_control_records": records,
            "native_controls_reopened": 5, "feasible_check_both_arms": True,
            "source_inventory_sha256": digest(sources)}


def _ledger() -> dict:
    state = BudgetLedger(CANONICAL_LEDGER_PATH).snapshot()
    if state["cap_usd"] != "50" or state["blocked"] or state["unknown_run_ids"]:
        raise ValueError("shared USD50 lifetime ledger blocked")
    return state


def _ancestor(frozen: dict) -> dict:
    state = _ledger()
    lines = CANONICAL_LEDGER_PATH.read_bytes().splitlines()
    if state["seq"] < frozen["seq"] or json.loads(lines[frozen["seq"]])["hash"] != frozen["last_hash"]:
        raise ValueError("frozen ledger head is not a current ancestor")
    return state


def _new(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def load_assignment(directory: Path = ASSIGNMENT) -> tuple[dict, str, tuple]:
    seed = (directory / "seed.hex").read_text().strip()
    rows = make_schedule(seed)
    expected = manifest(seed, rows)
    path = directory / "assignment_manifest.json"
    frozen = json.loads(path.read_bytes())
    if any(frozen.get(k) != v for k, v in expected.items()):
        raise ValueError("MPP005 manifest differs from seeded assignment")
    if json.loads((directory / "private_episodes.json").read_bytes()) != [asdict(r) for r in rows]:
        raise ValueError("MPP005 private assignment differs")
    lock = json.loads((directory.parent / LOCK.name).read_bytes())
    if lock != {"schema": "mpp005-one-time-freeze-v1",
                "assignment_manifest_sha256": sha(path),
                "seed_commitment_sha256": expected["seed_commitment_sha256"]}:
        raise ValueError("MPP005 one-time freeze lock differs")
    return frozen, sha(path), rows


def freeze(*, seed_hex: str | None = None) -> dict:
    if LOCK.exists() or ASSIGNMENT.exists():
        raise FileExistsError("MPP005 already or partially frozen; no reroll")
    seed_hex = secrets.token_hex(32) if seed_hex is None else seed_hex
    rows = make_schedule(seed_hex)
    payload = manifest(seed_hex, rows)
    sources = source_inventory()
    pins = runtime_pins()
    offline = offline_readiness(sources)
    rates = pricing_snapshot(MODEL_ID)
    one = reserve_worst_case(rates, MAX_CALLS_PER_EPISODE, MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS)
    ledger = _ledger()
    full = one * len(rows) + Decimal(CONTINGENCY_USD)
    if full > Decimal(ledger["available_usd"]):
        raise ValueError("full MPP005 worst-case block plus contingency exceeds USD50 headroom")
    payload.update(source_sha256=sources, runtime_pins=pins, offline_readiness=offline,
                   public_pricing_snapshot=rates,
                   budget_at_freeze={k: ledger[k] for k in ("seq", "last_hash", "cap_usd", "available_usd")},
                   worst_case_reserve_usd_per_episode=str(one),
                   worst_case_reserve_usd_full_block=str(one * len(rows)))
    GATE.mkdir(parents=True, exist_ok=True)
    raw = canonical(payload) + b"\n"
    _new(LOCK, canonical({"schema": "mpp005-one-time-freeze-v1",
         "assignment_manifest_sha256": sha256(raw).hexdigest(),
         "seed_commitment_sha256": payload["seed_commitment_sha256"]}) + b"\n")
    ASSIGNMENT.mkdir(mode=0o700)
    _new(ASSIGNMENT / "seed.hex", (seed_hex + "\n").encode())
    _new(ASSIGNMENT / "private_episodes.json", canonical([asdict(r) for r in rows]) + b"\n")
    _new(ASSIGNMENT / "assignment_manifest.json", raw)
    return {"status": "FROZEN_NOT_EXECUTED", "planned_episodes": len(rows),
            "assignment_manifest_sha256": sha256(raw).hexdigest(),
            "worst_case_block_usd": str(one * len(rows)), "model_calls": 0}


def verify() -> dict:
    frozen, assignment_sha, rows = load_assignment()
    sources = source_inventory()
    if frozen["source_sha256"] != sources:
        raise ValueError("MPP005 executable source changed")
    if frozen["runtime_pins"] != runtime_pins():
        raise ValueError("MPP005 native/runtime pin changed")
    if frozen["offline_readiness"] != offline_readiness(sources):
        raise ValueError("MPP005 offline control evidence changed")
    one = reserve_worst_case(frozen["public_pricing_snapshot"],
                             MAX_CALLS_PER_EPISODE, MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS)
    if frozen["worst_case_reserve_usd_per_episode"] != str(one) or frozen["worst_case_reserve_usd_full_block"] != str(one * len(rows)):
        raise ValueError("MPP005 frozen reservation differs")
    _ancestor(frozen["budget_at_freeze"])
    return {"status": "PASS", "assignment_manifest_sha256": assignment_sha,
            "planned_episodes": len(rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "verify", "readiness"))
    args = parser.parse_args()
    if args.command == "freeze":
        answer = freeze()
    elif args.command == "verify":
        answer = verify()
    else:
        sources = source_inventory()
        answer = {"runtime_pins": runtime_pins(), "offline": offline_readiness(sources),
                  "ledger": {k: _ledger()[k] for k in ("seq", "available_usd", "cap_usd")},
                  "would_freeze": not LOCK.exists()}
    print(json.dumps(answer, sort_keys=True))


if __name__ == "__main__":
    main()
