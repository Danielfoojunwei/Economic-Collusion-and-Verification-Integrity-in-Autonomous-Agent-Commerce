#!/usr/bin/env python3
"""One-time mixed-model native MPP assignment; no remote inference."""
from __future__ import annotations

import argparse
import ast
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from agent_economic_trust.mpp008_plan import (  # noqa: E402
    CANONICAL_LEDGER_PATH, canonical, digest, make_schedule, manifest)
from agent_economic_trust.mpp008_pricing import pricing_snapshots, reserve_pair  # noqa: E402
from agent_economic_trust.mpp008_budget import (  # noqa: E402
    MPP006_ORIGINAL_RESERVATION_USD, mpp006_contingent_exposure, required_headroom)
from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402
from agent_economic_trust.open_mpp_meeting import commitment  # noqa: E402
from scripts.freeze_mpp005 import (_ancestor, _ledger, _new, offline_readiness,
                                   runtime_pins, sha)  # noqa: E402
from scripts.run_mpp008_offline_native import run_new_native_controls  # noqa: E402


GATE = ROOT / "artifacts/gates/MPP008"
ASSIGNMENT = GATE / "assignment-mixed-001"
LOCK = GATE / "one-time-freeze.lock.json"
SOURCE_SEEDS = (
    "src/agent_economic_trust/__init__.py",
    "src/agent_economic_trust/mpp008_plan.py",
    "src/agent_economic_trust/mpp008_pricing.py",
    "src/agent_economic_trust/mpp008_task.py",
    "src/agent_economic_trust/mpp008_boundary.py",
    "src/agent_economic_trust/mpp008_remote.py",
    "src/agent_economic_trust/mpp008_reporting.py",
    "scripts/freeze_mpp008.py", "scripts/run_mpp008.py", "scripts/collect_mpp008.py",
    "scripts/run_mpp008_offline_native.py",
    "tests/test_mpp008_runner.py",
)
SOURCE_ASSETS = (
    "AGENTS.md", "UPSTREAM_PINNED.json", "docs/PROSPECTIVE_HETEROGENEOUS_SERVICES_004.md",
    "docs/MPP008_MIXED_MODEL_PROTOCOL.md", "protocols/mpp/package.json",
    "protocols/mpp/package-lock.json", "protocols/mpp/meeting-service.mjs",
    "protocols/mpp/verify-meeting-service.mjs", "protocols/mpp/meeting-local.mjs",
    "protocols/mpp/verify-meeting-evidence.mjs",
    "protocols/mpp/mpp008-decision-preflight.mjs",
)


def source_inventory() -> dict[str, str]:
    """Seal dynamic entrypoints, first-party import closure and native helpers."""
    pending = list(SOURCE_SEEDS)
    files = set(SOURCE_ASSETS)

    def module_for(name: str) -> str:
        parts = Path(name).with_suffix("").parts
        return ".".join(parts[1:] if parts[0] == "src" else parts)

    def path_for(module: str) -> str | None:
        if module == "agent_economic_trust" or module.startswith("agent_economic_trust."):
            relative = Path("src") / Path(*module.split("."))
        elif module == "scripts" or module.startswith("scripts."):
            relative = Path(*module.split("."))
        elif module == "tests" or module.startswith("tests."):
            relative = Path(*module.split("."))
        else:
            return None
        for candidate in (relative.with_suffix(".py"), relative / "__init__.py"):
            if (ROOT / candidate).is_file() and not (ROOT / candidate).is_symlink():
                return str(candidate)
        return None

    while pending:
        name = pending.pop()
        if name in files:
            continue
        path = ROOT / name
        sha(path)
        files.add(name)
        module = module_for(name)
        for node in ast.walk(ast.parse(path.read_bytes(), filename=name)):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                prefix = module.split(".")[:-node.level] if node.level else []
                base = ".".join([*prefix, *([node.module] if node.module else [])])
                imported = [base, *(base + "." + alias.name for alias in node.names)]
                if (node.level or base == "agent_economic_trust"
                        or base.startswith(("agent_economic_trust.", "scripts.", "tests."))):
                    if path_for(base) is None:
                        raise ValueError("unresolved first-party source import: " + base)
            else:
                continue
            for imported_module in imported:
                dependency = path_for(imported_module)
                if dependency is not None and dependency not in files:
                    pending.append(dependency)
    return {name: sha(ROOT / name) for name in sorted(files)}


def mixed_offline_readiness(sources: dict[str, str]) -> dict:
    """Reopen native controls and reject a legacy Node shape mismatch, no tx."""
    base = offline_readiness(sources)
    path = (ROOT / "artifacts/prospective/mpp-booking-service-stress-corrected/"
            "zero-model-001/trial-00/decision.json")
    original = json.loads(path.read_bytes())
    decision = {key: value for key, value in original.items() if key != "decision_sha256"}
    decision["model_execution_tier"] = "REAL_LLM_REMOTE_APPROVED"
    decision["model_provenance"] = {
        "expected_models_by_role": {"provider": "openrouter/anthropic/claude-sonnet-5.5",
                                    "auditor": "openrouter/anthropic/claude-sonnet-5.5"},
        "raw_actions_audited": True, "raw_model_events_sha256": "a" * 64,
        "reasoning_effort": "high",
        "reasoning_effort_by_role": {"provider": "high", "auditor": "high"}}
    decision["decision_sha256"] = commitment(decision)
    helper = ROOT / "protocols/mpp/mpp008-decision-preflight.mjs"
    with tempfile.TemporaryDirectory(prefix="mpp008-decision-", dir="/tmp") as temporary:
        target = Path(temporary) / "decision.json"
        target.write_bytes(canonical(decision) + b"\n")
        process = subprocess.run(["node", str(helper), str(target), decision["selected_flow"]],
                                 cwd=ROOT, capture_output=True, text=True, timeout=15,
                                 env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        if process.returncode or json.loads(process.stdout).get("status") != "PASS":
            raise ValueError("MPP008 mixed-model Node decision compatibility failed")
        malformed = {key: value for key, value in decision.items() if key != "decision_sha256"}
        malformed["model_provenance"].pop("reasoning_effort")
        malformed["decision_sha256"] = commitment(malformed)
        target.write_bytes(canonical(malformed) + b"\n")
        rejected = subprocess.run(["node", str(helper), str(target), decision["selected_flow"]],
                                  cwd=ROOT, capture_output=True, text=True, timeout=15,
                                  env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        if rejected.returncode == 0:
            raise ValueError("MPP008 mixed-model Node preflight accepted missing high reasoning")
    native = run_new_native_controls()
    if native.get("status") != "PASS" or native.get("real_remote_model_calls") != 0:
        raise ValueError("MPP008 new native bridge control failed")
    return {**base, "mixed_decision_preflight": "PASS",
            "new_native_bridge_controls": native,
            "missing_scalar_reasoning_negative": "REJECTED",
            "payment_execution": "NATIVE_LOCAL_PROTOCOL_SCRIPTED_CONTROL",
            "remote_model_execution": "NONE"}


def load_assignment(directory: Path = ASSIGNMENT):
    seed = (directory / "seed.hex").read_text().strip()
    rows = make_schedule(seed)
    expected = manifest(seed, rows)
    path = directory / "assignment_manifest.json"
    frozen = json.loads(path.read_bytes())
    if any(frozen.get(key) != value for key, value in expected.items()):
        raise ValueError("MPP008 manifest differs from seeded assignment")
    if json.loads((directory / "private_episodes.json").read_bytes()) != [asdict(row) for row in rows]:
        raise ValueError("MPP008 private assignment differs")
    lock = json.loads((directory.parent / LOCK.name).read_bytes())
    if lock != {"schema": "mpp008-one-time-freeze-v1",
                "assignment_manifest_sha256": sha(path),
                "seed_commitment_sha256": expected["seed_commitment_sha256"]}:
        raise ValueError("MPP008 one-time freeze lock differs")
    return frozen, sha(path), rows


def freeze(*, seed_hex: str | None = None) -> dict:
    if LOCK.exists() or ASSIGNMENT.exists():
        raise FileExistsError("MPP008 already or partially frozen; no reroll")
    # Resolve ambiguous earlier OpenRouter charges before even preparing a new
    # randomized assignment. The shared project cap is a lifetime gate.
    ledger = _ledger()
    if Decimal(ledger["reserved_usd"]) != 0:
        raise ValueError("shared USD50 lifetime ledger retains an active reservation")
    exposure = mpp006_contingent_exposure(ledger)
    seed_hex = secrets.token_hex(32) if seed_hex is None else seed_hex
    rows = make_schedule(seed_hex)
    payload = manifest(seed_hex, rows)
    sources = source_inventory()
    pins = runtime_pins()
    offline = mixed_offline_readiness(sources)
    prices = pricing_snapshots()
    reserves = {row.episode_id: reserve_pair(prices, row.provider_model_id, row.auditor_model_id)
                for row in rows}
    full = required_headroom(reserves)
    if full > Decimal(ledger["available_usd"]):
        raise ValueError("full MPP008 block, contingency, and MPP006 exposure exceed USD50 headroom")
    payload.update(source_sha256=sources, runtime_pins=pins, offline_readiness=offline,
                   public_pricing_snapshots=prices,
                   budget_at_freeze={key: ledger[key] for key in
                                     ("seq", "last_hash", "cap_usd", "available_usd")},
                   prior_mpp006_contingent_exposure=exposure,
                   required_headroom_usd=str(full),
                   worst_case_reserve_usd_by_episode={key: str(value) for key, value in reserves.items()},
                   worst_case_reserve_usd_full_block=str(sum(reserves.values(), Decimal(0))))
    GATE.mkdir(parents=True, exist_ok=True)
    raw = canonical(payload) + b"\n"
    _new(LOCK, canonical({"schema": "mpp008-one-time-freeze-v1",
         "assignment_manifest_sha256": sha256(raw).hexdigest(),
         "seed_commitment_sha256": payload["seed_commitment_sha256"]}) + b"\n")
    ASSIGNMENT.mkdir(mode=0o700)
    _new(ASSIGNMENT / "seed.hex", (seed_hex + "\n").encode())
    _new(ASSIGNMENT / "private_episodes.json", canonical([asdict(row) for row in rows]) + b"\n")
    _new(ASSIGNMENT / "assignment_manifest.json", raw)
    return {"status": "FROZEN_NOT_EXECUTED", "planned_episodes": len(rows),
            "assignment_manifest_sha256": sha256(raw).hexdigest(),
            "worst_case_block_usd": str(sum(reserves.values(), Decimal(0))), "model_calls": 0}


def _verify_static() -> tuple[dict, str, tuple, dict]:
    """Check frozen assignment, source, runtime and budget without native replay."""
    frozen, assignment_sha, rows = load_assignment()
    sources = source_inventory()
    if frozen["source_sha256"] != sources:
        raise ValueError("MPP008 executable source changed")
    if frozen["runtime_pins"] != runtime_pins():
        raise ValueError("MPP008 native/runtime pin changed")
    reserves = {row.episode_id: reserve_pair(frozen["public_pricing_snapshots"],
                row.provider_model_id, row.auditor_model_id) for row in rows}
    if (frozen["worst_case_reserve_usd_by_episode"] != {
            key: str(value) for key, value in reserves.items()}
            or frozen["worst_case_reserve_usd_full_block"] != str(sum(reserves.values(), Decimal(0)))):
        raise ValueError("MPP008 frozen reservation differs")
    if frozen["required_headroom_usd"] != str(required_headroom(reserves)):
        raise ValueError("MPP008 frozen MPP006 exposure headroom differs")
    if frozen["prior_mpp006_contingent_exposure"] != mpp006_contingent_exposure(
            _ancestor(frozen["budget_at_freeze"])):
        raise ValueError("MPP008 frozen MPP006 settlement evidence differs")
    return frozen, assignment_sha, rows, sources


def verify_static() -> dict:
    """Reopen sealed material after a paid row without executing controls."""
    _, assignment_sha, rows, _ = _verify_static()
    return {"status": "PASS", "assignment_manifest_sha256": assignment_sha,
            "planned_episodes": len(rows), "native_controls_executed": False}


def verify() -> dict:
    frozen, assignment_sha, rows, sources = _verify_static()
    if frozen["offline_readiness"] != mixed_offline_readiness(sources):
        raise ValueError("MPP008 offline control evidence changed")
    return {"status": "PASS", "assignment_manifest_sha256": assignment_sha,
            "planned_episodes": len(rows)}


def readiness() -> dict:
    """Report the zero-paid gate even while old billing remains UNKNOWN."""
    sources = source_inventory()
    prices = pricing_snapshots()
    rows = make_schedule("ab" * 32)
    reserves = [reserve_pair(prices, row.provider_model_id, row.auditor_model_id)
                for row in rows]
    state = BudgetLedger(CANONICAL_LEDGER_PATH).snapshot()
    full = required_headroom(reserves)
    try:
        exposure = mpp006_contingent_exposure(state)
        settlement_ready = True
    except ValueError as exc:
        exposure = {"prior_reservation_usd": str(MPP006_ORIGINAL_RESERVATION_USD),
                    "status": "NOT_RECONCILED", "reason": str(exc)}
        settlement_ready = False
    return {"runtime_pins": runtime_pins(),
            "offline": mixed_offline_readiness(sources),
            "source_inventory_sha256": digest(sources),
            "public_pricing_snapshots": prices,
            "worst_case_block_usd": str(sum(reserves, Decimal(0))),
            "required_headroom_usd": str(full),
            "prior_mpp006_contingent_exposure": exposure,
            "ledger": {key: state[key] for key in ("seq", "available_usd", "cap_usd",
                            "reserved_usd", "blocked", "unknown_run_ids")},
            "would_freeze": (not LOCK.exists() and not ASSIGNMENT.exists()
                and settlement_ready and state["cap_usd"] == "50"
                and not state["blocked"] and not state["unknown_run_ids"]
                and Decimal(state["reserved_usd"]) == 0
                and full <= Decimal(state["available_usd"]))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "verify", "readiness"))
    args = parser.parse_args()
    if args.command == "freeze":
        answer = freeze()
    elif args.command == "verify":
        answer = verify()
    else:
        answer = readiness()
    print(json.dumps(answer, sort_keys=True))


if __name__ == "__main__":
    main()
