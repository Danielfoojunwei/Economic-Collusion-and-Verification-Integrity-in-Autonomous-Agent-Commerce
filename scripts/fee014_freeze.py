#!/usr/bin/env python3
"""Read-only FEE014 role-swap readiness and explicit one-time assignment freeze.

The independent source review, native scripted controls, predecessor closure,
full five-row headroom and canonical checkout are all required before freezing.
No command here invokes a remote model or native payment controller.
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

from agent_economic_trust.fee014_budget import exact_prior_holds  # noqa: E402
from agent_economic_trust.fee014_plan import (  # noqa: E402
    CANONICAL_LEDGER, ROWS, canonical, digest, make_schedule, per_row_reserve,
    prospective_manifest, required_headroom)
from agent_economic_trust.mpp005_plan import canonical_project_root  # noqa: E402
from agent_economic_trust.mpp008_pricing import pricing_snapshots  # noqa: E402
from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402

GATE = ROOT / "artifacts/gates/ERC8183_FEE014"
ASSIGNMENT = GATE / "assignment-001"
LOCK = GATE / "first-freeze.lock.json"
CLEARANCE = GATE / "cross-study-clearance-001.json"
REVIEW = ROOT / "artifacts/prospective/ERC8183_FEE014/source-review-001.json"
OFFLINE = ROOT / "artifacts/prospective/ERC8183_FEE014/offline-native-001"
FEE013_GATE = ROOT / "artifacts/gates/ERC8183_FEE013"

DEPENDENCIES = (
    "AGENTS.md", "UPSTREAM_PINNED.json",
    "docs/PROSPECTIVE_FEE_ROLE_SWAP_REPLICATION_2026-10-15.md",
    "scripts/run_erc8183_local.py", "scripts/run_erc8183_fee_control.py",
    "scripts/verify_erc8183_fee_control.py",
    "scripts/verify_erc8183_fee_readiness.py",
    "scripts/freeze_x402_live012.py",
    "src/agent_economic_trust/ap2_live_fixture.py",
    "src/agent_economic_trust/core.py",
    "src/agent_economic_trust/erc8183_fee_plan.py",
    "src/agent_economic_trust/erc8183_fee_native.py",
    "src/agent_economic_trust/erc8183_fee_native_verifier.py",
    "src/agent_economic_trust/erc8183_fee_remote.py",
    "src/agent_economic_trust/mpp005_boundary.py",
    "src/agent_economic_trust/mpp005_plan.py",
    "src/agent_economic_trust/mpp008_budget.py",
    "src/agent_economic_trust/mpp008_plan.py",
    "src/agent_economic_trust/mpp008_pricing.py",
    "src/agent_economic_trust/remote_pricing.py",
    "src/agent_economic_trust/remote_budget.py",
    "src/agent_economic_trust/reporting.py",
    "src/agent_economic_trust/x402_live012_budget.py",
    "src/agent_economic_trust/x402_live011_budget.py",
    "src/agent_economic_trust/x402_live012_remote.py",
    "scripts/collect_x402_live012.py",
    "scripts/fee013_collect.py",
    "scripts/fee013_freeze.py",
    "scripts/verify_fee013_offline.py",
    "src/agent_economic_trust/fee013_budget.py",
    "src/agent_economic_trust/fee013_offline.py",
    "src/agent_economic_trust/fee013_plan.py",
    "src/agent_economic_trust/fee013_remote.py",
    "src/agent_economic_trust/fee013_task.py",
    "src/agent_economic_trust/fee013_boundary.py",
)


def sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("FEE014 sealed evidence missing or symlinked")
    return sha256(path.read_bytes()).hexdigest()


def _json(value: object) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True,
                      allow_nan=False).encode() + b"\n"


def _new(path: Path, payload: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _canonical_root() -> None:
    if ROOT.resolve() != canonical_project_root().resolve():
        raise ValueError("FEE014 can freeze only in canonical shared-ledger checkout")


def source_names() -> tuple[str, ...]:
    fresh = [str(path.relative_to(ROOT)) for pattern in (
        "src/agent_economic_trust/fee014*.py", "scripts/*fee014*.py",
        "tests/test_fee014*.py", "docs/*FEE014*.md")
        for path in ROOT.glob(pattern)]
    return tuple(sorted(set(DEPENDENCIES) | set(fresh)))


def source_inventory() -> dict[str, str]:
    names = source_names()
    if not all((ROOT / name).is_file() for name in names):
        raise ValueError("FEE014 source closure file missing")
    return {name: sha(ROOT / name) for name in names}


def clean_versioned_sources() -> bool:
    names = source_names()
    listed = subprocess.run(["git", "ls-files", "--error-unmatch", "--", *names],
                            cwd=ROOT, capture_output=True).returncode == 0
    clean = not subprocess.run(["git", "status", "--porcelain", "--", *names],
                               cwd=ROOT, capture_output=True, text=True,
                               check=True).stdout.strip()
    return listed and clean


def source_review(sources: dict[str, str]) -> dict:
    review = json.loads(REVIEW.read_bytes())
    if (REVIEW.is_symlink() or review.get("schema") != "fee014-source-review-v1"
            or review.get("status") != "GO_SOURCE_MERGE_ONLY"
            or review.get("source_inventory_sha256") != digest(sources)
            or review.get("reviewer_id") in (None, "", "/root/fee014_successor",
                                               "/root/fee014_runtime",
                                               "/root/fee014_implementer",
                                               "/root/role_swap_live_implementation")
            or review.get("freeze_or_paid_authorization") is not False):
        raise ValueError("independent FEE014 source review differs")
    return {"path": str(REVIEW.relative_to(ROOT)), "sha256": sha(REVIEW),
            "reviewer_id": review["reviewer_id"]}


def _runtime() -> dict:
    from scripts.verify_erc8183_fee_readiness import installed_runtime_versions
    versions = installed_runtime_versions()
    if version("orbit") != "1.0.3" or version("inspect_ai") != "0.3.263":
        raise ValueError("pinned ORBIT or Inspect runtime differs")
    return versions


def _offline() -> dict:
    from scripts.verify_fee014_offline import verify
    report = verify(OFFLINE)
    if report.get("status") != "PASS" or report.get("paid_model_calls") != 0:
        raise ValueError("FEE014 official native controls not replayed")
    return {"report_sha256": sha(OFFLINE / "report.json"),
            "status": report["status"], "paid_model_calls": 0}


def _ledger() -> dict:
    state = BudgetLedger(CANONICAL_LEDGER).snapshot()
    if (state.get("cap_usd") != "50" or state.get("blocked")
            or state.get("unknown_run_ids")):
        raise ValueError("FEE014 USD50 ledger is blocked")
    exact_prior_holds(state)
    return state


def _fee013_terminal_collection() -> tuple[Path, dict]:
    """Find one archived terminal predecessor denominator; never select a partial result."""
    paths = sorted(FEE013_GATE.glob("collection-*.json"))
    final = []
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError("FEE013 collection archive is symlinked or missing")
        saved = json.loads(path.read_bytes())
        if saved.get("schema") != "fee013-itt-collection-v1":
            continue
        if saved.get("planned_episodes") != 6 or len(saved.get("rows", [])) != 6:
            raise ValueError("FEE013 assigned denominator differs")
        complete = saved.get("completed_episodes", 0)
        stopped = saved.get("stopped_episodes", 0)
        pending = saved.get("pending_episodes", 0)
        incomplete = saved.get("observed_incomplete_episodes", 0)
        if complete + stopped + pending + incomplete != 6:
            raise ValueError("FEE013 collection counts differ")
        if (complete + incomplete == 6 and stopped == pending == 0
                or stopped == 1 and pending == 5 - complete - incomplete):
            final.append((path, saved))
    if len(final) != 1:
        raise ValueError("exactly one terminal FEE013 collection required")
    return final[0]


def clearance_preview(state: dict) -> dict:
    """Replay FEE013's immutable terminal result before any role-swap freeze."""
    from agent_economic_trust.erc8183_fee_native_verifier import verify_file
    from scripts.fee013_collect import collect as collect_fee013
    from scripts.fee013_freeze import load_assignment, verify_static

    verify_static()
    frozen, fee013_sha, fee013_rows = load_assignment()
    path, saved = _fee013_terminal_collection()
    replay = collect_fee013()
    replay["shared_ledger_seq"] = saved.get("shared_ledger_seq")
    if (saved != replay
            or saved.get("assignment_manifest_sha256") != fee013_sha
            or saved.get("study") != frozen["study"]
            or [item["episode_id"] for item in saved["rows"]]
               != [row.episode_id for row in fee013_rows]):
        raise ValueError("FEE013 terminal collection fails independent replay")
    stopped_receipts = {}
    for row, result in zip(fee013_rows, saved["rows"]):
        if result["status"] != "STOPPED":
            continue
        directory = FEE013_GATE / "runs-001/episodes" / row.episode_id
        stop = directory / "STOPPED.json"
        candidates = [directory / "erc8183" / name
                      for name in ("native-evidence.json", "native-partial.json")
                      if (directory / "erc8183" / name).is_file()]
        if len(candidates) != 1:
            raise ValueError("FEE013 stopped row needs one native receipt")
        native = verify_file(candidates[0], row)
        if native["status"] not in {"COMPLETE_VERIFIED", "FUNDED_SUBMITTED_VERIFIED"}:
            raise ValueError("FEE013 stopped native receipt unverified")
        stopped_receipts[row.episode_id] = {
            "stop_sha256": sha(stop),
            "native_path": str(candidates[0].relative_to(ROOT)),
            "native_sha256": sha(candidates[0]),
            "native_status": native["status"],
            "ledger_run_id": json.loads(stop.read_bytes())["ledger_run_id"],
        }
    exact = exact_prior_holds(state)
    return {"schema": "fee014-cross-study-clearance-v1",
            "status": "GO_AFTER_FEE013_TERMINAL_ARCHIVE",
            "fee013_assignment_sha256": fee013_sha,
            "fee013_collection_path": str(path.relative_to(ROOT)),
            "fee013_collection_sha256": sha(path),
            "fee013_completed_episodes": saved["completed_episodes"],
            "fee013_stopped_episodes": saved["stopped_episodes"],
            "fee013_pending_episodes": saved["pending_episodes"],
            "fee013_stopped_receipts": stopped_receipts,
            "exact_prior_holds": exact,
            "ledger_at_clearance": {key: state[key] for key in
                                    ("seq", "last_hash", "cap_usd")},
            "no_new_paid_calls_authorized_by_clearance": True}


def write_clearance() -> dict:
    _canonical_root()
    if os.environ.get("FEE014_CLEARANCE_ALLOWED") != "true":
        raise ValueError("explicit FEE014 predecessor clearance switch required")
    if CLEARANCE.exists() or ASSIGNMENT.exists() or LOCK.exists():
        raise FileExistsError("FEE014 clearance/freeze already exists")
    state = _ledger()
    payload = clearance_preview(state)
    if BudgetLedger(CANONICAL_LEDGER).snapshot()["last_hash"] != state["last_hash"]:
        raise ValueError("ledger changed during FEE014 clearance")
    GATE.mkdir(parents=True, exist_ok=True)
    _new(CLEARANCE, _json(payload))
    return {"status": "CLEARANCE_SAVED_NO_PAID_CALL", "sha256": sha(CLEARANCE)}


def clearance(state: dict) -> dict:
    saved = json.loads(CLEARANCE.read_bytes())
    if CLEARANCE.is_symlink():
        raise ValueError("FEE014 clearance symlinked")
    original = saved.get("ledger_at_clearance")
    if (not isinstance(original, dict) or type(original.get("seq")) is not int
            or original["seq"] < 0 or original.get("cap_usd") != "50"
            or original["seq"] > state["seq"]):
        raise ValueError("FEE014 clearance ledger ancestor differs")
    lines = CANONICAL_LEDGER.read_bytes().splitlines()
    if (len(lines) <= original["seq"]
            or json.loads(lines[original["seq"]])["hash"] != original["last_hash"]):
        raise ValueError("FEE014 clearance ledger hash is not ancestor")
    preview = clearance_preview(state)
    preview["ledger_at_clearance"] = original
    if saved != preview:
        raise ValueError("FEE014 predecessor clearance bytes/facts differ")
    return {"path": str(CLEARANCE.relative_to(ROOT)), "sha256": sha(CLEARANCE),
            "ledger_at_clearance": original}


def _budget(state: dict, prices: dict) -> dict:
    per = per_row_reserve(prices)
    needed = required_headroom(prices, ROWS)
    if needed > Decimal(state["available_usd"]):
        raise ValueError("full five-row FEE014 block plus contingency exceeds USD50")
    return {"per_row_worst_case_usd": str(per),
            "full_block_plus_contingency_residual_usd": str(needed),
            "ledger_available_usd": state["available_usd"]}


def readiness() -> dict:
    checks: dict[str, str] = {}
    values = {}
    for name, fn in (("canonical_checkout", _canonical_root),
                     ("one_time_freeze_available", lambda: (_ for _ in ()).throw(
                         FileExistsError("already frozen")) if LOCK.exists() or
                         ASSIGNMENT.exists() else None),
                     ("source_clean", lambda: None if clean_versioned_sources()
                         else (_ for _ in ()).throw(ValueError("source not committed"))),
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
    for name, fn in (("independent_source_review", lambda: source_review(
                         values["source_inventory"])),
                     ("cross_study_clearance", lambda: clearance(
                         values["shared_ledger"])),
                     ("full_block_budget", lambda: _budget(
                         values["shared_ledger"], values["current_catalog"]))):
        try:
            values[name] = fn()
            checks[name] = "PASS"
        except Exception as exc:
            checks[name] = type(exc).__name__ + ": " + str(exc)
    ready = all(value == "PASS" for value in checks.values())
    return {"status": "READY" if ready else "BLOCKED", "would_freeze": ready,
            "would_call_paid_model": False, "checks": checks,
            "budget": values.get("full_block_budget"), "model_calls": 0}


def freeze(*, seed_hex: str | None = None) -> dict:
    _canonical_root()
    if os.environ.get("FEE014_FREEZE_ALLOWED") != "true":
        raise ValueError("explicit FEE014 one-time freeze switch required")
    if LOCK.exists() or ASSIGNMENT.exists():
        raise FileExistsError("FEE014 already or partially frozen; no reroll")
    if readiness()["status"] != "READY":
        raise ValueError("FEE014 readiness has uncleared gates")
    state = _ledger()
    sources, runtime, offline = source_inventory(), _runtime(), _offline()
    review, prior = source_review(sources), clearance(state)
    prices = pricing_snapshots()
    seed = seed_hex if seed_hex is not None else secrets.token_hex(32)
    rows = make_schedule(seed)
    payload = {**prospective_manifest(seed, rows),
               "schema": "fee014-first-assignment-v1",
               "status": "FROZEN_NOT_EXECUTED",
               "source_sha256": sources,
               "source_inventory_sha256": digest(sources),
               "runtime_pins": runtime,
               "offline_readiness": offline,
               "independent_source_review": review,
               "cross_study_clearance": prior,
               "public_pricing_snapshot": prices,
               "budget_at_freeze": {key: state[key] for key in
                                    ("seq", "last_hash", "cap_usd", "available_usd")},
               "budget_gate": _budget(state, prices),
               "prior_ledger_run_ids": sorted(state["runs"]),
               "prior_ledger_runs_sha256": digest(state["runs"]),
               "model_tier": "REAL_LLM_REMOTE_APPROVED",
               "payment_tier": "NATIVE_LOCAL_PROTOCOL",
               "no_reroll_or_model_substitution": True}
    if BudgetLedger(CANONICAL_LEDGER).snapshot()["last_hash"] != state["last_hash"]:
        raise ValueError("shared ledger changed during FEE014 freeze")
    GATE.mkdir(parents=True, exist_ok=True)
    ASSIGNMENT.mkdir(mode=0o700)
    _new(ASSIGNMENT / "seed.hex", (seed + "\n").encode())
    _new(ASSIGNMENT / "private_rows.json", _json([asdict(row) for row in rows]))
    _new(ASSIGNMENT / "assignment_manifest.json", _json(payload))
    lock = {"schema": "fee014-one-time-freeze-v1",
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
        raise ValueError("FEE014 private rows differ from one-time seed")
    manifest = ASSIGNMENT / "assignment_manifest.json"
    frozen = json.loads(manifest.read_bytes())
    preview = prospective_manifest(seed, rows)
    for key, value in preview.items():
        if key not in {"schema", "status"} and frozen.get(key) != value:
            raise ValueError("FEE014 frozen assignment differs from seed preview")
    if (frozen.get("schema") != "fee014-first-assignment-v1"
            or frozen.get("status") != "FROZEN_NOT_EXECUTED"
            or json.loads(LOCK.read_bytes()) != {
                "schema": "fee014-one-time-freeze-v1",
                "assignment_manifest_sha256": sha(manifest),
                "seed_commitment_sha256": frozen["seed_commitment_sha256"]}):
        raise ValueError("FEE014 one-time manifest/lock differs")
    return frozen, sha(manifest), rows


def verify_static() -> dict:
    _canonical_root()
    frozen, assignment_sha, rows = load_assignment()
    sources = source_inventory()
    if (frozen["source_sha256"] != sources
            or frozen["source_inventory_sha256"] != digest(sources)
            or frozen["independent_source_review"] != source_review(sources)
            or frozen["offline_readiness"] != _offline()):
        raise ValueError("FEE014 sealed source, review or native controls changed")
    prior = frozen["cross_study_clearance"]
    if (prior["sha256"] != sha(CLEARANCE)
            or prior["path"] != str(CLEARANCE.relative_to(ROOT))):
        raise ValueError("FEE014 predecessor clearance changed")
    return {"status": "SEALED_STATIC", "assignment_manifest_sha256": assignment_sha,
            "rows": len(rows), "model_calls": 0}


def verify() -> dict:
    result = verify_static()
    frozen, _, _ = load_assignment()
    state = _ledger()
    earlier = frozen["budget_at_freeze"]
    lines = CANONICAL_LEDGER.read_bytes().splitlines()
    if (state["seq"] < earlier["seq"] or len(lines) <= earlier["seq"]
            or json.loads(lines[earlier["seq"]])["hash"] != earlier["last_hash"]
            or frozen["cross_study_clearance"] != clearance(state)):
        raise ValueError("FEE014 frozen ledger predecessor differs")
    return {**result, "ledger_seq": state["seq"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("readiness", "clearance", "freeze",
                                            "verify", "verify-static"),
                        nargs="?", default="readiness")
    args = parser.parse_args()
    result = {"readiness": readiness, "clearance": write_clearance,
              "freeze": freeze, "verify": verify,
              "verify-static": verify_static}[args.command]()
    print(json.dumps(result, sort_keys=True))
