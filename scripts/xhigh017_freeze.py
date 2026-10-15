#!/usr/bin/env python3
"""Read-only XHIGH017 gates and explicit one-time two-row assignment freeze.

No command here invokes a paid model. The paid runner additionally requires a
separate independent review of the frozen assignment.
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
from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402
from agent_economic_trust.xhigh017_budget import exact_prior_holds  # noqa: E402
from agent_economic_trust.xhigh017_plan import (CANONICAL_LEDGER, ROWS, digest,
    make_schedule, prospective_manifest, per_row_reserve, required_headroom)  # noqa: E402

GATE = ROOT / "artifacts/gates/ERC8183_XHIGH017"
ASSIGNMENT = GATE / "assignment-001"
LOCK = GATE / "first-freeze.lock.json"
ASSIGNMENT_REVIEW = GATE / "independent-assignment-review-001.json"
SOURCE_REVIEW = ROOT / "artifacts/prospective/ERC8183_XHIGH017/source-review-001.json"
OFFLINE = ROOT / "artifacts/prospective/ERC8183_XHIGH017/offline-native-001"
FEE015_GATE = ROOT / "artifacts/gates/ERC8183_FEE015"
FEE015_COLLECTION = FEE015_GATE / "collection-005-final.json"
FEE015_COLLECTION_SHA = "c5add35a657b6038de0f14cae106a46b48057e3428eb7db16b0b399314a27962"
FEE015_REVIEW = FEE015_GATE / "independent-results-review-final.json"
FEE015_REVIEW_SHA = "7fdb6aee08c536faa0a6734b4510b4d99429ec12de2c35c6a920f587dd4dafec"
PARTIAL014_GATE = ROOT / "artifacts/gates/ERC8183_PARTIAL_CLAIM014"
PARTIAL014_REVIEW = PARTIAL014_GATE / "independent-results-review-final.json"

# Explicit dependencies are captured at source review and frozen by path/hash.
# The earlier studies also retain their own independent sealed-source gates.
DEPENDENCIES = (
    "AGENTS.md", "UPSTREAM_PINNED.json",
    "docs/PROSPECTIVE_XHIGH_SENSITIVITY017_DESIGN.md",
    "scripts/run_erc8183_local.py", "scripts/run_erc8183_fee_control.py",
    "scripts/verify_erc8183_fee_control.py", "scripts/verify_erc8183_fee_readiness.py",
    "scripts/partial014_freeze.py",
    "scripts/partial014_collect.py", "scripts/fee015_freeze.py",
    "scripts/fee015_collect.py", "scripts/collect_x402_live012.py",
    "src/agent_economic_trust/ap2_live_fixture.py",
    "src/agent_economic_trust/core.py",
    "src/agent_economic_trust/erc8183_fee_plan.py",
    "src/agent_economic_trust/erc8183_fee_native.py",
    "src/agent_economic_trust/erc8183_fee_native_verifier.py",
    "src/agent_economic_trust/erc8183_fee_remote.py",
    "src/agent_economic_trust/fee012_offline.py",
    "src/agent_economic_trust/mpp005_boundary.py",
    "src/agent_economic_trust/mpp005_plan.py",
    "src/agent_economic_trust/mpp008_pricing.py",
    "src/agent_economic_trust/remote_budget.py",
    "src/agent_economic_trust/reporting.py",
    "src/agent_economic_trust/x402_live012_remote.py",
)
OWN_SOURCES = (
    "src/agent_economic_trust/xhigh017_budget.py",
    "src/agent_economic_trust/xhigh017_plan.py",
    "src/agent_economic_trust/xhigh017_task.py",
    "src/agent_economic_trust/xhigh017_boundary.py",
    "src/agent_economic_trust/xhigh017_remote.py",
    "src/agent_economic_trust/xhigh017_offline.py",
    "scripts/xhigh017_freeze.py", "scripts/xhigh017_collect.py",
    "scripts/run_xhigh017.py", "scripts/verify_xhigh017_offline.py",
    "tests/test_xhigh017_source.py",
)


def sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("XHIGH017 sealed file missing or symlinked")
    return sha256(path.read_bytes()).hexdigest()


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"


def _new(path: Path, value: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


def _canonical_root() -> None:
    if ROOT.resolve() != canonical_project_root().resolve():
        raise ValueError("XHIGH017 may freeze only in the canonical shared-ledger checkout")


def source_names() -> tuple[str, ...]:
    return tuple(sorted(set(DEPENDENCIES) | set(OWN_SOURCES)))


def source_inventory() -> dict[str, str]:
    return {name: sha(ROOT / name) for name in source_names()}


def _clean_sources() -> None:
    names = source_names()
    if subprocess.run(["git", "ls-files", "--error-unmatch", "--", *names],
                      cwd=ROOT, capture_output=True).returncode != 0:
        raise ValueError("XHIGH017 source closure is not versioned")
    if subprocess.run(["git", "status", "--porcelain", "--", *names],
                      cwd=ROOT, capture_output=True, text=True,
                      check=True).stdout.strip():
        raise ValueError("XHIGH017 source closure has uncommitted changes")


def _runtime() -> dict:
    from scripts.verify_erc8183_fee_readiness import installed_runtime_versions
    if version("orbit") != "1.0.3" or version("inspect_ai") != "0.3.263":
        raise ValueError("XHIGH017 ORBIT/Inspect pins differ")
    return installed_runtime_versions()


def _offline() -> dict:
    from agent_economic_trust.xhigh017_offline import verify
    report = verify(OFFLINE)
    if report["status"] != "PASS" or report["paid_model_calls"] != 0:
        raise ValueError("XHIGH017 official native controls did not replay")
    return {"report_sha256": sha(OFFLINE / "report.json"),
            "status": "PASS", "paid_model_calls": 0}


def _ledger() -> dict:
    state = BudgetLedger(CANONICAL_LEDGER).snapshot()
    if (state.get("cap_usd") != "50" or state.get("blocked")
            or state.get("unknown_run_ids")):
        raise ValueError("XHIGH017 USD50 lifetime ledger is blocked")
    exact_prior_holds(state)
    return state


def _fee015_closure() -> dict:
    from scripts.fee015_freeze import verify_static
    verify_static()
    if sha(FEE015_COLLECTION) != FEE015_COLLECTION_SHA or sha(FEE015_REVIEW) != FEE015_REVIEW_SHA:
        raise ValueError("XHIGH017 reviewed FEE015 predecessor changed")
    collection = json.loads(FEE015_COLLECTION.read_bytes())
    review = json.loads(FEE015_REVIEW.read_bytes())
    if (collection.get("schema") != "fee015-itt-collection-v1"
            or tuple(collection.get(k) for k in (
                "planned_episodes", "completed_episodes", "stopped_episodes",
                "pending_episodes")) != (5, 5, 0, 0)
            or review.get("collection_sha256") != FEE015_COLLECTION_SHA
            or review.get("freeze_or_paid_authorization") is not False):
        raise ValueError("XHIGH017 FEE015 terminal evidence differs")
    return {"collection_sha256": FEE015_COLLECTION_SHA,
            "independent_review_sha256": FEE015_REVIEW_SHA}


def _partial014_closure() -> dict:
    from scripts.partial014_freeze import verify_static
    from scripts.partial014_collect import collect
    verify_static()
    candidates = sorted(PARTIAL014_GATE.glob("collection-*-final.json"))
    if len(candidates) != 1:
        raise ValueError("XHIGH017 requires one terminal PARTIAL014 collection")
    path = candidates[0]
    collection = json.loads(path.read_bytes())
    review = json.loads(PARTIAL014_REVIEW.read_bytes())
    counts = [collection.get(key) for key in (
        "completed_episodes", "observed_incomplete_episodes",
        "stopped_episodes", "pending_episodes")]
    if (collection.get("schema") != "partial014-itt-collection-v1"
            or collection.get("planned_episodes") != 5
            or len(collection.get("rows", [])) != 5
            or any(type(n) is not int or n < 0 for n in counts)
            or sum(counts) != 5
            or review.get("schema") != "partial014-independent-results-review-v1"
            or not str(review.get("status", "")).startswith("REVIEW_COMPLETE")
            or not isinstance(review.get("independent_replay"), dict)
            or review["independent_replay"].get("saved_collector_replayed_exactly") is not True
            or review.get("collection_path") != str(path.relative_to(ROOT))
            or review.get("collection_sha256") != sha(path)
            or review.get("reviewer_id") in (None, "", "/root/xhigh017_source")
            or review.get("freeze_or_paid_authorization") is not False):
        raise ValueError("XHIGH017 PARTIAL014 independent closure differs")
    replay = collect()
    for key in ("study", "assignment_manifest_sha256", "planned_episodes",
                "completed_episodes", "observed_incomplete_episodes",
                "stopped_episodes", "pending_episodes", "rows"):
        if replay[key] != collection[key]:
            raise ValueError("XHIGH017 PARTIAL014 raw replay differs from reviewed collection")
    return {"collection_path": str(path.relative_to(ROOT)),
            "collection_sha256": sha(path),
            "independent_review_sha256": sha(PARTIAL014_REVIEW),
            "denominator": {key: collection[key] for key in (
                "completed_episodes", "observed_incomplete_episodes",
                "stopped_episodes", "pending_episodes")}}


def _source_review(sources: dict, predecessor: dict) -> dict:
    review = json.loads(SOURCE_REVIEW.read_bytes())
    if (SOURCE_REVIEW.is_symlink()
            or review.get("schema") != "xhigh017-independent-source-review-v1"
            or review.get("status") != "GO_SOURCE_MERGE_ONLY"
            or review.get("source_inventory_sha256") != digest(sources)
            or review.get("partial014_collection_sha256") != predecessor["partial014"]["collection_sha256"]
            or review.get("reviewer_id") in (None, "", "/root/xhigh017_source")
            or review.get("freeze_or_paid_authorization") is not False):
        raise ValueError("XHIGH017 independent source review missing or differs")
    return {"path": str(SOURCE_REVIEW.relative_to(ROOT)),
            "sha256": sha(SOURCE_REVIEW), "reviewer_id": review["reviewer_id"]}


def _predecessor() -> dict:
    return {"fee015": _fee015_closure(), "partial014": _partial014_closure()}


def _budget(state: dict, prices: dict) -> dict:
    reserve = per_row_reserve(prices)
    required = required_headroom(prices, ROWS)
    available = Decimal(state["available_usd"])
    if required > available:
        raise ValueError("XHIGH017 two-row block plus contingency exceeds USD50")
    return {"per_row_worst_case_usd": str(reserve),
            "full_block_plus_contingency_usd": str(required),
            "ledger_available_usd": str(available),
            "ledger_seq": state["seq"],
            "affordable": True}


def readiness() -> dict:
    checks = {}
    values = {}
    for name, fn in (
        ("canonical_root", _canonical_root),
        ("clean_versioned_source", _clean_sources),
        ("runtime", _runtime),
        ("offline_native", _offline),
        ("source_inventory", source_inventory),
        ("predecessor", _predecessor),
        ("ledger", _ledger),
        ("pricing", pricing_snapshots),
    ):
        try:
            values[name] = fn()
            checks[name] = "PASS"
        except Exception as exc:
            checks[name] = type(exc).__name__ + ": " + str(exc)
    for name, fn in (
        ("independent_source_review", lambda: _source_review(
            values["source_inventory"], values["predecessor"])),
        ("full_block_budget", lambda: _budget(values["ledger"], values["pricing"])),
    ):
        try:
            values[name] = fn()
            checks[name] = "PASS"
        except Exception as exc:
            checks[name] = type(exc).__name__ + ": " + str(exc)
    ready = all(v == "PASS" for v in checks.values())
    return {"status": "READY" if ready else "BLOCKED", "would_freeze": ready,
            "would_call_paid_model": False, "checks": checks,
            "budget": values.get("full_block_budget"), "model_calls": 0}


def freeze(*, seed_hex: str | None = None) -> dict:
    _canonical_root()
    if os.environ.get("XHIGH017_FREEZE_ALLOWED") != "true":
        raise ValueError("explicit XHIGH017 one-time freeze switch required")
    if LOCK.exists() or ASSIGNMENT.exists():
        raise FileExistsError("XHIGH017 already or partially frozen; no reroll")
    if readiness()["status"] != "READY":
        raise ValueError("XHIGH017 readiness has uncleared gates")
    state = _ledger()
    sources, predecessor = source_inventory(), _predecessor()
    prices = pricing_snapshots()
    seed = seed_hex if seed_hex is not None else secrets.token_hex(32)
    rows = make_schedule(seed)
    payload = {**prospective_manifest(seed, rows),
        "schema": "xhigh017-first-assignment-v1",
        "status": "FROZEN_NOT_EXECUTED",
        "source_sha256": sources,
        "source_inventory_sha256": digest(sources),
        "runtime_pins": _runtime(),
        "offline_readiness": _offline(),
        "independent_source_review": _source_review(sources, predecessor),
        "predecessor": predecessor,
        "public_pricing_snapshot": prices,
        "budget_at_freeze": {key: state[key] for key in
            ("seq", "last_hash", "cap_usd", "available_usd")},
        "budget_gate": _budget(state, prices),
        "prior_ledger_run_ids": sorted(state["runs"]),
        "prior_ledger_runs_sha256": digest(state["runs"]),
        "model_tier": "REAL_LLM_REMOTE_APPROVED",
        "payment_tier": "NATIVE_LOCAL_PROTOCOL",
        "route_support_is_not_proof_effort_honored": True,
        "no_reroll_or_model_substitution": True}
    if BudgetLedger(CANONICAL_LEDGER).snapshot()["last_hash"] != state["last_hash"]:
        raise ValueError("XHIGH017 ledger changed during freeze")
    GATE.mkdir(parents=True, exist_ok=True)
    ASSIGNMENT.mkdir(mode=0o700)
    _new(ASSIGNMENT / "seed.hex", (seed + "\n").encode())
    _new(ASSIGNMENT / "private_rows.json", _json([asdict(row) for row in rows]))
    _new(ASSIGNMENT / "assignment_manifest.json", _json(payload))
    lock = {"schema": "xhigh017-one-time-freeze-v1",
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
        raise ValueError("XHIGH017 private rows differ from frozen seed")
    path = ASSIGNMENT / "assignment_manifest.json"
    frozen = json.loads(path.read_bytes())
    preview = prospective_manifest(seed, rows)
    if any(frozen.get(k) != v for k, v in preview.items()
           if k not in {"schema", "status"}):
        raise ValueError("XHIGH017 frozen assignment differs from preview")
    if (frozen.get("schema") != "xhigh017-first-assignment-v1"
            or frozen.get("status") != "FROZEN_NOT_EXECUTED"
            or json.loads(LOCK.read_bytes()) != {
                "schema": "xhigh017-one-time-freeze-v1",
                "assignment_manifest_sha256": sha(path),
                "seed_commitment_sha256": frozen["seed_commitment_sha256"]}):
        raise ValueError("XHIGH017 one-time manifest/lock differs")
    return frozen, sha(path), rows


def verify_static() -> dict:
    _canonical_root()
    frozen, manifest_sha, rows = load_assignment()
    sealed = frozen.get("source_sha256")
    if not isinstance(sealed, dict) or set(sealed) != set(source_names()):
        raise ValueError("XHIGH017 sealed source set differs")
    sources = {name: sha(ROOT / name) for name in sealed}
    predecessor = _predecessor()
    if (sources != sealed or digest(sources) != frozen["source_inventory_sha256"]
            or _source_review(sources, predecessor) != frozen["independent_source_review"]
            or frozen["predecessor"] != predecessor
            or frozen["offline_readiness"] != _offline()):
        raise ValueError("XHIGH017 sealed source, controls or predecessor changed")
    return {"status": "SEALED_STATIC", "assignment_manifest_sha256": manifest_sha,
            "rows": len(rows), "model_calls": 0}


def verify() -> dict:
    result = verify_static()
    frozen, manifest_sha, _ = load_assignment()
    state = _ledger()
    earlier = frozen["budget_at_freeze"]
    lines = CANONICAL_LEDGER.read_bytes().splitlines()
    if (state["seq"] < earlier["seq"] or len(lines) <= earlier["seq"]
            or json.loads(lines[earlier["seq"]])["hash"] != earlier["last_hash"]):
        raise ValueError("XHIGH017 frozen ledger ancestor differs")
    review = json.loads(ASSIGNMENT_REVIEW.read_bytes())
    if (ASSIGNMENT_REVIEW.is_symlink()
            or review.get("schema") != "xhigh017-independent-assignment-review-v1"
            or review.get("status") != "GO_FROZEN_TWO_ROW_ASSIGNMENT"
            or review.get("assignment_manifest_sha256") != manifest_sha
            or review.get("source_inventory_sha256") != frozen["source_inventory_sha256"]
            or review.get("budget_gate") != frozen["budget_gate"]
            or review.get("reviewer_id") in (None, "", "/root/xhigh017_source")
            or review.get("paid_model_calls_at_review") != 0):
        raise ValueError("XHIGH017 independent frozen assignment review differs")
    return {**result, "ledger_seq": state["seq"],
            "independent_assignment_review_sha256": sha(ASSIGNMENT_REVIEW)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("readiness", "freeze", "verify", "verify-static"),
                        nargs="?", default="readiness")
    args = parser.parse_args()
    print(json.dumps({"readiness": readiness, "freeze": freeze,
                      "verify": verify, "verify-static": verify_static}[args.command](),
                     sort_keys=True))
