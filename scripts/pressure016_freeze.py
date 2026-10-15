#!/usr/bin/env python3
"""Read-only PRESSURE016 gates and a guarded one-time future assignment freeze.

The source preview deliberately has no frozen assignment. A paid run requires
PARTIAL014 final collection and independent review, this study's separate
independent source review, fresh full-block USD50 headroom, and the explicit
one-time freeze switch in the canonical shared-ledger checkout.
"""

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
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from agent_economic_trust.mpp005_plan import canonical_project_root  # noqa: E402
from agent_economic_trust.mpp008_pricing import pricing_snapshots  # noqa: E402
from agent_economic_trust.partial014_plan import per_row_reserve  # noqa: E402
from agent_economic_trust.pressure016_plan import (  # noqa: E402
    CANONICAL_LEDGER, ROWS, digest, make_schedule, prospective_manifest,
    required_headroom)
from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402
from scripts.partial014_freeze import (  # noqa: E402
    source_names as partial014_source_names)

GATE = ROOT / "artifacts/gates/ERC8183_PRESSURE016"
ASSIGNMENT = GATE / "assignment-001"
LOCK = GATE / "first-freeze.lock.json"
REVIEW = ROOT / "artifacts/prospective/ERC8183_PRESSURE016/source-review-001.json"
PARTIAL014_GATE = ROOT / "artifacts/gates/ERC8183_PARTIAL_CLAIM014"
PARTIAL014_REVIEW = PARTIAL014_GATE / "independent-results-review-final.json"
OFFLINE = ROOT / "artifacts/prospective/ERC8183_PRESSURE016/offline-native-001"
PARTIAL014_OFFLINE = ROOT / "artifacts/prospective/ERC8183_PARTIAL_CLAIM014/offline-native-001"
OWN_SOURCE = (
    "src/agent_economic_trust/pressure016_plan.py",
    "src/agent_economic_trust/pressure016_task.py",
    "src/agent_economic_trust/pressure016_boundary.py",
    "src/agent_economic_trust/pressure016_offline.py",
    "src/agent_economic_trust/pressure016_remote.py",
    "scripts/pressure016_collect.py",
    "scripts/pressure016_freeze.py",
    "scripts/run_pressure016.py",
    "tests/test_pressure016_source.py",
    "docs/PROSPECTIVE_ERC8183_PRESSURE016_DESIGN.md",
)


def sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"PRESSURE016 sealed evidence missing or symlinked: {path}")
    return sha256(path.read_bytes()).hexdigest()


def _json(value: object) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"


def _new(path: Path, payload: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _canonical_root() -> None:
    if ROOT.resolve() != canonical_project_root().resolve():
        raise ValueError("PRESSURE016 freeze requires canonical shared-ledger checkout")


def source_names() -> tuple[str, ...]:
    return tuple(sorted(set(partial014_source_names()) | set(OWN_SOURCE)))


def source_inventory() -> dict[str, str]:
    return {name: sha(ROOT / name) for name in source_names()}


def frozen_source_inventory(sealed: dict[str, str]) -> dict[str, str]:
    """Use exactly the sealed path set even when later studies add files."""
    if (not isinstance(sealed, dict) or not sealed
            or any(not isinstance(name, str) or not isinstance(expected, str)
                   or Path(name).is_absolute() or ".." in Path(name).parts
                   or len(expected) != 64 for name, expected in sealed.items())):
        raise ValueError("PRESSURE016 frozen source inventory malformed")
    return {name: sha(ROOT / name) for name in sealed}


def clean_versioned_sources() -> bool:
    names = source_names()
    listed = subprocess.run(["git", "ls-files", "--error-unmatch", "--", *names],
                            cwd=ROOT, capture_output=True).returncode == 0
    clean = not subprocess.run(["git", "status", "--porcelain", "--", *names],
                               cwd=ROOT, capture_output=True, text=True,
                               check=True).stdout.strip()
    return listed and clean


def source_review(sources: dict[str, str]) -> dict:
    saved = json.loads(REVIEW.read_bytes())
    if (REVIEW.is_symlink()
            or saved.get("schema") != "pressure016-live-source-review-v1"
            or saved.get("status") != "GO_SOURCE_MERGE_ONLY"
            or saved.get("source_inventory_sha256") != digest(sources)
            or saved.get("reviewer_id") in (None, "", "/root", "/root/pressure016_source")
            or saved.get("freeze_or_paid_authorization") is not False):
        raise ValueError("PRESSURE016 independent source review differs")
    return {"path": str(REVIEW.relative_to(ROOT)), "sha256": sha(REVIEW),
            "reviewer_id": saved["reviewer_id"]}


def _runtime() -> dict:
    from scripts.verify_erc8183_fee_readiness import installed_runtime_versions
    if version("orbit") != "1.0.3" or version("inspect_ai") != "0.3.263":
        raise ValueError("pinned ORBIT or Inspect runtime differs")
    return installed_runtime_versions()


def _offline() -> dict:
    from agent_economic_trust.partial014_offline import verify as verify_partial014
    from agent_economic_trust.pressure016_offline import verify as verify_pressure016
    prior = verify_partial014(PARTIAL014_OFFLINE)
    result = verify_pressure016(OFFLINE)
    if (prior.get("status") != "PASS" or prior.get("paid_model_calls") != 0
            or prior.get("scripted_native_cases_reverified") != 11
            or prior.get("tamper_negatives_reverified") != 19
            or result.get("status") != "PASS" or result.get("paid_model_calls") != 0
            or result.get("scripted_native_cases_reverified") != 4
            or result.get("scripted_bad_early_approval_controls") != 2
            or result.get("tamper_negatives_reverified") != 4):
        raise ValueError("PRESSURE016 official native positive/negative controls differ")
    return {"path": str((OFFLINE / "report.json").relative_to(ROOT)),
            "report_sha256": sha(OFFLINE / "report.json"),
            "scripted_native_cases_reverified": 4,
            "tamper_negatives_reverified": 4,
            "predecessor_report_sha256": sha(PARTIAL014_OFFLINE / "report.json"),
            "model_tier": "SCRIPTED_SIMULATION", "paid_model_calls": 0}


def _ledger() -> dict:
    state = BudgetLedger(CANONICAL_LEDGER).snapshot()
    if (state.get("cap_usd") != "50" or state.get("blocked")
            or state.get("unknown_run_ids")):
        raise ValueError("PRESSURE016 USD50 ledger blocked or unknown")
    if any(row.get("status") == "RESERVED" for row in state["runs"].values()):
        raise ValueError("another live row is still reserved")
    return state


def _partial014_closed(state: dict) -> dict:
    from scripts.partial014_collect import collect as collect_partial014
    from scripts.partial014_freeze import (load_assignment as load_partial014,
                                           verify_static as verify_partial014)
    verify_partial014()
    _, assignment_sha, assigned = load_partial014()
    review = json.loads(PARTIAL014_REVIEW.read_bytes())
    relative = review.get("collection_path")
    if (type(relative) is not str or Path(relative).is_absolute()
            or ".." in Path(relative).parts):
        raise ValueError("PARTIAL014 independent review lacks safe collection path")
    collection_path = ROOT / relative
    if (not collection_path.resolve().is_relative_to(PARTIAL014_GATE.resolve())
            or review.get("assignment_manifest_sha256") != assignment_sha
            or review.get("collection_sha256") != sha(collection_path)
            or review.get("reviewer_id") in (None, "", "/root")
            or review.get("freeze_or_paid_authorization") is not False
            or not str(review.get("status", "")).startswith("REVIEW_COMPLETE")):
        raise ValueError("PARTIAL014 final independent review differs")
    saved = json.loads(collection_path.read_bytes())
    current = collect_partial014()
    # The historical collection's ledger sequence is an observation at its
    # write time; subsequent settled PRESSURE016 rows legitimately advance it.
    current["shared_ledger_seq"] = saved.get("shared_ledger_seq")
    if saved != current or saved.get("planned_episodes") != len(assigned):
        raise ValueError("PARTIAL014 final assigned denominator no longer replays")
    if (saved.get("completed_episodes", 0)
            + saved.get("observed_incomplete_episodes", 0)
            + saved.get("stopped_episodes", 0)
            + saved.get("pending_episodes", 0) != len(assigned)):
        raise ValueError("PARTIAL014 final denominator differs")
    if saved.get("pending_episodes", 0) and not saved.get("stopped_episodes", 0):
        raise ValueError("PARTIAL014 has unclosed pending rows")
    for row in saved["rows"]:
        if row["status"] in {"COMPLETE", "OBSERVED_INCOMPLETE"}:
            ident = "partial014-" + assignment_sha[:12] + "-" + row["episode_id"]
            if state["runs"].get(ident, {}).get("status") != "SETTLED":
                raise ValueError("PARTIAL014 complete model run lacks settled billing")
        elif row["status"] == "STOPPED":
            ident = "partial014-" + assignment_sha[:12] + "-" + row["episode_id"]
            if state["runs"].get(ident, {}).get("status") != "SETTLED":
                raise ValueError("PARTIAL014 stopped charge is not reconciled")
    return {"assignment_manifest_sha256": assignment_sha,
            "collection_path": relative, "collection_sha256": sha(collection_path),
            "independent_review_sha256": sha(PARTIAL014_REVIEW),
            "completed_episodes": saved["completed_episodes"],
            "stopped_episodes": saved["stopped_episodes"],
            "pending_episodes": saved["pending_episodes"]}


def _budget(state: dict, prices: dict) -> dict:
    per = per_row_reserve(prices)
    needed = required_headroom(prices, ROWS)
    if needed > Decimal(state["available_usd"]):
        raise ValueError("full four-row PRESSURE016 block plus contingency exceeds USD50")
    return {"per_row_worst_case_usd": str(per),
            "full_block_plus_contingency_residual_usd": str(needed),
            "ledger_available_usd": state["available_usd"]}


def readiness() -> dict:
    checks: dict[str, str] = {}
    values: dict = {}
    for name, fn in (
        ("canonical_checkout", _canonical_root),
        ("one_time_freeze_available", lambda: None if not LOCK.exists()
         and not ASSIGNMENT.exists() else (_ for _ in ()).throw(
             FileExistsError("already or partially frozen"))),
        ("source_clean", lambda: None if clean_versioned_sources() else
         (_ for _ in ()).throw(ValueError("source not committed"))),
        ("source_inventory", source_inventory),
        ("pinned_runtime", _runtime),
        ("native_controls", _offline),
        ("shared_ledger", _ledger),
        ("current_catalog", pricing_snapshots)):
        try:
            values[name] = fn()
            checks[name] = "PASS"
        except Exception as exc:
            checks[name] = type(exc).__name__ + ": " + str(exc)
    for name, fn in (
        ("independent_source_review", lambda: source_review(
            values["source_inventory"])),
        ("partial014_final_closure", lambda: _partial014_closed(
            values["shared_ledger"])),
        ("full_block_budget", lambda: _budget(
            values["shared_ledger"], values["current_catalog"]))):
        try:
            values[name] = fn()
            checks[name] = "PASS"
        except Exception as exc:
            checks[name] = type(exc).__name__ + ": " + str(exc)
    ready = all(value == "PASS" for value in checks.values())
    return {"status": "READY" if ready else "BLOCKED",
            "would_freeze": ready, "would_call_paid_model": False,
            "checks": checks, "budget": values.get("full_block_budget"),
            "model_calls": 0}


def freeze(*, seed_hex: str | None = None) -> dict:
    _canonical_root()
    if os.environ.get("PRESSURE016_FREEZE_ALLOWED") != "true":
        raise ValueError("explicit PRESSURE016 one-time freeze switch required")
    if LOCK.exists() or ASSIGNMENT.exists():
        raise FileExistsError("PRESSURE016 already or partially frozen; no reroll")
    if readiness()["status"] != "READY":
        raise ValueError("PRESSURE016 readiness has uncleared gates")
    state = _ledger()
    sources = source_inventory()
    prices = pricing_snapshots()
    seed = seed_hex if seed_hex is not None else secrets.token_hex(32)
    rows = make_schedule(seed)
    payload = {**prospective_manifest(seed, rows),
               "schema": "pressure016-first-assignment-v1",
               "status": "FROZEN_NOT_EXECUTED",
               "source_sha256": sources,
               "source_inventory_sha256": digest(sources),
               "runtime_pins": _runtime(),
               "offline_readiness": _offline(),
               "independent_source_review": source_review(sources),
               "partial014_final_closure": _partial014_closed(state),
               "public_pricing_snapshot": prices,
               "budget_at_freeze": {key: state[key] for key in (
                   "seq", "last_hash", "cap_usd", "available_usd", "reserved_usd")},
               "budget_gate": _budget(state, prices),
               "prior_open_ledger_run_ids": sorted(ident for ident, run in
                   state["runs"].items() if run["status"] in
                   {"RESERVED", "CONTINGENT", "UNKNOWN"}),
               "prior_ledger_run_ids": sorted(state["runs"]),
               "prior_ledger_runs_sha256": digest(state["runs"]),
               "model_tier": "REAL_LLM_REMOTE_APPROVED",
               "payment_tier": "NATIVE_LOCAL_PROTOCOL",
               "no_reroll_or_model_substitution": True}
    if BudgetLedger(CANONICAL_LEDGER).snapshot()["last_hash"] != state["last_hash"]:
        raise ValueError("shared ledger changed during PRESSURE016 freeze")
    GATE.mkdir(parents=True, exist_ok=True)
    ASSIGNMENT.mkdir(mode=0o700)
    _new(ASSIGNMENT / "seed.hex", (seed + "\n").encode())
    _new(ASSIGNMENT / "private_rows.json", _json([asdict(row) for row in rows]))
    _new(ASSIGNMENT / "assignment_manifest.json", _json(payload))
    lock = {"schema": "pressure016-one-time-freeze-v1",
            "assignment_manifest_sha256": sha(ASSIGNMENT / "assignment_manifest.json"),
            "seed_commitment_sha256": payload["seed_commitment_sha256"]}
    _new(LOCK, _json(lock))
    return {"status": "FROZEN_NOT_EXECUTED", "rows": ROWS,
            "assignment_manifest_sha256": lock["assignment_manifest_sha256"],
            "ledger_seq": state["seq"], "model_calls": 0}


def load_assignment() -> tuple[dict, str, tuple]:
    seed = (ASSIGNMENT / "seed.hex").read_text().strip()
    rows = make_schedule(seed)
    if json.loads((ASSIGNMENT / "private_rows.json").read_bytes()) != [
            asdict(row) for row in rows]:
        raise ValueError("PRESSURE016 private rows differ from one-time seed")
    manifest = ASSIGNMENT / "assignment_manifest.json"
    frozen = json.loads(manifest.read_bytes())
    preview = prospective_manifest(seed, rows)
    for key, value in preview.items():
        if key not in {"schema", "status"} and frozen.get(key) != value:
            raise ValueError("PRESSURE016 assignment differs from seed preview")
    if (frozen.get("schema") != "pressure016-first-assignment-v1"
            or frozen.get("status") != "FROZEN_NOT_EXECUTED"
            or json.loads(LOCK.read_bytes()) != {
                "schema": "pressure016-one-time-freeze-v1",
                "assignment_manifest_sha256": sha(manifest),
                "seed_commitment_sha256": frozen["seed_commitment_sha256"]}):
        raise ValueError("PRESSURE016 one-time manifest or lock differs")
    return frozen, sha(manifest), rows


def verify_static() -> dict:
    _canonical_root()
    frozen, assignment_sha, rows = load_assignment()
    sources = frozen_source_inventory(frozen["source_sha256"])
    if (frozen["source_sha256"] != sources
            or frozen["source_inventory_sha256"] != digest(sources)
            or frozen["independent_source_review"] != source_review(sources)
            or frozen["offline_readiness"] != _offline()):
        raise ValueError("PRESSURE016 sealed source, review or native controls changed")
    return {"status": "SEALED_STATIC", "assignment_manifest_sha256": assignment_sha,
            "rows": len(rows), "model_calls": 0}


def verify() -> dict:
    result = verify_static()
    frozen, assignment_sha, _ = load_assignment()
    state = _ledger()
    earlier = frozen["budget_at_freeze"]
    lines = CANONICAL_LEDGER.read_bytes().splitlines()
    if (state["seq"] < earlier["seq"] or len(lines) <= earlier["seq"]
            or json.loads(lines[earlier["seq"]])["hash"] != earlier["last_hash"]
            or frozen["partial014_final_closure"] != _partial014_closed(state)):
        raise ValueError("PRESSURE016 predecessor or ledger ancestor differs")
    from agent_economic_trust.pressure016_remote import _ledger as verify_run_set
    verify_run_set(state, frozen, assignment_sha)
    return {**result, "ledger_seq": state["seq"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("readiness", "freeze", "verify",
                                            "verify-static"),
                        nargs="?", default="readiness")
    args = parser.parse_args()
    result = {"readiness": readiness, "freeze": freeze, "verify": verify,
              "verify-static": verify_static}[args.command]()
    print(json.dumps(result, sort_keys=True))
