#!/usr/bin/env python3
"""Read-only readiness and one-time prospective five-pair MPP011 freeze.

The reviewed cross-study clearance is a separate committed artifact. This
module never calls a paid model or moves local payment assets.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
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

from agent_economic_trust.mpp011_budget import (
    budget_preflight, fee011_hold, mpp006_with_x402, required_headroom,
    x402_contingent_hold,
)
from agent_economic_trust.mpp011_plan import (
    CANONICAL_LEDGER_PATH, MAX_INPUT_BYTES, STUDY_ID, canonical, digest,
    full_block_reserve, make_schedule, manifest, refreshed_catalog, reserve_pair,
)
from agent_economic_trust.remote_budget import BudgetLedger
from scripts.freeze_mpp005 import _ancestor, _new, sha
from scripts.freeze_mpp008 import source_inventory as mpp008_source_inventory


PROJECT_ROOT = CANONICAL_LEDGER_PATH.parents[2]
GATE = ROOT / "artifacts/gates/MPP011"
ASSIGNMENT = GATE / "assignment-001"
RUNS = GATE / "runs-001"
LOCK = GATE / "one-time-freeze.lock.json"
CLEARANCE = GATE / "cross-study-clearance.json"
OFFLINE = ROOT / "artifacts/prospective/mpp011-scripted-native-002"
X402_GATE = PROJECT_ROOT / "artifacts/gates/X402_LIVE011"
CONTAINER = "mpp010-pressure-localnet"
IMAGE = ("ghcr.io/tempoxyz/tempo-localnet@sha256:"
         "86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b")

MPP010 = {
    "gate": "MPP010", "schema": "mpp010-assignment-v1",
    "lock_schema": "mpp010-one-time-freeze-v1",
    "collection_schema": "mpp010-collection-v1", "planned": 10,
    "assignment": "f3189330bfa1e1b3942151c52226d0390742f4eca9c8c5dee822e0d46160ec74",
    "lock": "9c22065fe59dcf521ad2ba8b14362ae9572bf15d47c947a99fbc71efb7a92cba",
    "collection": "8adc7a00c3e679d39e2976800af361da096978a7ac9d0d69c36b39779c1ae691",
    "stop": "5dc98f3f4271f1f7edec01ef6030906cf3a210f95f83f249b6d10de86fe2a7e0",
    "episode": "mpp010-fd58811b0c6751a119e750a2",
    "run": "mpp010-f3189330bfa1-mpp010-fd58811b0c6751a119e750a2",
    "actual_usd": "0.147242", "run_prefix": "mpp010-",
    "study": "mpp-contingent-check-pressure-010",
}
FEE011 = {
    "gate": "ERC8183_FEE011", "schema": "fee011-successor-assignment-v1",
    "lock_schema": "fee011-first-freeze-lock-v1",
    "collection_schema": "fee011-itt-collection-v1", "planned": 8,
    "assignment": "c36239cdcfd421441974cdcd865e317fa118e2514368085bf54d1dbcdf699471",
    "lock": "62da5f8c98e1fbe30209a6b8e0f187c8cc28ed81b65f90abe211bf6cf215dfe7",
    "collection": "469ed70b289a7e142c8ffd01528abd69866147ce0c48f0b30dbf819f8d406309",
    "stop": "a958aaf91828070f5f7da74a9e9baf73eea1fdbe6e0b27c023c5b6820760195e",
    "episode": "fee010-b0125916b5cd2e63f69109b5",
    "run": "fee011-c36239cdcfd4-fee010-b0125916b5cd2e63f69109b5",
    "actual_usd": "0.061476", "run_prefix": "fee011-",
    "study": "erc8183-native-evaluator-fee-live-011",
}
FEE_HOLD_ID = FEE011["run"] + "-failed-request-hold"
FEE_HOLD_USD = Decimal("3.379164")
FEE_HOLD_RELATIVE = "artifacts/budget/fee011-failed-request-hold-001/evidence.json"
FEE_HOLD_SHA256 = "87f7817ae03d0fbfb7f0fd2063fc7401012180cbd204959337da084f3499e50b"
MPP006_HOLD_ID = "mpp006-0e11d0595056-mpp006-bc092a2baae1584874c4f308"
X402_FIRST_RUN_ID = "x402011-ea4c997ba6f3-x402011-19587c1ddccc97900b2deddd"
X402_FIRST_EPISODE = "x402011-19587c1ddccc97900b2deddd"
X402_ASSIGNMENT_SHA256 = "ea4c997ba6f30d6b007469c90bbd58de923ee185406fc405b847b591ae2098bb"
X402_LOCK_SHA256 = "03d67d895889565b9ea2ed59ae39f5675584054921206f94f548d5d21d6566d0"
X402_COLLECTION_SHA256 = "49e3d3bb707700a55f89156c0423bd28f9d474344dfab8be4b676c065b5c281b"
X402_HOLD_RELATIVE = "artifacts/budget/x402011-first-stop-contingent-001/evidence.json"
X402_HOLD_SHA256 = "84dbe734ba49a992def4aeee3b77645a80ee8b9fd2d89a5b59a1dbbe4d7d9559"
X402_HOLD_USD = Decimal("4.407296")

# MPP008 seals its transitive source closure; these are MPP011's new executable
# entry points and dynamic Node assets. Prior study executables stay archived.
NEW_SOURCE = (
    "docs/MPP011_PROSPECTIVE.md",
    "src/agent_economic_trust/remote.py",
    "src/agent_economic_trust/mpp011_plan.py",
    "src/agent_economic_trust/mpp011_budget.py",
    "src/agent_economic_trust/mpp011_market.py",
    "src/agent_economic_trust/mpp011_orbit.py",
    "src/agent_economic_trust/mpp011_task.py",
    "src/agent_economic_trust/mpp011_boundary.py",
    "src/agent_economic_trust/mpp011_native_service.py",
    "src/agent_economic_trust/mpp011_remote.py",
    "src/agent_economic_trust/mpp011_reporting.py",
    "scripts/freeze_mpp011.py",
    "scripts/run_mpp011.py",
    "scripts/collect_mpp011.py",
    "scripts/run_mpp011_offline_native.py",
    "tests/test_mpp011_workflow.py",
    "tests/test_mpp011_freeze.py",
    "protocols/mpp/mpp011-meeting-service.mjs",
    "protocols/mpp/mpp011-chain-identity.mjs",
    "protocols/mpp/mpp011-verify-meeting-service.mjs",
    "protocols/mpp/mpp011-meeting-local.mjs",
    "protocols/mpp/mpp011-verify-meeting-evidence.mjs",
    "protocols/mpp/mpp011-decision-preflight.mjs",
)


def source_inventory() -> dict[str, str]:
    inventory = mpp008_source_inventory()
    for name in NEW_SOURCE:
        inventory[name] = sha(ROOT / name)
    return dict(sorted(inventory.items()))


def _committed(name: str, expected_sha: str | None = None) -> str:
    path = ROOT / name
    actual = sha(path)
    if expected_sha is not None and actual != expected_sha:
        raise ValueError("reviewed artifact changed: " + name)
    result = subprocess.run(["git", "show", "HEAD:" + name], cwd=ROOT,
                            capture_output=True, timeout=10)
    if result.returncode or sha256(result.stdout).hexdigest() != actual:
        raise ValueError("artifact is absent from committed HEAD or dirty: " + name)
    return actual


def canonical_checkout_preflight() -> dict:
    """Require exact committed source in the one shared-ledger checkout."""
    if ROOT.resolve() != PROJECT_ROOT.resolve():
        raise ValueError("MPP011 freeze requires the canonical project checkout")
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=ROOT,
                         capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    if Path(top).resolve() != PROJECT_ROOT.resolve():
        raise ValueError("MPP011 Git root differs from the shared-ledger checkout")
    inventory = source_inventory()
    for name, value in inventory.items():
        _committed(name, value)
    _committed(str(CLEARANCE.relative_to(ROOT)))
    dirty = subprocess.run(["git", "status", "--porcelain=v1", "-z",
                            "--untracked-files=no"], cwd=ROOT,
                           capture_output=True, check=True, timeout=10).stdout
    allowed = {"artifacts/budget/openrouter-ledger.jsonl",
               "artifacts/budget/openrouter-ledger.jsonl.anchor"}
    assigned: set[str] = set()
    if ASSIGNMENT.exists():
        if not ASSIGNMENT.is_dir() or ASSIGNMENT.is_symlink():
            raise ValueError("MPP011 partial assignment path")
        assigned = {row["episode_id"] for row in
                    json.loads((ASSIGNMENT / "assignment_manifest.json").read_bytes())["rows"]}
    entries = dirty.split(b"\0")
    index = 0
    while index < len(entries) and entries[index]:
        entry = entries[index]
        names = [entry[3:].decode("utf-8", "surrogateescape")]
        if b"R" in entry[:2] or b"C" in entry[:2]:
            index += 1
            names.append(entries[index].decode("utf-8", "surrogateescape"))
        for name in names:
            parts = Path(name).parts
            own_run = (len(parts) >= 6 and parts[:5] ==
                       ("artifacts", "gates", "MPP011", "runs-001", "episodes")
                       and parts[5] in assigned)
            own_collection = (parts[:3] == ("artifacts", "gates", "MPP011")
                              and len(parts) == 4 and parts[3].startswith("collection-"))
            if name in inventory or name == str(CLEARANCE.relative_to(ROOT)) or not (
                    name in allowed or own_run or own_collection):
                raise ValueError("unrelated or frozen tracked path is dirty: " + name)
        index += 1
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    return {"source_commit": head, "source_sha256": inventory}


def runtime_pins() -> dict:
    """Reuse the persistent bare MPP010 chain and verify its marker history."""
    from agent_economic_trust.meeting_generalization import ORBIT_COMMIT, verify_orbit_source
    from agent_economic_trust.mpp011_remote import dedicated_chain_preflight

    verify_orbit_source()
    if version("orbit") != "1.0.3" or version("inspect_ai") != "0.3.263":
        raise ValueError("ORBIT or Inspect runtime pin differs")
    node = shutil.which("node")
    if not node:
        raise ValueError("Node runtime absent")
    docker_env = os.environ.copy()
    for key in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY",
                "DOCKER_CERT_PATH"):
        docker_env.pop(key, None)
    result = subprocess.run(["docker", "--host=unix:///var/run/docker.sock", "inspect",
                             CONTAINER], capture_output=True, text=True, timeout=15,
                            env=docker_env)
    if result.returncode:
        raise ValueError("persistent MPP010 localnet container unavailable")
    container, = json.loads(result.stdout)
    if (container["Config"]["Image"] != IMAGE or container["State"]["Running"] is not True
            or container["Config"]["Cmd"] != ["--bare", "--block-time", "100ms"]
            or container["HostConfig"]["PortBindings"].get("8545/tcp") !=
               [{"HostIp": "127.0.0.1", "HostPort": "19767"}]):
        raise ValueError("MPP010 bare localnet image, flags or port differs")
    installed = {}
    for package, expected in (("mppx", "0.13.4"), ("viem", "2.57.1")):
        package_path = ROOT / "protocols/mpp/node_modules" / package / "package.json"
        meta = json.loads(package_path.read_bytes())
        if meta.get("name") != package or meta.get("version") != expected:
            raise ValueError("installed native MPP SDK differs from lockfile")
        installed[package] = {"version": expected, "sha256": sha(package_path)}
    chain = dedicated_chain_preflight()
    if (chain.get("status") != "PASS" or chain.get("chain_id") != 1337
            or chain.get("rpc_url") != "http://127.0.0.1:19767"):
        raise ValueError("MPP011 persistent chain marker differs")
    return {"orbit_commit": ORBIT_COMMIT, "orbit_version": version("orbit"),
            "inspect_ai_version": version("inspect_ai"),
            "node_sha256": sha(Path(node).resolve()), "image": IMAGE,
            "image_id": container["Image"], "container": CONTAINER,
            "sdk": installed,
            "package_lock_sha256": sha(ROOT / "protocols/mpp/package-lock.json"),
            "chain_helper_sha256": sha(ROOT / "protocols/mpp/mpp011-chain-identity.mjs"),
            "chain_readiness": chain}


def offline_readiness() -> dict:
    from scripts.run_mpp011_offline_native import verify_offline_report

    result = verify_offline_report(OFFLINE / "summary.json")
    if (result.get("status") != "PASS" or result.get("remote_model_calls") != 0
            or result.get("verified_controls") != 5
            or result.get("verified_tamper_negatives") != 7
            or result.get("max_serialized_input_bytes", MAX_INPUT_BYTES + 1) > MAX_INPUT_BYTES):
        raise ValueError("MPP011 five-case zero-model native controls incomplete")
    return {"status": "PASS", "summary_sha256": sha(OFFLINE / "summary.json"),
            "scripted_cases": 5, "tamper_negatives": 7, "remote_model_calls": 0,
            "max_serialized_input_bytes": result["max_serialized_input_bytes"]}


def _predecessor(spec: dict, state: dict) -> dict:
    """Seal each stopped first row and its unchanged full assignment denominator."""
    gate = PROJECT_ROOT / "artifacts/gates" / spec["gate"]
    assignment = gate / "assignment-001/assignment_manifest.json"
    lock = gate / ("one-time-freeze.lock.json" if spec["gate"] == "MPP010"
                   else "first-freeze.lock.json")
    collection = gate / "collection-001-after-first-stop.json"
    episodes = gate / "runs-001/episodes"
    stopped = episodes / spec["episode"] / "STOPPED.json"
    for path, expected in ((assignment, spec["assignment"]), (lock, spec["lock"]),
                           (collection, spec["collection"]), (stopped, spec["stop"])):
        if sha(path) != expected:
            raise ValueError(spec["gate"] + " reviewed assignment or stop changed")
    frozen = json.loads(assignment.read_bytes())
    sealed = json.loads(lock.read_bytes())
    report = json.loads(collection.read_bytes())
    stop = json.loads(stopped.read_bytes())
    order = frozen.get("execution_order")
    rows = report.get("rows")
    if (frozen.get("schema") != spec["schema"]
            or frozen.get("study_id", frozen.get("study")) != spec["study"]
            or frozen.get("planned_episodes", spec["planned"]) != spec["planned"]
            or not isinstance(order, list) or len(order) != spec["planned"]
            or len(set(order)) != len(order) or order[0] != spec["episode"]
            or sealed.get("schema") != spec["lock_schema"]
            or sealed.get("assignment_manifest_sha256") != spec["assignment"]
            or report.get("schema") != spec["collection_schema"]
            or report.get("assignment_manifest_sha256") != spec["assignment"]
            or report.get("planned_episodes") != spec["planned"]
            or report.get("completed_episodes") != 0
            or report.get("stopped_episodes", 1) != 1
            or report.get("pending_episodes", spec["planned"] - 1) != spec["planned"] - 1
            or not isinstance(rows, list) or len(rows) != spec["planned"]
            or [row.get("episode_id") for row in rows] != order
            or [row.get("status") for row in rows] !=
               ["STOPPED"] + ["PENDING"] * (spec["planned"] - 1)
            or stop.get("episode_id") != spec["episode"]
            or stop.get("assignment_manifest_sha256") != spec["assignment"]
            or stop.get("ledger_run_id") != spec["run"]
            or stop.get("budget_state") != "SETTLED"
            or stop.get("no_retry_or_substitution") is not True
            or {path.name for path in episodes.iterdir()} != {spec["episode"]}
            or (episodes / spec["episode"] / "episode_record.json").exists()):
        raise ValueError(spec["gate"] + " first STOPPED row or pending denominator differs")
    raw_sha = sha(episodes / spec["episode"] / "inspect.eval")
    billed = state["runs"].get(spec["run"])
    if (not isinstance(billed, dict) or billed.get("status") != "SETTLED"
            or billed.get("evidence_ref") != "sha256:" + raw_sha
            or Decimal(billed.get("actual_usd", "-1")) != Decimal(spec["actual_usd"])):
        raise ValueError(spec["gate"] + " archived model charge differs")
    return {"assignment_sha256": spec["assignment"], "lock_sha256": spec["lock"],
            "collection_sha256": spec["collection"], "first_stop_sha256": spec["stop"],
            "first_raw_inspect_sha256": raw_sha, "ledger_run_id": spec["run"],
            "settled_model_cost_usd": billed["actual_usd"],
            "status_counts": {"COMPLETE": 0, "STOPPED": 1,
                              "PENDING": spec["planned"] - 1}}


def _fee_failed_request_hold(state: dict) -> dict:
    fee011_hold(state)
    path = PROJECT_ROOT / FEE_HOLD_RELATIVE
    if sha(path) != FEE_HOLD_SHA256:
        raise ValueError("FEE011 failed-request forensic hold evidence differs")
    evidence = json.loads(path.read_bytes())
    if (evidence.get("schema") != "fee011-failed-request-billing-buffer-v1"
            or evidence.get("buffer_run_id") != FEE_HOLD_ID
            or evidence.get("original_ledger_run_id") != FEE011["run"]
            or Decimal(evidence.get("additional_reserved_buffer_usd", "-1")) != FEE_HOLD_USD
            or evidence.get("final_failed_request_charge_usd", "MISSING") is not None
            or evidence.get("failed_event_http_status") != 400
            or evidence.get("per_call_billing_available") is not False):
        raise ValueError("FEE011 failed-request hold facts differ")
    for key, relative in evidence["evidence_paths"].items():
        path = PROJECT_ROOT / relative
        if (path.is_symlink() or not path.resolve().is_relative_to(PROJECT_ROOT.resolve())
                or sha(path) != evidence["evidence_sha256"][key]):
            raise ValueError("FEE011 forensic dependency changed")
    held = state["runs"].get(FEE_HOLD_ID)
    if (not isinstance(held, dict) or held.get("status") != "RESERVED"
            or Decimal(held.get("reserved_usd", "-1")) != FEE_HOLD_USD):
        raise ValueError("FEE011 failed-request reservation absent or released")
    return {"evidence_sha256": FEE_HOLD_SHA256, "ledger_run_id": FEE_HOLD_ID,
            "reserved_usd": str(FEE_HOLD_USD), "status": "RESERVED_UNRECONCILED"}


def _x402_disposition(state: dict, final_collection: str | None) -> dict:
    """A frozen x402 gate requires a complete or stopped-prefix final report."""
    assignment = X402_GATE / "assignment-001/assignment_manifest.json"
    lock = X402_GATE / "first-freeze.lock.json"
    prior_runs = sorted(name for name in state["runs"] if name.startswith("x402011-"))
    if not assignment.exists() and not lock.exists():
        if (prior_runs or final_collection is not None
                or (X402_GATE / "runs-001").exists()):
            raise ValueError("x402 011 paid run or partial gate lacks a freeze")
        return {"status": "PROSPECTIVE_ONLY_NO_PAID_GATE", "ledger_run_ids": []}
    if not assignment.is_file() or not lock.is_file() or final_collection is None:
        raise ValueError("frozen x402 011 lacks an explicit final collection")
    relative = Path(final_collection)
    if (relative.is_absolute() or ".." in relative.parts
            or relative.parent != Path("artifacts/gates/X402_LIVE011")):
        raise ValueError("x402 011 collection path is outside its gate")
    collection = PROJECT_ROOT / relative
    frozen, sealed, report = (json.loads(path.read_bytes()) for path in
                              (assignment, lock, collection))
    assignment_sha = sha(assignment)
    order = frozen.get("execution_order")
    rows = report.get("rows")
    if (assignment_sha != X402_ASSIGNMENT_SHA256
            or sha(lock) != X402_LOCK_SHA256
            or sha(collection) != X402_COLLECTION_SHA256
            or frozen.get("schema") != "x402-live011-first-assignment-v1"
            or frozen.get("study") != "x402-audit-retainer-live-011"
            or sealed.get("schema") != "x402-live011-one-time-freeze-v1"
            or sealed.get("assignment_manifest_sha256") != assignment_sha
            or report.get("schema") != "x402-live011-itt-collection-v1"
            or report.get("assignment_manifest_sha256") != assignment_sha
            or report.get("planned_episodes") != 4
            or not isinstance(order, list) or len(order) != 4 or len(set(order)) != 4
            or order[0] != X402_FIRST_EPISODE
            or not isinstance(rows, list) or len(rows) != 4
            or [row.get("episode_id") for row in rows] != order):
        raise ValueError("x402 011 frozen denominator or collection differs")
    source_sha = frozen.get("source_sha256")
    if (not isinstance(source_sha, dict) or not source_sha
            or frozen.get("source_inventory_sha256") != digest(source_sha)
            or any(not isinstance(name, str) or not isinstance(value, str)
                   or sha(PROJECT_ROOT / name) != value
                   for name, value in source_sha.items())):
        raise ValueError("x402 011 frozen executable source changed")
    statuses = [row.get("status") for row in rows]
    if (statuses != ["STOPPED", "PENDING", "PENDING", "PENDING"]
            or report.get("completed_episodes") != 0
            or report.get("stopped_episodes") != 1
            or report.get("pending_episodes") != 3
            or rows[0].get("budget_state") != "UNKNOWN"
            or prior_runs != [X402_FIRST_RUN_ID]):
        raise ValueError("x402 011 first STOPPED and three PENDING rows differ")
    exposure = x402_contingent_hold(state)
    sidecar_path = PROJECT_ROOT / X402_HOLD_RELATIVE
    if sha(sidecar_path) != X402_HOLD_SHA256:
        raise ValueError("x402 011 contingent billing sidecar changed")
    sidecar = json.loads(sidecar_path.read_bytes())
    if (sidecar.get("schema") != "x402011-first-stop-contingent-billing-v1"
            or sidecar.get("run_id") != X402_FIRST_RUN_ID
            or Decimal(sidecar.get("contingent_budget_exposure_usd", "-1")) != X402_HOLD_USD
            or sidecar.get("evidence_sha256", {}).get("collection") != X402_COLLECTION_SHA256
            or sidecar.get("actual_final_provider_charge_usd", "MISSING") is not None
            or sidecar.get("settlement_requires_independent_review") is not True):
        raise ValueError("x402 011 contingent sidecar facts differ")
    episodes = X402_GATE / "runs-001/episodes"
    if (not episodes.is_dir() or {path.name for path in episodes.iterdir()} !=
            {X402_FIRST_EPISODE}):
        raise ValueError("x402 011 run directory differs from final disposition")
    stop_path = episodes / X402_FIRST_EPISODE / "STOPPED.json"
    if (stop_path.is_symlink() or not stop_path.is_file()
            or sha(stop_path) != sidecar["evidence_sha256"]["stop"]):
        raise ValueError("x402 011 first STOPPED proof changed")
    proof = {X402_FIRST_EPISODE: sha(stop_path)}
    # Reopen the prior study's raw Inspect/native collector. Its ledger sequence
    # naturally advances when later studies reserve or settle, so compare every
    # reported finding except that snapshot field.
    from scripts.collect_x402_live011 import collect
    from scripts.freeze_x402_live011 import load_assignment as load_x402_assignment

    loaded, loaded_sha, assigned_rows = load_x402_assignment()
    if loaded != frozen or loaded_sha != assignment_sha:
        raise ValueError("x402 011 seeded assignment changed")
    # The saved collector was produced at ledger seq154, when this run was
    # UNKNOWN. It is now CONTINGENT with the same full reservation. Restore
    # only that one historical status for collector replay; all spending gates
    # above use the actual, independently validated current ledger state.
    prestate = sidecar["ledger_prestate"]
    lines = CANONICAL_LEDGER_PATH.read_bytes().splitlines()
    event = json.loads(lines[prestate["seq"]])
    transition = json.loads(lines[prestate["seq"] + 1])
    if (prestate["seq"] != 154 or event["hash"] != prestate["last_hash"]
            or event["kind"] != "unknown"
            or event["payload"] != {"reason": "RemoteBoundaryError",
                                      "run_id": X402_FIRST_RUN_ID}
            or prestate["unknown_run_ids"] != [X402_FIRST_RUN_ID]
            or prestate["blocked"] is not True
            or prestate["cap_usd"] != "50"
            or prestate["reserved_usd"] != "14.0943"
            or transition["seq"] != 155
            or transition["prev_hash"] != event["hash"]
            or transition["kind"] != "contingent"
            or transition["payload"] != {
                "run_id": X402_FIRST_RUN_ID,
                "evidence_ref": "sha256:" + X402_HOLD_SHA256}):
        raise ValueError("x402 011 reviewed UNKNOWN ancestor changed")
    historical = deepcopy(state)
    old_run = historical["runs"][X402_FIRST_RUN_ID]
    for key in ("evidence_ref", "contingent_evidence_ref", "prior_unknown_reason"):
        old_run.pop(key, None)
    old_run.update(status="UNKNOWN", unknown_reason="RemoteBoundaryError")
    historical["seq"] = 154
    historical["last_hash"] = prestate["last_hash"]
    historical["unknown_run_ids"] = [X402_FIRST_RUN_ID]
    historical["contingent_run_ids"] = [MPP006_HOLD_ID]
    historical["blocked"] = True
    reopened = collect(frozen, assignment_sha, assigned_rows,
                       X402_GATE / "runs-001", ledger_snapshot=historical)
    without_snapshot = lambda value: {key: item for key, item in value.items()
                                      if key != "shared_ledger_seq"}
    if without_snapshot(reopened) != without_snapshot(report):
        raise ValueError("x402 011 saved collection differs from independent replay")
    return {"status": "FIRST_STOPPED_CONTINGENT_NO_RETRY_THREE_PENDING",
            "assignment_sha256": assignment_sha,
            "lock_sha256": sha(lock), "final_collection_path": final_collection,
            "final_collection_sha256": sha(collection),
            "episode_evidence_sha256": proof, "ledger_run_ids": prior_runs,
            "source_inventory_sha256": frozen["source_inventory_sha256"],
            "contingent_exposure": exposure,
            "contingent_evidence_sha256": X402_HOLD_SHA256,
            "saved_collector_budget_state": "UNKNOWN"}


def clearance_preview(state: dict, *, x402_collection: str | None = None,
                      budget_head: dict | None = None) -> dict:
    """Deterministic read-only content to review and commit before any freeze."""
    head = state if budget_head is None else budget_head
    if (head.get("cap_usd") != "50" or state.get("blocked")
            or state.get("unknown_run_ids") or state["seq"] < head["seq"]):
        raise ValueError("shared ledger blocked or clearance head invalid")
    lines = CANONICAL_LEDGER_PATH.read_bytes().splitlines()
    if len(lines) <= head["seq"] or json.loads(lines[head["seq"]])["hash"] != head["last_hash"]:
        raise ValueError("clearance ledger head is not a current ancestor")
    mpp = _predecessor(MPP010, state)
    fee = _predecessor(FEE011, state)
    fee_hold = _fee_failed_request_hold(state)
    x402 = _x402_disposition(state, x402_collection)
    if x402["status"] != "FIRST_STOPPED_CONTINGENT_NO_RETRY_THREE_PENDING":
        raise ValueError("x402 011 first-stop contingent disposition is required")
    own_reserved = sum((Decimal(value["reserved_usd"]) for name, value in
                        state["runs"].items() if name.startswith("mpp011-")
                        and value.get("status") == "RESERVED"), Decimal(0))
    old = mpp006_with_x402(
        state, additional_reservation_usd=FEE_HOLD_USD + own_reserved)
    other = {name for name, value in state["runs"].items()
             if value.get("status") in {"RESERVED", "UNKNOWN", "CONTINGENT"}
             and name not in {MPP006_HOLD_ID, FEE_HOLD_ID, X402_FIRST_RUN_ID}
             and not name.startswith("mpp011-")}
    if other:
        raise ValueError("another competing study has an unresolved ledger run")
    return {"schema": "mpp011-cross-study-clearance-v1", "study_id": STUDY_ID,
            "decision": "MPP011_AFTER_MPP010_FEE011_AND_X402_FINAL_DISPOSITION",
            "ledger_at_clearance": {key: head[key] for key in
                                    ("seq", "last_hash", "cap_usd", "available_usd")},
            "mpp010": mpp, "fee011": fee, "fee011_failed_request_hold": fee_hold,
            "mpp006_contingent_hold": old,
            "x402_live011": x402}


def cross_study_clearance(state: dict, *, budget_head: dict | None = None) -> dict:
    if not CLEARANCE.is_file() or CLEARANCE.is_symlink():
        raise ValueError("reviewed MPP011 cross-study clearance absent")
    relative = str(CLEARANCE.relative_to(ROOT))
    clearance_sha = _committed(relative)
    saved = json.loads(CLEARANCE.read_bytes())
    x402_collection = saved.get("x402_live011", {}).get("final_collection_path")
    expected = clearance_preview(state, x402_collection=x402_collection,
                                 budget_head=budget_head)
    if saved != expected:
        raise ValueError("MPP011 cross-study clearance differs from source evidence")
    predecessor_paths = [
        "artifacts/gates/MPP010/assignment-001/assignment_manifest.json",
        "artifacts/gates/MPP010/one-time-freeze.lock.json",
        "artifacts/gates/MPP010/collection-001-after-first-stop.json",
        "artifacts/gates/MPP010/runs-001/episodes/" + MPP010["episode"] + "/STOPPED.json",
        "artifacts/gates/ERC8183_FEE011/assignment-001/assignment_manifest.json",
        "artifacts/gates/ERC8183_FEE011/first-freeze.lock.json",
        "artifacts/gates/ERC8183_FEE011/collection-001-after-first-stop.json",
        "artifacts/gates/ERC8183_FEE011/runs-001/episodes/" + FEE011["episode"] + "/STOPPED.json",
        FEE_HOLD_RELATIVE, X402_HOLD_RELATIVE,
    ]
    x402 = expected["x402_live011"]
    if x402["status"] != "PROSPECTIVE_ONLY_NO_PAID_GATE":
        predecessor_paths.extend([
            "artifacts/gates/X402_LIVE011/assignment-001/assignment_manifest.json",
            "artifacts/gates/X402_LIVE011/first-freeze.lock.json",
            x402["final_collection_path"],
        ])
        for episode in x402["episode_evidence_sha256"]:
            directory = X402_GATE / "runs-001/episodes" / episode
            relative = (directory / ("STOPPED.json" if (directory / "STOPPED.json").exists()
                                     else "episode_record.json")).relative_to(ROOT)
            predecessor_paths.append(str(relative))
    for name in predecessor_paths:
        _committed(name)
    return {**saved, "sha256": clearance_sha}


def _reserves(prices: dict, rows: tuple) -> dict[str, Decimal]:
    values = {row.episode_id: reserve_pair(prices, row.provider_model_id,
                                           row.auditor_model_id) for row in rows}
    if sum(values.values(), Decimal(0)) != full_block_reserve(prices, rows):
        raise ValueError("five-row reserve differs from full-block calculation")
    return values


def load_assignment(directory: Path = ASSIGNMENT) -> tuple[dict, str, tuple]:
    if Path(directory).resolve() != ASSIGNMENT.resolve():
        raise ValueError("MPP011 assignment path differs from one-time freeze")
    seed = (ASSIGNMENT / "seed.hex").read_text().strip()
    rows = make_schedule(seed)
    expected = manifest(seed, rows)
    path = ASSIGNMENT / "assignment_manifest.json"
    frozen = json.loads(path.read_bytes())
    if any(frozen.get(key) != value for key, value in expected.items()):
        raise ValueError("MPP011 public assignment differs from seeded five-row design")
    if json.loads((ASSIGNMENT / "private_episodes.json").read_bytes()) != [
            asdict(row) for row in rows]:
        raise ValueError("MPP011 private truth differs from seeded schedule")
    lock = {"schema": "mpp011-one-time-freeze-v1",
            "assignment_manifest_sha256": sha(path),
            "seed_commitment_sha256": expected["seed_commitment_sha256"]}
    if json.loads(LOCK.read_bytes()) != lock:
        raise ValueError("MPP011 one-time freeze lock differs")
    return frozen, sha(path), rows


def freeze(*, seed_hex: str | None = None) -> dict:
    if os.environ.get("MPP011_FREEZE_ALLOWED") != "true":
        raise ValueError("explicit MPP011 one-time freeze switch required")
    checkout = canonical_checkout_preflight()
    if LOCK.exists() or ASSIGNMENT.exists():
        raise FileExistsError("MPP011 already or partially frozen; no reroll")
    state = BudgetLedger(CANONICAL_LEDGER_PATH).snapshot()
    clearance = cross_study_clearance(state)
    pins = runtime_pins()
    offline = offline_readiness()
    prices = refreshed_catalog()
    seed = secrets.token_hex(32) if seed_hex is None else seed_hex
    rows = make_schedule(seed)
    reserves = _reserves(prices, rows)
    budget = budget_preflight(state, reserves)
    payload = manifest(seed, rows)
    payload.update(source_sha256=checkout["source_sha256"],
                   source_commit=checkout["source_commit"], runtime_pins=pins,
                   offline_readiness=offline, cross_study_clearance=clearance,
                   prior_ledger_run_ids=sorted(state["runs"]),
                   prior_ledger_runs_sha256=digest(state["runs"]),
                   public_pricing_snapshots=prices,
                   budget_at_freeze={key: state[key] for key in
                                     ("seq", "last_hash", "cap_usd", "available_usd")},
                   prior_mpp006_contingent_exposure=mpp006_with_x402(
                       state, additional_reservation_usd=FEE_HOLD_USD),
                   prior_fee011_failed_request_hold=clearance["fee011_failed_request_hold"],
                   prior_x402_contingent_exposure=clearance["x402_live011"]["contingent_exposure"],
                   required_headroom_usd=budget["required_headroom_usd"],
                   worst_case_reserve_usd_by_episode={key: str(value)
                       for key, value in reserves.items()},
                   worst_case_reserve_usd_full_block=budget["full_block_reserve_usd"])
    if BudgetLedger(CANONICAL_LEDGER_PATH).snapshot()["last_hash"] != state["last_hash"]:
        raise ValueError("shared ledger changed during MPP011 freeze preflight")
    raw = canonical(payload) + b"\n"
    GATE.mkdir(parents=True, exist_ok=True)
    _new(LOCK, canonical({"schema": "mpp011-one-time-freeze-v1",
        "assignment_manifest_sha256": sha256(raw).hexdigest(),
        "seed_commitment_sha256": payload["seed_commitment_sha256"]}) + b"\n")
    ASSIGNMENT.mkdir(mode=0o700)
    _new(ASSIGNMENT / "seed.hex", (seed + "\n").encode())
    _new(ASSIGNMENT / "private_episodes.json",
         canonical([asdict(row) for row in rows]) + b"\n")
    _new(ASSIGNMENT / "assignment_manifest.json", raw)
    return {"status": "FROZEN_NOT_EXECUTED", "planned_episodes": 5,
            "assignment_manifest_sha256": sha256(raw).hexdigest(),
            "required_headroom_usd": budget["required_headroom_usd"],
            "model_calls": 0}


def verify_static() -> dict:
    checkout = canonical_checkout_preflight()
    frozen, assignment_sha, rows = load_assignment()
    if frozen["source_sha256"] != checkout["source_sha256"]:
        raise ValueError("MPP011 executable source changed after freeze")
    if frozen["runtime_pins"] != runtime_pins():
        raise ValueError("MPP011 runtime or persistent chain changed after freeze")
    reserves = _reserves(frozen["public_pricing_snapshots"], rows)
    if (frozen["worst_case_reserve_usd_by_episode"] !=
            {key: str(value) for key, value in reserves.items()}
            or frozen["worst_case_reserve_usd_full_block"] !=
               str(sum(reserves.values(), Decimal(0)))
            or frozen["required_headroom_usd"] != str(required_headroom(reserves))):
        raise ValueError("MPP011 frozen five-row reservation differs")
    current = _ancestor(frozen["budget_at_freeze"])
    prior = frozen["prior_ledger_run_ids"]
    own = {f"mpp011-{assignment_sha[:12]}-{row.episode_id}" for row in rows}
    if (prior != sorted(set(prior))
            or set(current["runs"]) - set(prior) - own
            or any(name not in current["runs"] for name in prior)
            or digest({name: current["runs"][name] for name in prior}) !=
               frozen["prior_ledger_runs_sha256"]):
        raise ValueError("MPP011 prior billing changed or competing paid run appeared")
    own_reserved = sum((Decimal(current["runs"][name]["reserved_usd"])
                        for name in own if name in current["runs"]
                        and current["runs"][name].get("status") == "RESERVED"), Decimal(0))
    if frozen["prior_mpp006_contingent_exposure"] != mpp006_with_x402(
            current, additional_reservation_usd=FEE_HOLD_USD + own_reserved):
        raise ValueError("MPP006 contingent exposure changed after MPP011 freeze")
    clearance = cross_study_clearance(current, budget_head=frozen["budget_at_freeze"])
    if frozen["cross_study_clearance"] != clearance:
        raise ValueError("MPP011 post-freeze predecessor disposition changed")
    if frozen["prior_fee011_failed_request_hold"] != clearance["fee011_failed_request_hold"]:
        raise ValueError("FEE011 failed-request hold changed after freeze")
    if frozen["prior_x402_contingent_exposure"] != clearance["x402_live011"]["contingent_exposure"]:
        raise ValueError("x402 011 contingent exposure changed after freeze")
    return {"status": "PASS", "assignment_manifest_sha256": assignment_sha,
            "planned_episodes": len(rows), "model_calls": 0}


def verify() -> dict:
    result = verify_static()
    frozen, _, _ = load_assignment()
    if frozen["offline_readiness"] != offline_readiness():
        raise ValueError("MPP011 zero-model native controls changed")
    return result


def readiness() -> dict:
    """Explain blockers without writing an assignment or spending USD."""
    checks: dict[str, str] = {}
    for name, operation in (("canonical_checkout", canonical_checkout_preflight),
                            ("source", source_inventory), ("runtime", runtime_pins),
                            ("offline", offline_readiness),
                            ("catalog", refreshed_catalog)):
        try:
            value = operation()
            checks[name] = "PASS"
            if name == "catalog":
                prices = value
        except Exception as exc:
            checks[name] = type(exc).__name__ + ": " + str(exc)
    checks["one_time_freeze"] = ("ALREADY_FROZEN_OR_PARTIAL"
                                  if LOCK.exists() or ASSIGNMENT.exists() else "PASS")
    try:
        state = BudgetLedger(CANONICAL_LEDGER_PATH).snapshot()
        checks["ledger"] = "PASS"
    except Exception as exc:
        state = None
        checks["ledger"] = type(exc).__name__ + ": " + str(exc)
    if state is not None:
        try:
            cross_study_clearance(state)
            checks["cross_study"] = "PASS"
        except Exception as exc:
            checks["cross_study"] = type(exc).__name__ + ": " + str(exc)
        if checks.get("catalog") == "PASS":
            try:
                budget = budget_preflight(state, _reserves(prices, make_schedule("ab" * 32)))
                checks["budget"] = "PASS"
            except Exception as exc:
                checks["budget"] = type(exc).__name__ + ": " + str(exc)
                budget = None
        else:
            budget = None
    else:
        budget = None
    ready = bool(checks) and all(value == "PASS" for value in checks.values())
    return {"status": "READY" if ready else "BLOCKED", "would_freeze": ready,
            "checks": checks, "budget": budget, "model_calls": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("readiness", "clearance-preview", "freeze", "verify"))
    parser.add_argument("--x402-collection", help="explicit final x402 011 collection path")
    args = parser.parse_args()
    if args.command == "clearance-preview":
        result = clearance_preview(BudgetLedger(CANONICAL_LEDGER_PATH).snapshot(),
                                   x402_collection=args.x402_collection)
    else:
        if args.x402_collection:
            parser.error("--x402-collection is only for clearance-preview")
        result = {"readiness": readiness, "freeze": freeze,
                  "verify": verify}[args.command]()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
