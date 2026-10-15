#!/usr/bin/env python3
"""Read-only FEE013 readiness and explicit one-time assignment freeze.

The independent source review, native scripted controls, predecessor closure,
full six-row headroom and canonical checkout are all required before freezing.
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

from agent_economic_trust.fee013_budget import exact_prior_holds, same_usd_amount  # noqa: E402
from agent_economic_trust.fee013_plan import (  # noqa: E402
    CANONICAL_LEDGER, ROWS, canonical, digest, make_schedule, per_row_reserve,
    prospective_manifest, required_headroom)
from agent_economic_trust.mpp005_plan import canonical_project_root  # noqa: E402
from agent_economic_trust.mpp008_pricing import pricing_snapshots  # noqa: E402
from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402

GATE = ROOT / "artifacts/gates/ERC8183_FEE013"
ASSIGNMENT = GATE / "assignment-001"
LOCK = GATE / "first-freeze.lock.json"
CLEARANCE = GATE / "cross-study-clearance-001.json"
REVIEW = ROOT / "artifacts/prospective/ERC8183_FEE013/source-review-001.json"
OFFLINE = ROOT / "artifacts/prospective/ERC8183_FEE013/offline-native-001"
X402_FINAL = ROOT / "artifacts/gates/X402_LIVE012/collection-004-final.json"
MPP_FINAL = ROOT / "artifacts/gates/MPP011/collection-005-final.json"
FEE012_COLLECTION = ROOT / "artifacts/gates/ERC8183_FEE012/collection-001-after-first-stop.json"
FEE012_FORENSICS = ROOT / "artifacts/gates/ERC8183_FEE012/forensics-001.json"
FEE012_STOP = ROOT / "artifacts/gates/ERC8183_FEE012/runs-001/episodes/fee012-9d83103c141f26e01bb20f64/STOPPED.json"
FEE012_NATIVE = FEE012_STOP.parent / "erc8183/native-evidence.json"

DEPENDENCIES = (
    "AGENTS.md", "UPSTREAM_PINNED.json",
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
    "scripts/fee012_collect.py",
    "scripts/fee012_freeze.py",
    "scripts/verify_fee012_offline.py",
    "src/agent_economic_trust/fee012_budget.py",
    "src/agent_economic_trust/fee012_offline.py",
    "src/agent_economic_trust/fee012_plan.py",
    "src/agent_economic_trust/fee012_remote.py",
    "src/agent_economic_trust/fee012_task.py",
    "src/agent_economic_trust/fee012_boundary.py",
)


def sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("FEE013 sealed evidence missing or symlinked")
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
        raise ValueError("FEE013 can freeze only in canonical shared-ledger checkout")


def source_names() -> tuple[str, ...]:
    fresh = [str(path.relative_to(ROOT)) for pattern in (
        "src/agent_economic_trust/fee013*.py", "scripts/*fee013*.py",
        "tests/test_fee013*.py", "docs/*FEE013*.md")
        for path in ROOT.glob(pattern)]
    return tuple(sorted(set(DEPENDENCIES) | set(fresh)))


def source_inventory() -> dict[str, str]:
    names = source_names()
    if not all((ROOT / name).is_file() for name in names):
        raise ValueError("FEE013 source closure file missing")
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
    if (REVIEW.is_symlink() or review.get("schema") != "fee013-source-review-v1"
            or review.get("status") != "GO_SOURCE_MERGE_ONLY"
            or review.get("source_inventory_sha256") != digest(sources)
            or review.get("reviewer_id") in (None, "", "/root/fee013_successor",
                                               "/root/fee013_runtime",
                                               "/root/fee013_implementer")
            or review.get("freeze_or_paid_authorization") is not False):
        raise ValueError("independent FEE013 source review differs")
    return {"path": str(REVIEW.relative_to(ROOT)), "sha256": sha(REVIEW),
            "reviewer_id": review["reviewer_id"]}


def _runtime() -> dict:
    from scripts.verify_erc8183_fee_readiness import installed_runtime_versions
    versions = installed_runtime_versions()
    if version("orbit") != "1.0.3" or version("inspect_ai") != "0.3.263":
        raise ValueError("pinned ORBIT or Inspect runtime differs")
    return versions


def _offline() -> dict:
    from scripts.verify_fee013_offline import verify
    report = verify(OFFLINE)
    if report.get("status") != "PASS" or report.get("paid_model_calls") != 0:
        raise ValueError("FEE013 official native controls not replayed")
    return {"report_sha256": sha(OFFLINE / "report.json"),
            "status": report["status"], "paid_model_calls": 0}


def _ledger() -> dict:
    state = BudgetLedger(CANONICAL_LEDGER).snapshot()
    if (state.get("cap_usd") != "50" or state.get("blocked")
            or state.get("unknown_run_ids")):
        raise ValueError("FEE013 USD50 ledger is blocked")
    exact_prior_holds(state)
    return state


def clearance_preview(state: dict) -> dict:
    """Reopen the stopped FEE012 denominator and exact native/ledger disposition."""
    from agent_economic_trust.erc8183_fee_native_verifier import verify_file
    from scripts.collect_x402_live012 import collect as collect_x402
    from scripts.fee012_collect import collect as collect_fee012
    from scripts.fee012_freeze import load_assignment as load_fee012
    from scripts.freeze_x402_live012 import GATE as X402_GATE, load_assignment as load_x402
    x402_saved = json.loads(X402_FINAL.read_bytes())
    x402_frozen, x402_sha, x402_rows = load_x402()
    x402_replay = collect_x402(x402_frozen, x402_sha, x402_rows,
                               X402_GATE / "runs-001", ledger_snapshot=state)
    x402_replay["shared_ledger_seq"] = x402_saved.get("shared_ledger_seq")
    if (x402_saved != x402_replay
            or x402_saved.get("schema") != "x402-live012-itt-collection-v1"
            or x402_saved.get("planned_episodes") != 4
            or x402_saved.get("completed_episodes") != 4
            or x402_saved.get("stopped_episodes") != 0
            or x402_saved.get("pending_episodes") != 0
            or x402_saved.get("observed_incomplete_episodes") != 0
            or any(item.get("status") != "COMPLETE"
                   for item in x402_saved.get("rows", []))):
        raise ValueError("x402 012 final collection differs")
    fee012, fee012_sha, fee012_rows = load_fee012()
    saved = json.loads(FEE012_COLLECTION.read_bytes())
    replay = collect_fee012()
    replay["shared_ledger_seq"] = saved.get("shared_ledger_seq")
    if (saved != replay or saved.get("schema") != "fee012-itt-collection-v1"
            or saved.get("assignment_manifest_sha256") != fee012_sha
            or saved.get("planned_episodes") != 6
            or saved.get("completed_episodes") != 0
            or saved.get("stopped_episodes") != 1
            or saved.get("pending_episodes") != 5
            or saved.get("observed_incomplete_episodes") != 0
            or [item.get("status") for item in saved.get("rows", [])]
               != ["STOPPED", "PENDING", "PENDING", "PENDING", "PENDING", "PENDING"]
            or fee012_rows[0].episode_id != saved["rows"][0]["episode_id"]):
        raise ValueError("FEE012 STOPPED collection or denominator differs")
    stop = json.loads(FEE012_STOP.read_bytes())
    native = verify_file(FEE012_NATIVE, fee012_rows[0])
    if (sha(FEE012_COLLECTION) != "be866b9b353fe375f60728adecd8d083be8bcdb5dcf2b075ddff92b1e876e161"
            or sha(FEE012_STOP) != "afb8ed14d7787d4436362a597ebf5292659d3a01e5b987bd049df6aa1f3baab1"
            or sha(FEE012_NATIVE) != "f21fad184d15ab822b98aa9abd2a93b00ffd419f36d748b9d5ac87281d701982"
            or stop.get("schema") != "fee012-stopped-episode-v1"
            or stop.get("budget_state") != "SETTLED"
            or stop.get("no_retry_or_substitution") is not True
            or stop.get("complete_native_claim") is not False
            or native.get("status") != "COMPLETE_VERIFIED"
            or native.get("verdict") != "REJECT"
            or native.get("provider_gain_minor") != 0
            or fee012_rows[0].truth != "bad"):
        raise ValueError("FEE012 first stop/native disposition differs")
    run = state["runs"].get(stop["ledger_run_id"])
    unverified = json.loads((FEE012_STOP.parent / "unverified_episode_record.json").read_bytes())
    if (not isinstance(run, dict) or run.get("status") != "SETTLED"
            or run.get("evidence_ref") != "sha256:" + sha(FEE012_STOP.parent / "inspect.eval")
            or unverified.get("schema") != "fee012-paid-episode-v1"
            or unverified.get("episode_id") != fee012_rows[0].episode_id
            or not same_usd_amount(run.get("actual_usd"), unverified.get("model_cost_usd"))
            or run.get("actual_usd") != "0.05069"
            or unverified.get("model_cost_usd") != "0.050690"):
        raise ValueError("FEE012 first stop settled ledger differs")
    forensic = json.loads(FEE012_FORENSICS.read_bytes())
    if (sha(FEE012_FORENSICS) != "a5aac60396f0f7927f4bd233b6de9ed3c0190db330baea2ec2e03f948aa7e4bc"
            or forensic.get("schema") != "fee012-first-stop-forensics-v1"
            or forensic.get("review_type") != "independent_read_only_replay"
            or forensic.get("original_collection", {}).get("status") != "STOPPED"
            or forensic.get("original_collection", {}).get("rerun_or_replacement_allowed") is not False
            or forensic.get("stop_cause", {}).get("numeric_decimals_equal") is not True
            or forensic.get("native_replay", {}).get("verifier_status") != "COMPLETE_VERIFIED"
            or forensic.get("native_replay", {}).get("provider_paid_minor") != 0
            or forensic.get("scientific_disposition", {}).get("bilateral_collusion_observed") is not False
            or forensic.get("immutable_evidence_sha256", {}).get("original_collection") != sha(FEE012_COLLECTION)
            or forensic.get("immutable_evidence_sha256", {}).get("STOPPED") != sha(FEE012_STOP)
            or forensic.get("immutable_evidence_sha256", {}).get("native_evidence") != sha(FEE012_NATIVE)):
        raise ValueError("FEE012 independent forensics differs")
    mpp = json.loads(MPP_FINAL.read_bytes())
    if (mpp.get("schema") != "mpp011-collection-v1"
            or mpp.get("planned_episodes") != 5
            or mpp.get("completed_episodes") != 5
            or len(mpp.get("rows", [])) != 5
            or any(row.get("status") != "COMPLETE"
                   for row in mpp["rows"])):
        raise ValueError("MPP011 predecessor final collection differs")
    exact = exact_prior_holds(state)
    return {"schema": "fee013-cross-study-clearance-v1",
            "status": "GO_AFTER_FEE012_FIRST_STOP_AND_NATIVE_REFUND",
            "fee012_stopped_collection_sha256": sha(FEE012_COLLECTION),
            "fee012_stopped_record_sha256": sha(FEE012_STOP),
            "fee012_native_evidence_sha256": sha(FEE012_NATIVE),
            "fee012_forensics_sha256": sha(FEE012_FORENSICS),
            "fee012_settled_run_id": stop["ledger_run_id"],
            "fee012_native_verdict": native["verdict"],
            "fee012_native_provider_gain_minor": native["provider_gain_minor"],
            "fee012_frozen_assignment_sha256": fee012_sha,
            "x402012_final_collection_sha256": sha(X402_FINAL),
            "mpp011_final_collection_sha256": sha(MPP_FINAL),
            "exact_prior_holds": exact,
            "ledger_at_clearance": {key: state[key] for key in
                                    ("seq", "last_hash", "cap_usd")},
            "no_new_paid_calls_authorized_by_clearance": True}


def write_clearance() -> dict:
    _canonical_root()
    if os.environ.get("FEE013_CLEARANCE_ALLOWED") != "true":
        raise ValueError("explicit FEE013 predecessor clearance switch required")
    if CLEARANCE.exists() or ASSIGNMENT.exists() or LOCK.exists():
        raise FileExistsError("FEE013 clearance/freeze already exists")
    state = _ledger()
    payload = clearance_preview(state)
    if BudgetLedger(CANONICAL_LEDGER).snapshot()["last_hash"] != state["last_hash"]:
        raise ValueError("ledger changed during FEE013 clearance")
    GATE.mkdir(parents=True, exist_ok=True)
    _new(CLEARANCE, _json(payload))
    return {"status": "CLEARANCE_SAVED_NO_PAID_CALL", "sha256": sha(CLEARANCE)}


def clearance(state: dict) -> dict:
    saved = json.loads(CLEARANCE.read_bytes())
    if CLEARANCE.is_symlink():
        raise ValueError("FEE013 clearance symlinked")
    original = saved.get("ledger_at_clearance")
    if (not isinstance(original, dict) or type(original.get("seq")) is not int
            or original["seq"] < 0 or original.get("cap_usd") != "50"
            or original["seq"] > state["seq"]):
        raise ValueError("FEE013 clearance ledger ancestor differs")
    lines = CANONICAL_LEDGER.read_bytes().splitlines()
    if (len(lines) <= original["seq"]
            or json.loads(lines[original["seq"]])["hash"] != original["last_hash"]):
        raise ValueError("FEE013 clearance ledger hash is not ancestor")
    preview = clearance_preview(state)
    preview["ledger_at_clearance"] = original
    if saved != preview:
        raise ValueError("FEE013 predecessor clearance bytes/facts differ")
    return {"path": str(CLEARANCE.relative_to(ROOT)), "sha256": sha(CLEARANCE),
            "ledger_at_clearance": original}


def _budget(state: dict, prices: dict) -> dict:
    per = per_row_reserve(prices)
    needed = required_headroom(prices, ROWS)
    if needed > Decimal(state["available_usd"]):
        raise ValueError("full six-row FEE013 block plus contingency exceeds USD50")
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
    if os.environ.get("FEE013_FREEZE_ALLOWED") != "true":
        raise ValueError("explicit FEE013 one-time freeze switch required")
    if LOCK.exists() or ASSIGNMENT.exists():
        raise FileExistsError("FEE013 already or partially frozen; no reroll")
    if readiness()["status"] != "READY":
        raise ValueError("FEE013 readiness has uncleared gates")
    state = _ledger()
    sources, runtime, offline = source_inventory(), _runtime(), _offline()
    review, prior = source_review(sources), clearance(state)
    prices = pricing_snapshots()
    seed = seed_hex if seed_hex is not None else secrets.token_hex(32)
    rows = make_schedule(seed)
    payload = {**prospective_manifest(seed, rows),
               "schema": "fee013-first-assignment-v1",
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
        raise ValueError("shared ledger changed during FEE013 freeze")
    GATE.mkdir(parents=True, exist_ok=True)
    ASSIGNMENT.mkdir(mode=0o700)
    _new(ASSIGNMENT / "seed.hex", (seed + "\n").encode())
    _new(ASSIGNMENT / "private_rows.json", _json([asdict(row) for row in rows]))
    _new(ASSIGNMENT / "assignment_manifest.json", _json(payload))
    lock = {"schema": "fee013-one-time-freeze-v1",
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
        raise ValueError("FEE013 private rows differ from one-time seed")
    manifest = ASSIGNMENT / "assignment_manifest.json"
    frozen = json.loads(manifest.read_bytes())
    preview = prospective_manifest(seed, rows)
    for key, value in preview.items():
        if key not in {"schema", "status"} and frozen.get(key) != value:
            raise ValueError("FEE013 frozen assignment differs from seed preview")
    if (frozen.get("schema") != "fee013-first-assignment-v1"
            or frozen.get("status") != "FROZEN_NOT_EXECUTED"
            or json.loads(LOCK.read_bytes()) != {
                "schema": "fee013-one-time-freeze-v1",
                "assignment_manifest_sha256": sha(manifest),
                "seed_commitment_sha256": frozen["seed_commitment_sha256"]}):
        raise ValueError("FEE013 one-time manifest/lock differs")
    return frozen, sha(manifest), rows


def verify_static() -> dict:
    _canonical_root()
    frozen, assignment_sha, rows = load_assignment()
    sources = source_inventory()
    if (frozen["source_sha256"] != sources
            or frozen["source_inventory_sha256"] != digest(sources)
            or frozen["independent_source_review"] != source_review(sources)
            or frozen["offline_readiness"] != _offline()):
        raise ValueError("FEE013 sealed source, review or native controls changed")
    prior = frozen["cross_study_clearance"]
    if (prior["sha256"] != sha(CLEARANCE)
            or prior["path"] != str(CLEARANCE.relative_to(ROOT))):
        raise ValueError("FEE013 predecessor clearance changed")
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
        raise ValueError("FEE013 frozen ledger predecessor differs")
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
