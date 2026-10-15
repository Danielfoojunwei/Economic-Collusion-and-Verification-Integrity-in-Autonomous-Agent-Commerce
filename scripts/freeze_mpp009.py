#!/usr/bin/env python3
"""Prospective ten-row MPP009 freeze and read-only readiness; never run models."""
from __future__ import annotations

import argparse
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

from agent_economic_trust.mpp009_budget import budget_preflight, required_headroom
from agent_economic_trust.mpp008_budget import mpp006_contingent_exposure
from agent_economic_trust.mpp009_plan import (
    CANONICAL_LEDGER_PATH, MAX_INPUT_BYTES, STUDY_ID, canonical, digest,
    full_block_reserve, make_schedule, manifest, refreshed_catalog, reserve_pair,
)
from agent_economic_trust.remote_budget import BudgetLedger
from scripts.freeze_mpp005 import _ancestor, _new, sha
from scripts.freeze_mpp008 import source_inventory as mpp008_source_inventory


GATE = ROOT / "artifacts/gates/MPP009"
PROJECT_ROOT = CANONICAL_LEDGER_PATH.parents[2]
ASSIGNMENT = GATE / "assignment-001"
RUNS = GATE / "runs-001"
LOCK = GATE / "one-time-freeze.lock.json"
CLEARANCE = GATE / "cross-study-clearance.json"
AP2_GATE = PROJECT_ROOT / "artifacts/gates/AP2_LIVE"
AP2_V2_GATE = PROJECT_ROOT / "artifacts/gates/AP2_LIVE_V2"
AP2_V2_ASSIGNMENT_SHA256 = "79e039bab397a0cbc9c50186cdf68fdb458f3fb0df76fd288ad0db332fa1d6ce"
AP2_V2_LOCK_SHA256 = "49eb58d6f4d9e5679bec9307d07d2777eb3bb81d7fd8011ce2662fa7da942933"
AP2_V2_FINAL_COLLECTION_SHA256 = "73e2261ed2cfb10941b6867b476e7820dc72a15ed5cccba94d6ae541763b701a"
AP2_V2_FINAL_LEDGER_SEQ = 145
AP2_V2_FINAL_LEDGER_HASH = "ec60ee56530c226c87c0b43e60718d93307206d27e8c54abcc745fd62c8035ba"
AP2_V2_FINAL_EPISODE_RECORD_SHA256 = {
    "ap2live2-4dac18e8f1bc22d551ece718": "ce553d78276ba5b91ca4a31524ff3d0995188799752e59feb3b24778bcf64b68",
    "ap2live2-9b3a2e4c73fbc890506ec424": "e0d0f5ccb58b4110cc9ba1aab595b31fa7aa5514b1ad6f7f8efa8c046a709c18",
    "ap2live2-67aea2ccc058779f370dcc20": "91b7da883738d946bb0e74886a78f536e204f825adc425ca72be2b1067bdee10",
    "ap2live2-93956fe860c0756c828249ed": "10a1c2f7e967fccf7e47328c1287cb7273f8fbefc8188a044a05671d76dee003",
}
MPP008_GATE = PROJECT_ROOT / "artifacts/gates/MPP008"
OFFLINE = ROOT / "artifacts/prospective/mpp009-scripted-native-001"
CONTAINER = "mpp009-pressure-localnet"
IMAGE = ("ghcr.io/tempoxyz/tempo-localnet@sha256:"
         "86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b")

# MPP008's inventory includes the inherited first-party import closure. Add
# every versioned MPP009 entrypoint and native helper, including the collector.
NEW_SOURCE = (
    "docs/PROSPECTIVE_MPP_PRESSURE_009.md",
    "docs/MPP009_IMPLEMENTATION_STATUS.md",
    "src/agent_economic_trust/mpp009_plan.py",
    "src/agent_economic_trust/mpp009_budget.py",
    "src/agent_economic_trust/mpp009_market.py",
    "src/agent_economic_trust/mpp009_orbit.py",
    "src/agent_economic_trust/mpp009_task.py",
    "src/agent_economic_trust/mpp009_boundary.py",
    "src/agent_economic_trust/mpp009_native_service.py",
    "src/agent_economic_trust/mpp009_remote.py",
    "src/agent_economic_trust/mpp009_reporting.py",
    "scripts/freeze_mpp009.py",
    "scripts/run_mpp009.py",
    "scripts/collect_mpp009.py",
    "scripts/run_mpp009_offline_native.py",
    "tests/test_mpp009_pressure.py",
    "tests/test_mpp009_offline_native.py",
    "tests/test_mpp009_runner.py",
    "tests/test_mpp009_clearance.py",
    "protocols/mpp/mpp009-meeting-service.mjs",
    "protocols/mpp/mpp009-verify-meeting-service.mjs",
    "protocols/mpp/mpp009-meeting-local.mjs",
    "protocols/mpp/mpp009-verify-meeting-evidence.mjs",
    "protocols/mpp/mpp009-decision-preflight.mjs",
)


def source_inventory() -> dict[str, str]:
    result = mpp008_source_inventory()
    for name in NEW_SOURCE:
        result[name] = sha(ROOT / name)
    return dict(sorted(result.items()))


def canonical_checkout_preflight() -> dict:
    """Allow freeze and paid-row validation only in the committed project root."""
    if ROOT.resolve() != PROJECT_ROOT.resolve():
        raise ValueError("MPP009 source root is not the canonical project checkout")
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=ROOT,
                         capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    if Path(top).resolve() != PROJECT_ROOT.resolve():
        raise ValueError("MPP009 Git checkout differs from canonical project root")
    changed = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                             cwd=ROOT, capture_output=True, text=True,
                             check=True, timeout=10).stdout.strip()
    if changed:
        raise ValueError("MPP009 tracked source must be committed before freeze or paid row")
    sources = source_inventory()
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", "--", *sources],
                             cwd=ROOT, capture_output=True, text=True, timeout=10)
    if tracked.returncode:
        raise ValueError("MPP009 source inventory includes an untracked path")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    return {"source_commit": commit, "source_sha256": sources}


def runtime_pins() -> dict:
    """Pin the dedicated bare MPP009 chain, official runtime and local SDKs."""
    from agent_economic_trust.meeting_generalization import ORBIT_COMMIT, verify_orbit_source

    verify_orbit_source()
    if version("orbit") != "1.0.3" or version("inspect_ai") != "0.3.263":
        raise ValueError("ORBIT/Inspect installed versions differ")
    node = shutil.which("node")
    if not node:
        raise ValueError("Node runtime missing")
    docker_env = os.environ.copy()
    for selector in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY",
                     "DOCKER_CERT_PATH"):
        docker_env.pop(selector, None)
    result = subprocess.run(["docker", "--host=unix:///var/run/docker.sock", "inspect",
                             CONTAINER], capture_output=True, text=True, timeout=15, env=docker_env)
    if result.returncode:
        raise ValueError("dedicated MPP009 localnet container unavailable")
    container, = json.loads(result.stdout)
    bindings = container["HostConfig"]["PortBindings"].get("8545/tcp")
    if (container["Config"]["Image"] != IMAGE or container["State"]["Running"] is not True
            or container["Config"]["Cmd"] != ["--bare", "--block-time", "100ms"]
            or bindings != [{"HostIp": "127.0.0.1", "HostPort": "19667"}]
            or not container["Image"].startswith("sha256:")):
        raise ValueError("dedicated MPP009 bare localnet image, flags or port differs")
    installed = {}
    for package, expected in (("mppx", "0.13.4"), ("viem", "2.57.1")):
        path = ROOT / "protocols/mpp/node_modules" / package / "package.json"
        package_json = json.loads(path.read_bytes())
        if package_json.get("name") != package or package_json.get("version") != expected:
            raise ValueError("installed MPP SDK differs from lockfile")
        installed[package] = {"version": expected, "package_json_sha256": sha(path)}
    from agent_economic_trust.mpp009_remote import dedicated_chain_preflight
    chain = dedicated_chain_preflight()
    return {"orbit_commit": ORBIT_COMMIT, "orbit_version": version("orbit"),
            "inspect_ai_version": version("inspect_ai"), "node_sha256": sha(Path(node).resolve()),
            "mpp_image": IMAGE, "mpp_image_id": container["Image"],
            "mpp_package_lock_sha256": sha(ROOT / "protocols/mpp/package-lock.json"),
            "installed_mpp_sdk": installed,
            "container": CONTAINER,
            "rpc_url": "http://127.0.0.1:19667",
            "http_url": "http://127.0.0.1:19659", "chain_id": 1337,
            "bare": True, "chain_readiness": chain}


def offline_readiness() -> dict:
    """Require the saved nine-case local report to pass its own read-only verifier."""
    from scripts.run_mpp009_offline_native import verify_offline_report

    summary = verify_offline_report(OFFLINE / "summary.json")
    if (summary.get("status") != "PASS"
            or summary.get("remote_model_calls") != 0
            or summary.get("max_serialized_input_bytes", MAX_INPUT_BYTES + 1) > MAX_INPUT_BYTES
            or summary.get("verified_controls") != 9
            or summary.get("verified_tamper_negatives", 0) < 3):
        raise ValueError("MPP009 nine-case zero-model native readiness is incomplete")
    return {"status": "PASS", "summary_sha256": sha(OFFLINE / "summary.json"),
            "max_serialized_input_bytes": summary["max_serialized_input_bytes"],
            "scripted_cases": 9, "remote_model_calls": 0}


def ap2_v2_final_evidence(state: dict) -> dict:
    """Bind the completed AP2 v2 denominator to immutable rows and ledger."""
    assignment = AP2_V2_GATE / "assignment-001/assignment_manifest.json"
    lock = AP2_V2_GATE / "first-freeze.lock.json"
    collection = AP2_V2_GATE / "collection-001-final.json"
    if any(not path.is_file() or path.is_symlink()
           for path in (assignment, lock, collection)):
        raise ValueError("AP2 v2 final assignment, freeze lock or collection is absent or changed")
    if (sha(assignment) != AP2_V2_ASSIGNMENT_SHA256
            or sha(lock) != AP2_V2_LOCK_SHA256
            or sha(collection) != AP2_V2_FINAL_COLLECTION_SHA256):
        raise ValueError("AP2 v2 final assignment, freeze lock or collection is absent or changed")
    frozen = json.loads(assignment.read_bytes())
    sealed = json.loads(lock.read_bytes())
    report = json.loads(collection.read_bytes())
    assigned = frozen.get("public_rows")
    results = report.get("rows")
    if (frozen.get("schema") != "ap2-live-prospective-assignment-v2"
            or frozen.get("study_id") != "ap2-audit-purchase-invoice-release-live-002"
            or frozen.get("planned_episodes") != 4
            or not isinstance(assigned, list) or len(assigned) != 4
            or sealed.get("schema") != "ap2-live-v2-first-freeze-v1"
            or sealed.get("assignment_manifest_sha256") != AP2_V2_ASSIGNMENT_SHA256
            or sealed.get("paid_model_calls") != 0
            or report.get("schema") != "ap2-live-itt-collection-v2"
            or report.get("study_id") != frozen["study_id"]
            or report.get("assignment_manifest_sha256") != AP2_V2_ASSIGNMENT_SHA256
            or (report.get("planned_episodes"), report.get("completed_episodes"),
                report.get("stopped_episodes"), report.get("pending_episodes"))
               != (4, 4, 0, 0)
            or report.get("shared_ledger_seq") != AP2_V2_FINAL_LEDGER_SEQ
            or not isinstance(results, list) or len(results) != 4
            or [item.get("episode_id") for item in results] !=
               [item.get("episode_id") for item in assigned]
            or len({item.get("episode_id") for item in assigned}) != 4
            or set(AP2_V2_FINAL_EPISODE_RECORD_SHA256) !=
               {item.get("episode_id") for item in assigned}
            or any(item.get("status") != "COMPLETE" for item in results)):
        raise ValueError("AP2 v2 final assigned denominator is not four COMPLETE rows")
    if state["seq"] < AP2_V2_FINAL_LEDGER_SEQ:
        raise ValueError("AP2 v2 final ledger head is absent")
    if state["seq"] == AP2_V2_FINAL_LEDGER_SEQ:
        final_hash = state["last_hash"]
    else:
        lines = CANONICAL_LEDGER_PATH.read_bytes().splitlines()
        if len(lines) <= AP2_V2_FINAL_LEDGER_SEQ:
            raise ValueError("AP2 v2 final ledger ancestor is absent")
        final_hash = json.loads(lines[AP2_V2_FINAL_LEDGER_SEQ])["hash"]
    if final_hash != AP2_V2_FINAL_LEDGER_HASH:
        raise ValueError("AP2 v2 final ledger ancestor changed")
    runs = state["runs"]
    expected_runs = set()
    settled = []
    episodes = AP2_V2_GATE / "runs-001/episodes"
    if (not episodes.is_dir() or episodes.is_symlink()
            or {path.name for path in episodes.iterdir()} !=
               {item["episode_id"] for item in assigned}):
        raise ValueError("AP2 v2 run directory differs from four assigned rows")
    for public, result in zip(assigned, results, strict=True):
        episode_id = public["episode_id"]
        directory = episodes / episode_id
        if (not directory.is_dir() or directory.is_symlink()
                or (directory / "STOPPED.json").exists()):
            raise ValueError("AP2 v2 final row is stopped or missing")
        record_path = directory / "episode_record.json"
        if sha(record_path) != AP2_V2_FINAL_EPISODE_RECORD_SHA256[episode_id]:
            raise ValueError("AP2 v2 final episode record changed since collection")
        record = json.loads(record_path.read_bytes())
        inspect_sha = sha(directory / "inspect.eval")
        purchase_sha = sha(directory / "audit-purchase/native-audit-purchase.json")
        native_sha = sha(directory / "erc8183/native-evidence.json")
        ident = f"ap2live2-{AP2_V2_ASSIGNMENT_SHA256[:12]}-{episode_id}"
        billed = runs.get(ident)
        expected_runs.add(ident)
        if (record.get("schema") != "ap2-live-paid-episode-v2"
                or record.get("status") != "COMPLETE"
                or record.get("episode_id") != episode_id
                or record.get("assignment_manifest_sha256") != AP2_V2_ASSIGNMENT_SHA256
                or record.get("ledger_run_id") != ident
                or record.get("inspect_sha256") != inspect_sha
                or record.get("native_purchase_sha256") != purchase_sha
                or record.get("native_erc8183_sha256") != native_sha
                or not isinstance(billed, dict) or billed.get("status") != "SETTLED"
                or billed.get("evidence_ref") != "sha256:" + inspect_sha
                or Decimal(billed["actual_usd"]) != Decimal(record["model_cost_usd"])
                or Decimal(result["model_cost_usd"]) != Decimal(record["model_cost_usd"])):
            raise ValueError("AP2 v2 final row, native evidence or settled billing differs")
        settled.append({"episode_id": episode_id, "ledger_run_id": ident,
                        "episode_record_sha256": sha(record_path),
                        "inspect_sha256": inspect_sha,
                        "native_purchase_sha256": purchase_sha,
                        "native_erc8183_sha256": native_sha,
                        "settled_model_cost_usd": billed["actual_usd"]})
    if any(name.startswith("ap2live2-") and name not in expected_runs for name in runs):
        raise ValueError("unassigned AP2 v2 ledger run exists")
    return {"ap2_v2_disposition": "COMPLETE_NO_PENDING",
            "ap2_v2_assignment_sha256": AP2_V2_ASSIGNMENT_SHA256,
            "ap2_v2_freeze_lock_sha256": AP2_V2_LOCK_SHA256,
            "ap2_v2_final_collection_sha256": AP2_V2_FINAL_COLLECTION_SHA256,
            "ap2_v2_final_ledger_seq": AP2_V2_FINAL_LEDGER_SEQ,
            "ap2_v2_final_ledger_hash": AP2_V2_FINAL_LEDGER_HASH,
            "ap2_v2_settled_runs": settled}


def cross_study_clearance(state: dict, *, budget_head: dict | None = None) -> dict:
    """Require explicit sequencing while MPP008 and AP2 share one USD50 cap.

    This is an evidence-bound research allocation record, not a new spending
    authorization. It must be prepared separately after AP2 priority is
    resolved; an absent or stale record makes freeze fail closed.
    """
    ap2_v2_final = ap2_v2_final_evidence(state)
    if not CLEARANCE.is_file() or CLEARANCE.is_symlink():
        raise ValueError("MPP009 cross-study sequencing record is absent")
    from scripts.freeze_mpp008 import load_assignment as load_mpp008

    mpp008, assignment_sha, _ = load_mpp008()
    first = mpp008["execution_order"][0]
    published_mpp008 = MPP008_GATE / "assignment-mixed-001/assignment_manifest.json"
    if sha(published_mpp008) != assignment_sha:
        raise ValueError("canonical MPP008 assignment differs from isolated source")
    stopped = MPP008_GATE / "runs-mixed-001/episodes" / first / "STOPPED.json"
    if not stopped.is_file() or stopped.is_symlink():
        raise ValueError("MPP008 first row is not documented STOPPED")
    saved = json.loads(stopped.read_bytes())
    if (saved.get("episode_id") != first
            or saved.get("assignment_manifest_sha256") != assignment_sha
            or saved.get("no_retry_or_substitution") is not True):
        raise ValueError("MPP008 stop evidence does not end its executable block")
    ap2_assignment = AP2_GATE / "assignment-001/assignment_manifest.json"
    ap2_collection = AP2_GATE / "collection-001-after-first-stop.json"
    if not (AP2_GATE / "first-freeze.lock.json").is_file():
        raise ValueError("AP2 original freeze lock missing")
    ap2 = json.loads(ap2_collection.read_bytes())
    if (ap2.get("assignment_manifest_sha256") != sha(ap2_assignment)
            or ap2.get("planned_episodes") != 4
            or ap2.get("completed_episodes") != 0
            or ap2.get("stopped_episodes") != 1
            or ap2.get("pending_episodes") != 3):
        raise ValueError("AP2 original stopped denominator differs")
    ap2_first = ap2["rows"][0]["episode_id"]
    ap2_stopped = AP2_GATE / "runs-001/episodes" / ap2_first / "STOPPED.json"
    ap2_stop = json.loads(ap2_stopped.read_bytes())
    if (ap2_stop.get("assignment_manifest_sha256") != sha(ap2_assignment)
            or ap2_stop.get("episode_id") != ap2_first
            or ap2_stop.get("no_retry_or_substitution") is not True
            or state["runs"].get(ap2_stop.get("ledger_run_id"), {}).get("status") != "SETTLED"):
        raise ValueError("AP2 first stop or billing differs from canonical ledger")
    record = json.loads(CLEARANCE.read_bytes())
    budget_head = state if budget_head is None else budget_head
    expected = {
        "schema": "mpp009-cross-study-clearance-v2",
        "study_id": STUDY_ID,
        "decision": "MPP009_PRIORITY_AFTER_AP2_V2_COMPLETION",
        "ap2_original_disposition": "STOPPED_NO_RETRY",
        "ap2_original_assignment_sha256": sha(ap2_assignment),
        "ap2_original_collection_sha256": sha(ap2_collection),
        "ap2_first_stopped_sha256": sha(ap2_stopped),
        "mpp008_disposition": "STOPPED_NO_RETRY",
        "mpp008_assignment_sha256": assignment_sha,
        "mpp008_first_stopped_sha256": sha(stopped),
        "ledger_seq": budget_head["seq"],
        "ledger_last_hash": budget_head["last_hash"],
        "ledger_available_usd": budget_head["available_usd"],
        **ap2_v2_final,
    }
    if record != expected:
        raise ValueError("MPP009 cross-study clearance differs from current evidence or ledger")
    return {**record, "sha256": sha(CLEARANCE)}


def _reserves(prices: dict, rows: tuple) -> dict[str, Decimal]:
    result = {row.episode_id: reserve_pair(prices, row.provider_model_id,
                                           row.auditor_model_id) for row in rows}
    if sum(result.values(), Decimal(0)) != full_block_reserve(prices, rows):
        raise ValueError("MPP009 ten-row reserve differs from full-block calculation")
    return result


def load_assignment(directory: Path = ASSIGNMENT) -> tuple[dict, str, tuple]:
    directory = Path(directory)
    if directory.resolve() != ASSIGNMENT.resolve():
        raise ValueError("MPP009 assignment path differs from canonical freeze")
    seed = (directory / "seed.hex").read_text().strip()
    rows = make_schedule(seed)
    expected = manifest(seed, rows)
    path = directory / "assignment_manifest.json"
    frozen = json.loads(path.read_bytes())
    if any(frozen.get(key) != value for key, value in expected.items()):
        raise ValueError("MPP009 assignment differs from seeded schedule")
    if json.loads((directory / "private_episodes.json").read_bytes()) != [asdict(row) for row in rows]:
        raise ValueError("MPP009 private truth differs from seeded schedule")
    if json.loads(LOCK.read_bytes()) != {
            "schema": "mpp009-one-time-freeze-v1",
            "assignment_manifest_sha256": sha(path),
            "seed_commitment_sha256": expected["seed_commitment_sha256"]}:
        raise ValueError("MPP009 one-time freeze lock differs")
    return frozen, sha(path), rows


def freeze(*, seed_hex: str | None = None) -> dict:
    """Write the ten cells once, only after all local and cross-study gates pass."""
    checkout = canonical_checkout_preflight()
    if LOCK.exists() or ASSIGNMENT.exists():
        raise FileExistsError("MPP009 already or partially frozen; no reroll")
    state = BudgetLedger(CANONICAL_LEDGER_PATH).snapshot()
    clearance = cross_study_clearance(state)
    exposure = mpp006_contingent_exposure(state)
    sources = checkout["source_sha256"]
    pins = runtime_pins()
    offline = offline_readiness()
    prices = refreshed_catalog()
    seed_hex = secrets.token_hex(32) if seed_hex is None else seed_hex
    rows = make_schedule(seed_hex)
    reserves = _reserves(prices, rows)
    budget = budget_preflight(state, reserves)
    payload = manifest(seed_hex, rows)
    payload.update(source_sha256=sources, source_commit=checkout["source_commit"],
                   runtime_pins=pins,
                   offline_readiness=offline, cross_study_clearance=clearance,
                   public_pricing_snapshots=prices,
                   budget_at_freeze={key: state[key] for key in
                                     ("seq", "last_hash", "cap_usd", "available_usd")},
                   prior_mpp006_contingent_exposure=exposure,
                   required_headroom_usd=budget["required_headroom_usd"],
                   worst_case_reserve_usd_by_episode={key: str(value)
                       for key, value in reserves.items()},
                   worst_case_reserve_usd_full_block=budget["full_block_reserve_usd"])
    GATE.mkdir(parents=True, exist_ok=True)
    raw = canonical(payload) + b"\n"
    _new(LOCK, canonical({"schema": "mpp009-one-time-freeze-v1",
        "assignment_manifest_sha256": sha256(raw).hexdigest(),
        "seed_commitment_sha256": payload["seed_commitment_sha256"]}) + b"\n")
    ASSIGNMENT.mkdir(mode=0o700)
    _new(ASSIGNMENT / "seed.hex", (seed_hex + "\n").encode())
    _new(ASSIGNMENT / "private_episodes.json",
         canonical([asdict(row) for row in rows]) + b"\n")
    _new(ASSIGNMENT / "assignment_manifest.json", raw)
    return {"status": "FROZEN_NOT_EXECUTED", "planned_episodes": 10,
            "assignment_manifest_sha256": sha256(raw).hexdigest(),
            "required_headroom_usd": budget["required_headroom_usd"], "model_calls": 0}


def verify_static() -> dict:
    checkout = canonical_checkout_preflight()
    frozen, assignment_sha, rows = load_assignment()
    if frozen["source_sha256"] != checkout["source_sha256"]:
        raise ValueError("MPP009 executable source changed after freeze")
    if frozen["runtime_pins"] != runtime_pins():
        raise ValueError("MPP009 runtime pin changed after freeze")
    reserves = _reserves(frozen["public_pricing_snapshots"], rows)
    if (frozen["worst_case_reserve_usd_by_episode"] != {
                key: str(value) for key, value in reserves.items()}
            or frozen["worst_case_reserve_usd_full_block"] !=
                str(sum(reserves.values(), Decimal(0)))
            or frozen["required_headroom_usd"] != str(required_headroom(reserves))):
        raise ValueError("MPP009 frozen reservation or residual differs")
    current = _ancestor(frozen["budget_at_freeze"])
    if frozen["cross_study_clearance"] != cross_study_clearance(
            current, budget_head=frozen["budget_at_freeze"]):
        raise ValueError("MPP009 cross-study sequencing evidence changed")
    if frozen["prior_mpp006_contingent_exposure"] != mpp006_contingent_exposure(current):
        raise ValueError("MPP006 contingent exposure changed after MPP009 freeze")
    return {"status": "PASS", "assignment_manifest_sha256": assignment_sha,
            "planned_episodes": len(rows), "model_calls": 0}


def verify() -> dict:
    result = verify_static()
    frozen, _, _ = load_assignment()
    if frozen["offline_readiness"] != offline_readiness():
        raise ValueError("MPP009 zero-model readiness evidence changed")
    return result


def readiness() -> dict:
    """Report blockers without creating an assignment or reserving a dollar."""
    checks: dict[str, str] = {}
    try:
        canonical_checkout_preflight()
        checks["canonical_checkout"] = "PASS"
    except Exception as exc:
        checks["canonical_checkout"] = type(exc).__name__ + ": " + str(exc)
    if LOCK.exists() or ASSIGNMENT.exists():
        checks["one_time_freeze"] = "ALREADY_FROZEN_OR_PARTIAL"
    try:
        state = BudgetLedger(CANONICAL_LEDGER_PATH).snapshot()
        checks["ledger"] = "PASS"
    except Exception as exc:
        state = None
        checks["ledger"] = type(exc).__name__
    for name, operation in (
        ("source", source_inventory), ("runtime", runtime_pins),
        ("offline", offline_readiness), ("catalog", refreshed_catalog),
    ):
        try:
            value = operation()
            checks[name] = "PASS"
            if name == "catalog":
                prices = value
        except Exception as exc:
            checks[name] = type(exc).__name__ + ": " + str(exc)
    if state is not None:
        try:
            cross_study_clearance(state)
            checks["cross_study"] = "PASS"
        except Exception as exc:
            checks["cross_study"] = type(exc).__name__ + ": " + str(exc)
        if checks.get("catalog") == "PASS":
            try:
                rows = make_schedule("ab" * 32)
                reserves = _reserves(prices, rows)
                budget = budget_preflight(state, reserves)
                checks["budget"] = "PASS"
            except Exception as exc:
                checks["budget"] = type(exc).__name__ + ": " + str(exc)
    else:
        budget = None
    return {"status": "READY" if checks and all(v == "PASS" for v in checks.values())
            else "BLOCKED", "would_freeze": bool(checks) and all(v == "PASS" for v in checks.values()),
            "checks": checks, "budget": budget if checks.get("budget") == "PASS" else None,
            "model_calls": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("readiness", "freeze", "verify"))
    args = parser.parse_args()
    result = {"readiness": readiness, "freeze": freeze, "verify": verify}[args.command]()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
