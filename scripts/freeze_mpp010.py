#!/usr/bin/env python3
"""Prospective ten-row MPP010 freeze and read-only readiness; never run models."""
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

from agent_economic_trust.mpp010_budget import budget_preflight, required_headroom
from agent_economic_trust.mpp008_budget import mpp006_contingent_exposure
from agent_economic_trust.mpp010_plan import (
    CANONICAL_LEDGER_PATH, MAX_INPUT_BYTES, STUDY_ID, canonical, digest,
    full_block_reserve, make_schedule, manifest, refreshed_catalog, reserve_pair,
)
from agent_economic_trust.remote_budget import BudgetLedger
from scripts.freeze_mpp005 import _ancestor, _new, sha
from scripts.freeze_mpp008 import source_inventory as mpp008_source_inventory


GATE = ROOT / "artifacts/gates/MPP010"
PROJECT_ROOT = CANONICAL_LEDGER_PATH.parents[2]
ASSIGNMENT = GATE / "assignment-001"
RUNS = GATE / "runs-001"
LOCK = GATE / "one-time-freeze.lock.json"
CLEARANCE = GATE / "cross-study-clearance.json"
MPP009_GATE = PROJECT_ROOT / "artifacts/gates/MPP009"
MPP009_ASSIGNMENT_SHA256 = "a406280cf0619ea70e9901bd88f79af793a260fb199857f1a82a60a724d2239e"
MPP009_LOCK_SHA256 = "5244618512fb9bed10e0928da14e97ed747c846bdbefdc8cdc2dbbfe557249f8"
MPP009_COLLECTION_SHA256 = "942fac731930ac77d79a2a40be048ca666c4c1cac39426d27b11ec4b88536b29"
MPP009_FIRST_EPISODE_ID = "mpp009-bad064fc4d3fd2a6d4d74118"
MPP009_FIRST_STOP_SHA256 = "1c6b12257c1b879961a5d40ba406a0002b7431e3b79568b3deace5220a50b0da"
MPP009_FIRST_RUN_ID = "mpp009-a406280cf061-mpp009-bad064fc4d3fd2a6d4d74118"
MPP009_FIRST_RAW_SHA256 = "60e9f9838fe05c7e66ab4b1284cd281afe4360b19f2c218365c25fb687768cb7"
MPP009_FINAL_LEDGER_SEQ = 147
MPP009_FINAL_LEDGER_HASH = "e1b94c98a463811680f4947f0a4c6f29b6e730bc654e3fb83023301422357109"
BASELINE_GATE_INVENTORY_SHA256 = "e5ecf74567fea024fbc103235ad7e525aacef36dba7626b6a5c09b37d3571cca"
BASELINE_GATE_PATHS = tuple("artifacts/gates/" + name for name in """
AP2_LIVE/assignment-001/assignment_manifest.json
AP2_LIVE/first-freeze.lock.json
AP2_LIVE_V2/assignment-001/assignment_manifest.json
AP2_LIVE_V2/first-freeze.lock.json
MECHANISM_PILOT/assignment-001/assignment_manifest.json
MECHANISM_PILOT/assignment-002/assignment_manifest.json
MECHANISM_PILOT/assignment-003/assignment_manifest.json
MECHANISM_PILOT/first-freeze.lock.json
MECHANISM_PILOT/second-freeze.lock.json
MECHANISM_PILOT/third-freeze.lock.json
MPP006/assignment-mixed-001/assignment_manifest.json
MPP006/one-time-freeze.lock.json
MPP008/assignment-mixed-001/assignment_manifest.json
MPP008/one-time-freeze.lock.json
MPP009/assignment-001/assignment_manifest.json
MPP009/one-time-freeze.lock.json
OPEN004/assignment-invoice-001/assignment_manifest.json
OPEN004/invoice-first-freeze.lock.json
OPEN005/assignment-invoice-001/assignment_manifest.json
OPEN005/invoice-first-freeze.lock.json
OPEN006/assignment-invoice-001/assignment_manifest.json
OPEN006/invoice-first-freeze.lock.json
W10_DESIGN/assignment-001/assignment_manifest.json
W10_DESIGN/assignment-002/assignment_manifest.json
W10_DESIGN/assignment-003/assignment_manifest.json
W11_DESIGN/assignment-001/assignment_manifest.json
W11_DESIGN/assignment-002/assignment_manifest.json
W11_DESIGN/assignment-003/assignment_manifest.json
W11_DESIGN/assignment-004/assignment_manifest.json
W11_DESIGN/assignment-005/assignment_manifest.json
W11_DESIGN/assignment-006/assignment_manifest.json
W11_DESIGN/assignment-007/assignment_manifest.json
W11_DESIGN/assignment-008/assignment_manifest.json
""".split())
OFFLINE = ROOT / "artifacts/prospective/mpp010-scripted-native-001"
CONTAINER = "mpp010-pressure-localnet"
IMAGE = ("ghcr.io/tempoxyz/tempo-localnet@sha256:"
         "86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b")

# MPP008 supplies shared first-party source. MPP009 is bound only through
# archived evidence hashes, never through its frozen executable bytes.
NEW_SOURCE = (
    "src/agent_economic_trust/remote.py",
    "docs/PROSPECTIVE_MPP_PRESSURE_010.md",
    "docs/MPP010_IMPLEMENTATION_STATUS.md",
    "docs/MPP010_NATIVE_ISOLATION.md",
    "src/agent_economic_trust/mpp010_plan.py",
    "src/agent_economic_trust/mpp010_budget.py",
    "src/agent_economic_trust/mpp010_market.py",
    "src/agent_economic_trust/mpp010_orbit.py",
    "src/agent_economic_trust/mpp010_task.py",
    "src/agent_economic_trust/mpp010_boundary.py",
    "src/agent_economic_trust/mpp010_native_service.py",
    "src/agent_economic_trust/mpp010_remote.py",
    "src/agent_economic_trust/mpp010_reporting.py",
    "scripts/freeze_mpp010.py",
    "scripts/run_mpp010.py",
    "scripts/collect_mpp010.py",
    "scripts/run_mpp010_offline_native.py",
    "tests/test_mpp010_pressure.py",
    "tests/test_mpp010_offline_native.py",
    "tests/test_mpp010_runner.py",
    "tests/test_mpp010_clearance.py",
    "protocols/mpp/mpp010-meeting-service.mjs",
    "protocols/mpp/mpp010-chain-identity.mjs",
    "protocols/mpp/mpp010-verify-meeting-service.mjs",
    "protocols/mpp/mpp010-meeting-local.mjs",
    "protocols/mpp/mpp010-verify-meeting-evidence.mjs",
    "protocols/mpp/mpp010-decision-preflight.mjs",
)


def source_inventory() -> dict[str, str]:
    result = mpp008_source_inventory()
    for name in NEW_SOURCE:
        result[name] = sha(ROOT / name)
    return dict(sorted(result.items()))


def canonical_checkout_preflight() -> dict:
    """Accept only committed source plus expected mutable billing/run artifacts."""
    if ROOT.resolve() != PROJECT_ROOT.resolve():
        raise ValueError("MPP010 source root is not the canonical project checkout")
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=ROOT,
                         capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    if Path(top).resolve() != PROJECT_ROOT.resolve():
        raise ValueError("MPP010 Git checkout differs from canonical project root")
    sources = source_inventory()
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", "--", *sources],
                             cwd=ROOT, capture_output=True, text=True, timeout=10)
    if tracked.returncode:
        raise ValueError("MPP010 source inventory includes an untracked path")
    for name, expected_sha in sources.items():
        path = ROOT / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("MPP010 frozen source is not a regular file: " + name)
        committed = subprocess.run(["git", "show", "HEAD:" + name], cwd=ROOT,
                                   capture_output=True, check=True, timeout=10).stdout
        if sha256(committed).hexdigest() != expected_sha:
            raise ValueError("MPP010 frozen source differs from committed HEAD: " + name)
    dirty = subprocess.run(["git", "status", "--porcelain=v1", "-z",
                            "--untracked-files=no"], cwd=ROOT,
                           capture_output=True, check=True, timeout=10).stdout
    allowed = {"artifacts/budget/openrouter-ledger.jsonl",
               "artifacts/budget/openrouter-ledger.jsonl.anchor",
               "artifacts/gates/MPP010/collection-001.json"}
    assigned = set()
    if ASSIGNMENT.is_dir():
        manifest_path = ASSIGNMENT / "assignment_manifest.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise ValueError("MPP010 assignment is partial while checking dirty artifacts")
        assigned = {row["episode_id"] for row in json.loads(manifest_path.read_bytes())["rows"]}
    parts = dirty.split(b"\0")
    index = 0
    while index < len(parts) and parts[index]:
        entry = parts[index]
        status = entry[:2]
        names = [entry[3:].decode("utf-8", "surrogateescape")]
        if b"R" in status or b"C" in status:
            index += 1
            names.append(parts[index].decode("utf-8", "surrogateescape"))
        for name in names:
            segments = Path(name).parts
            assigned_run = (len(segments) >= 6
                and segments[:5] == ("artifacts", "gates", "MPP010", "runs-001", "episodes")
                and segments[5] in assigned)
            if name in sources or not (name in allowed or assigned_run):
                raise ValueError("MPP010 unrelated or frozen tracked path is dirty: " + name)
        index += 1
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    return {"source_commit": commit, "source_sha256": sources}


def runtime_pins() -> dict:
    """Pin the dedicated bare MPP010 chain, official runtime and local SDKs."""
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
        raise ValueError("dedicated MPP010 localnet container unavailable")
    container, = json.loads(result.stdout)
    bindings = container["HostConfig"]["PortBindings"].get("8545/tcp")
    if (container["Config"]["Image"] != IMAGE or container["State"]["Running"] is not True
            or container["Config"]["Cmd"] != ["--bare", "--block-time", "100ms"]
            or bindings != [{"HostIp": "127.0.0.1", "HostPort": "19767"}]
            or not container["Image"].startswith("sha256:")):
        raise ValueError("dedicated MPP010 bare localnet image, flags or port differs")
    installed = {}
    for package, expected in (("mppx", "0.13.4"), ("viem", "2.57.1")):
        path = ROOT / "protocols/mpp/node_modules" / package / "package.json"
        package_json = json.loads(path.read_bytes())
        if package_json.get("name") != package or package_json.get("version") != expected:
            raise ValueError("installed MPP SDK differs from lockfile")
        installed[package] = {"version": expected, "package_json_sha256": sha(path)}
    from agent_economic_trust.mpp010_remote import dedicated_chain_preflight
    chain = dedicated_chain_preflight()
    return {"orbit_commit": ORBIT_COMMIT, "orbit_version": version("orbit"),
            "inspect_ai_version": version("inspect_ai"), "node_sha256": sha(Path(node).resolve()),
            "mpp_image": IMAGE, "mpp_image_id": container["Image"],
            "mpp_package_lock_sha256": sha(ROOT / "protocols/mpp/package-lock.json"),
            "installed_mpp_sdk": installed,
            "container": CONTAINER,
            "rpc_url": "http://127.0.0.1:19767",
            "http_url": "http://127.0.0.1:19759", "chain_id": 1337,
            "genesis_hash": chain["genesis_hash"],
            "marker_transaction_hash": chain["marker_transaction_hash"],
            "marker_block_hash": chain["marker_block_hash"],
            "chain_identity_helper_sha256": sha(ROOT / "protocols/mpp/mpp010-chain-identity.mjs"),
            "bare": True, "chain_readiness": chain}


def offline_readiness() -> dict:
    """Require the saved nine-case local report to pass its own read-only verifier."""
    from scripts.run_mpp010_offline_native import verify_offline_report

    summary = verify_offline_report(OFFLINE / "summary.json")
    if (summary.get("status") != "PASS"
            or summary.get("remote_model_calls") != 0
            or summary.get("max_serialized_input_bytes", MAX_INPUT_BYTES + 1) > MAX_INPUT_BYTES
            or summary.get("verified_controls") != 9
            or summary.get("verified_tamper_negatives", 0) < 3):
        raise ValueError("MPP010 nine-case zero-model native readiness is incomplete")
    return {"status": "PASS", "summary_sha256": sha(OFFLINE / "summary.json"),
            "max_serialized_input_bytes": summary["max_serialized_input_bytes"],
            "scripted_cases": 9, "remote_model_calls": 0}


def _ledger_records_through(state: dict) -> list[dict]:
    """Read the already validated ledger only through this snapshot's head."""
    records = [json.loads(line) for line in CANONICAL_LEDGER_PATH.read_bytes().splitlines()]
    if (len(records) <= state["seq"] or records[state["seq"]]["hash"] != state["last_hash"]
            or state["seq"] < MPP009_FINAL_LEDGER_SEQ
            or records[MPP009_FINAL_LEDGER_SEQ]["hash"] != MPP009_FINAL_LEDGER_HASH):
        raise ValueError("MPP009 ledger ancestor or current head differs")
    return records[:state["seq"] + 1]


def mpp009_stopped_evidence(state: dict) -> dict:
    """Bind the frozen MPP009 denominator and first STOPPED paid row."""
    assignment = MPP009_GATE / "assignment-001/assignment_manifest.json"
    lock = MPP009_GATE / "one-time-freeze.lock.json"
    collection = MPP009_GATE / "collection-001-after-first-stop.json"
    episode_dir = MPP009_GATE / "runs-001/episodes" / MPP009_FIRST_EPISODE_ID
    stopped = episode_dir / "STOPPED.json"
    expected = ((assignment, MPP009_ASSIGNMENT_SHA256), (lock, MPP009_LOCK_SHA256),
                (collection, MPP009_COLLECTION_SHA256), (stopped, MPP009_FIRST_STOP_SHA256))
    if any(not path.is_file() or path.is_symlink() or sha(path) != value
           for path, value in expected):
        raise ValueError("MPP009 frozen assignment, lock, collection or STOPPED proof changed")
    frozen = json.loads(assignment.read_bytes())
    sealed = json.loads(lock.read_bytes())
    report = json.loads(collection.read_bytes())
    stop = json.loads(stopped.read_bytes())
    order = frozen.get("execution_order")
    results = report.get("rows")
    if (frozen.get("schema") != "mpp009-assignment-v1"
            or frozen.get("study_id") != "mpp-contingent-check-pressure-009"
            or frozen.get("planned_episodes") != 10
            or not isinstance(order, list) or len(order) != 10 or len(set(order)) != 10
            or order[0] != MPP009_FIRST_EPISODE_ID
            or {row.get("episode_id") for row in frozen.get("rows", [])} != set(order)
            or sealed.get("schema") != "mpp009-one-time-freeze-v1"
            or sealed.get("assignment_manifest_sha256") != MPP009_ASSIGNMENT_SHA256
            or report.get("schema") != "mpp009-collection-v1"
            or report.get("study_id") != frozen["study_id"]
            or report.get("assignment_manifest_sha256") != MPP009_ASSIGNMENT_SHA256
            or report.get("planned_episodes") != 10
            or report.get("completed_episodes") != 0
            or not isinstance(results, list) or len(results) != 10
            or [row.get("episode_id") for row in results] != order
            or [row.get("status") for row in results] != ["STOPPED"] + ["PENDING"] * 9
            or stop.get("schema") != "mpp009-stopped-episode-v1"
            or stop.get("assignment_manifest_sha256") != MPP009_ASSIGNMENT_SHA256
            or stop.get("episode_id") != MPP009_FIRST_EPISODE_ID
            or stop.get("ledger_run_id") != MPP009_FIRST_RUN_ID
            or stop.get("budget_state") != "SETTLED"
            or stop.get("no_retry_or_substitution") is not True
            or stop.get("complete_payment_claim") is not False
            or stop.get("model_calls_attempted") != 7
            or results[0].get("partial_native_evidence") != stop.get("partial_artifacts")):
        raise ValueError("MPP009 first STOPPED and nine PENDING rows differ")
    first_row = next(row for row in frozen["rows"]
                     if row["episode_id"] == MPP009_FIRST_EPISODE_ID)
    model_boundary = stop.get("model_request_boundary")
    expected_roles = ["provider", "provider", "auditor", "auditor",
                      "provider", "auditor", "auditor"]
    if (not isinstance(model_boundary, list) or len(model_boundary) != 7
            or [call.get("role") for call in model_boundary] != expected_roles
            or any(call.get("call_index") != index
                   or call.get("completed") is not True
                   or call.get("provider_api_invoked") is not True
                   or call.get("http_client_max_retries") != 0
                   or not isinstance(call.get("serialized_input_bytes"), int)
                   or call["serialized_input_bytes"] > 32768
                   or call.get("model") != "openrouter/" + first_row[
                       call["role"] + "_model_id"]
                   for index, call in enumerate(model_boundary, 1))):
        raise ValueError("MPP009 STOPPED seven model-call boundary differs")
    episodes = episode_dir.parent
    if (not episodes.is_dir() or episodes.is_symlink()
            or {path.name for path in episodes.iterdir()} != {MPP009_FIRST_EPISODE_ID}
            or (episode_dir / "episode_record.json").exists()):
        raise ValueError("MPP009 run directory contains a retry or an unassigned row")
    artifacts = stop["partial_artifacts"]
    if not isinstance(artifacts, list) or len(artifacts) != len({x.get("path") for x in artifacts}):
        raise ValueError("MPP009 STOPPED partial artifact inventory differs")
    artifact_sha = {}
    for item in artifacts:
        relative = Path(item["path"])
        path = episode_dir / relative
        if (relative.is_absolute() or ".." in relative.parts or path.is_symlink()
                or not path.is_file() or sha(path) != item["sha256"]):
            raise ValueError("MPP009 STOPPED partial artifact changed")
        artifact_sha[item["path"]] = item["sha256"]
    if artifact_sha.get("inspect.eval") != MPP009_FIRST_RAW_SHA256:
        raise ValueError("MPP009 STOPPED raw model archive changed")
    history = results[0].get("verified_native_history")
    if (not isinstance(history, list) or
            [x.get("operation") for x in history] !=
            ["prepare", "check", "release", "compensation"]):
        raise ValueError("MPP009 STOPPED native history is incomplete")
    for item in history:
        operation = item["operation"]
        name = f"native/{operation}-evidence.json"
        evidence = json.loads((episode_dir / name).read_bytes())
        hashes = ([payment["transaction"]["hash"] for payment in evidence["payments"]]
                  if operation == "compensation" else
                  [evidence["reduction" if operation == "prepare" else "transaction"]["hash"]])
        if (item.get("historical_balances_verified") is not True
                or item.get("evidence_sha256") != artifact_sha.get(name)
                or hashes != item.get("transaction_hashes", [item.get("transaction_hash")])):
            raise ValueError("MPP009 STOPPED native payment history changed")
    _ledger_records_through(state)
    billed = state["runs"].get(MPP009_FIRST_RUN_ID)
    if (not isinstance(billed, dict) or billed.get("status") != "SETTLED"
            or billed.get("evidence_ref") != "sha256:" + MPP009_FIRST_RAW_SHA256
            or Decimal(billed["actual_usd"]) != Decimal("0.123486")
            or any(name.startswith("mpp009-") and name != MPP009_FIRST_RUN_ID
                   for name in state["runs"])):
        raise ValueError("MPP009 STOPPED ledger billing or run denominator differs")
    return {"mpp009_disposition": "FIRST_STOPPED_NO_RETRY_NINE_PENDING",
            "mpp009_assignment_sha256": MPP009_ASSIGNMENT_SHA256,
            "mpp009_lock_sha256": MPP009_LOCK_SHA256,
            "mpp009_collection_sha256": MPP009_COLLECTION_SHA256,
            "mpp009_first_stopped_sha256": MPP009_FIRST_STOP_SHA256,
            "mpp009_first_raw_sha256": MPP009_FIRST_RAW_SHA256,
            "mpp009_first_ledger_run_id": MPP009_FIRST_RUN_ID,
            "mpp009_first_actual_usd": billed["actual_usd"],
            "mpp009_first_model_calls_attempted": 7,
            "mpp009_first_model_boundary_sha256": digest(model_boundary),
            "mpp009_final_ledger_seq": MPP009_FINAL_LEDGER_SEQ,
            "mpp009_final_ledger_hash": MPP009_FINAL_LEDGER_HASH,
            "mpp009_verified_native_history_sha256": digest(history)}


def competing_gate_inventory() -> dict[str, str]:
    """Bind every known frozen assignment/lock, including zero-call studies."""
    gates = PROJECT_ROOT / "artifacts/gates"
    inventory = {}
    for path in gates.rglob("*"):
        if "MPP010" in path.relative_to(gates).parts:
            continue
        if path.name == "assignment_manifest.json" or path.name.endswith("freeze.lock.json"):
            if path.is_symlink() or not path.is_file():
                raise ValueError("competing study gate path is not a regular file")
            inventory[str(path.relative_to(PROJECT_ROOT))] = sha(path)
    return dict(sorted(inventory.items()))


def _competing_gate_dispositions(inventory: dict[str, str]) -> dict[str, str]:
    """Require explicit review of frozen gates, including zero-ledger studies."""
    return {name: "REVIEWED_NO_ACTIVE_PRIORITY" for name in sorted({
        Path(path).parts[2] for path in inventory})}


def _new_competing_gates(inventory: dict[str, str]) -> list[str]:
    baseline = set(BASELINE_GATE_PATHS)
    if (not baseline.issubset(inventory)
            or digest({name: inventory[name] for name in sorted(baseline)}) !=
               BASELINE_GATE_INVENTORY_SHA256):
        raise ValueError("pre-MPP010 frozen competing gate baseline changed")
    return sorted({Path(name).parts[2] for name in inventory if name not in baseline})


def intervening_ledger_evidence(state: dict, *, through: dict | None = None) -> dict:
    """Require terminal billing for every run after the MPP009 stop."""
    records = _ledger_records_through(state if through is None else through)
    later = records[MPP009_FINAL_LEDGER_SEQ + 1:]
    run_ids = sorted({record["payload"]["run_id"] for record in later
                      if "run_id" in record["payload"]})
    final_runs = {}
    for ident in run_ids:
        billed = state["runs"].get(ident)
        if not isinstance(billed, dict) or billed.get("status") != "SETTLED":
            raise ValueError("post-MPP009 competing ledger run is nonterminal or UNKNOWN")
        final_runs[ident] = {"status": billed["status"],
                             "actual_usd": billed.get("actual_usd"),
                             "evidence_ref": billed.get("evidence_ref")}
    return {"post_mpp009_ledger_events_sha256": digest(later),
            "post_mpp009_ledger_run_ids": run_ids,
            "post_mpp009_terminal_runs": final_runs}


def _intervening_review(record: dict, run_ids: list[str],
                        new_gates: list[str]) -> list[dict]:
    reviews = record.get("intervening_studies")
    if not isinstance(reviews, list):
        raise ValueError("MPP010 intervening study review missing")
    covered = []
    expected = []
    reviewed_gates = []
    for item in reviews:
        if (not isinstance(item, dict) or item.get("disposition") != "FINALIZED_NO_ACTIVE_PRIORITY"
                or not isinstance(item.get("ledger_run_ids"), list)
                or not isinstance(item.get("gate_id"), str)
                or not isinstance(item.get("study_id"), str)
                or not isinstance(item.get("final_collection_path"), str)):
            raise ValueError("MPP010 intervening study review is incomplete")
        name = item["final_collection_path"]
        path = PROJECT_ROOT / name
        if (path.is_symlink() or not path.is_file() or
                not name.startswith("artifacts/gates/" + item["gate_id"] + "/")
                or ".." in Path(name).parts
                or not path.resolve().is_relative_to(
                    (PROJECT_ROOT / "artifacts/gates").resolve())):
            raise ValueError("MPP010 intervening final collection path differs")
        final = json.loads(path.read_bytes())
        planned = final.get("planned_episodes")
        complete = final.get("completed_episodes")
        stopped = final.get("stopped_episodes", 0)
        rows = final.get("rows")
        rows_final = (isinstance(rows, list) and len(rows) == planned
                      and all(row.get("status") in {"COMPLETE", "STOPPED"}
                              for row in rows))
        counts_final = (isinstance(complete, int) and isinstance(stopped, int)
                        and complete + stopped == planned)
        if (final.get("study_id") != item["study_id"]
                or not isinstance(planned, int) or planned <= 0
                or final.get("pending_episodes", 0) != 0
                or not (rows_final or counts_final)):
            raise ValueError("MPP010 intervening study is not finally disposed")
        covered.extend(item["ledger_run_ids"])
        reviewed_gates.append(item["gate_id"])
        expected.append({"gate_id": item["gate_id"],
                         "study_id": item["study_id"],
                         "disposition": "FINALIZED_NO_ACTIVE_PRIORITY",
                         "final_collection_path": name,
                         "final_collection_sha256": sha(path),
                         "ledger_run_ids": sorted(item["ledger_run_ids"])})
    if (sorted(covered) != run_ids or len(set(reviewed_gates)) != len(reviewed_gates)
            or not set(new_gates).issubset(reviewed_gates) or reviews != expected):
        raise ValueError("MPP010 intervening study review does not cover terminal ledger runs")
    return expected


def cross_study_clearance(state: dict, *, budget_head: dict | None = None) -> dict:
    """Require an explicit evidence-bound sequencing decision; never create it."""
    stopped = mpp009_stopped_evidence(state)
    if not CLEARANCE.is_file() or CLEARANCE.is_symlink():
        raise ValueError("MPP010 cross-study sequencing record is absent")
    budget_head = state if budget_head is None else budget_head
    later = intervening_ledger_evidence(state, through=budget_head)
    record = json.loads(CLEARANCE.read_bytes())
    inventory = competing_gate_inventory()
    new_gates = _new_competing_gates(inventory)
    reviews = _intervening_review(record, later["post_mpp009_ledger_run_ids"], new_gates)
    expected = {"schema": "mpp010-cross-study-clearance-v1",
                "study_id": STUDY_ID,
                "decision": "MPP010_PRIORITY_AFTER_MPP009_FIRST_STOP",
                "ledger_seq": budget_head["seq"],
                "ledger_last_hash": budget_head["last_hash"],
                "ledger_available_usd": budget_head["available_usd"],
                "competing_gate_inventory": inventory,
                "competing_gate_dispositions": _competing_gate_dispositions(inventory),
                "new_competing_gates": new_gates,
                "intervening_studies": reviews,
                **later, **stopped}
    if record != expected:
        raise ValueError("MPP010 cross-study clearance differs from current evidence or ledger")
    return {**record, "sha256": sha(CLEARANCE)}


def _reserves(prices: dict, rows: tuple) -> dict[str, Decimal]:
    result = {row.episode_id: reserve_pair(prices, row.provider_model_id,
                                           row.auditor_model_id) for row in rows}
    if sum(result.values(), Decimal(0)) != full_block_reserve(prices, rows):
        raise ValueError("MPP010 ten-row reserve differs from full-block calculation")
    return result


def load_assignment(directory: Path = ASSIGNMENT) -> tuple[dict, str, tuple]:
    directory = Path(directory)
    if directory.resolve() != ASSIGNMENT.resolve():
        raise ValueError("MPP010 assignment path differs from canonical freeze")
    seed = (directory / "seed.hex").read_text().strip()
    rows = make_schedule(seed)
    expected = manifest(seed, rows)
    path = directory / "assignment_manifest.json"
    frozen = json.loads(path.read_bytes())
    if any(frozen.get(key) != value for key, value in expected.items()):
        raise ValueError("MPP010 assignment differs from seeded schedule")
    if json.loads((directory / "private_episodes.json").read_bytes()) != [asdict(row) for row in rows]:
        raise ValueError("MPP010 private truth differs from seeded schedule")
    if json.loads(LOCK.read_bytes()) != {
            "schema": "mpp010-one-time-freeze-v1",
            "assignment_manifest_sha256": sha(path),
            "seed_commitment_sha256": expected["seed_commitment_sha256"]}:
        raise ValueError("MPP010 one-time freeze lock differs")
    return frozen, sha(path), rows


def freeze(*, seed_hex: str | None = None) -> dict:
    """Write the ten cells once, only after all local and cross-study gates pass."""
    checkout = canonical_checkout_preflight()
    if LOCK.exists() or ASSIGNMENT.exists():
        raise FileExistsError("MPP010 already or partially frozen; no reroll")
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
                   prior_ledger_run_ids=sorted(state["runs"]),
                   prior_ledger_runs_sha256=digest(state["runs"]),
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
    _new(LOCK, canonical({"schema": "mpp010-one-time-freeze-v1",
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
        raise ValueError("MPP010 executable source changed after freeze")
    if frozen["runtime_pins"] != runtime_pins():
        raise ValueError("MPP010 runtime pin changed after freeze")
    reserves = _reserves(frozen["public_pricing_snapshots"], rows)
    if (frozen["worst_case_reserve_usd_by_episode"] != {
                key: str(value) for key, value in reserves.items()}
            or frozen["worst_case_reserve_usd_full_block"] !=
                str(sum(reserves.values(), Decimal(0)))
            or frozen["required_headroom_usd"] != str(required_headroom(reserves))):
        raise ValueError("MPP010 frozen reservation or residual differs")
    current = _ancestor(frozen["budget_at_freeze"])
    prior_ids = frozen["prior_ledger_run_ids"]
    own_ids = {f"mpp010-{assignment_sha[:12]}-{row.episode_id}" for row in rows}
    if (prior_ids != sorted(set(prior_ids))
            or set(current["runs"]) - set(prior_ids) - own_ids
            or any(ident not in current["runs"] for ident in prior_ids)
            or digest({ident: current["runs"][ident] for ident in prior_ids}) !=
               frozen["prior_ledger_runs_sha256"]):
        raise ValueError("post-freeze competing ledger run or prior billing changed")
    if frozen["cross_study_clearance"] != cross_study_clearance(
            current, budget_head=frozen["budget_at_freeze"]):
        raise ValueError("MPP010 cross-study sequencing evidence changed")
    if frozen["prior_mpp006_contingent_exposure"] != mpp006_contingent_exposure(current):
        raise ValueError("MPP006 contingent exposure changed after MPP010 freeze")
    return {"status": "PASS", "assignment_manifest_sha256": assignment_sha,
            "planned_episodes": len(rows), "model_calls": 0}


def verify() -> dict:
    result = verify_static()
    frozen, _, _ = load_assignment()
    if frozen["offline_readiness"] != offline_readiness():
        raise ValueError("MPP010 zero-model readiness evidence changed")
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
