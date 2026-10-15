#!/usr/bin/env python3
"""One-time prospective x402 011 assignment and fail-closed readiness.

The default `readiness` command is read only. Freezing requires an explicit
operator switch and reviewed cross-study clearance after MPP010 disposition.
No command in this file calls a paid model or signs a payment.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from agent_economic_trust.mpp005_plan import canonical_project_root  # noqa: E402
from agent_economic_trust.mpp008_pricing import pricing_snapshots  # noqa: E402
from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402
from agent_economic_trust.x402_live011_budget import (  # noqa: E402
    FEE_HOLD_USD, fee011_failed_request_hold)
from agent_economic_trust.x402_live011_plan import (  # noqa: E402
    CANONICAL_LEDGER, ROWS, canonical, digest, make_schedule,
    prospective_manifest, required_headroom, reserve_pair)
from agent_economic_trust.x402_live011_boundary import offline_real_tool_schema_control  # noqa: E402
from scripts.verify_x402_live011_readiness import (  # noqa: E402
    OFFLINE_010, OFFLINE_011, clean_versioned_sources,
    native_source_readiness, source_inventory, verify_010, verify_011,
    version)


GATE = ROOT / "artifacts/gates/X402_LIVE011"
ASSIGNMENT = GATE / "assignment-001"
LOCK = GATE / "first-freeze.lock.json"
CLEARANCE = GATE / "cross-study-clearance-001.json"


def sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("sealed file missing or symlinked")
    return sha256(path.read_bytes()).hexdigest()


def _new(path: Path, payload: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _json(value: object) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"


def _canonical_root() -> None:
    if ROOT.resolve() != canonical_project_root().resolve():
        raise ValueError("x402 011 may freeze only in canonical shared-ledger checkout")


def _ledger() -> dict:
    state = BudgetLedger(CANONICAL_LEDGER).snapshot()
    if (state.get("cap_usd") != "50" or state.get("blocked")
            or state.get("unknown_run_ids")
            or Decimal(state["reserved_usd"]) != Decimal("6.30784") + FEE_HOLD_USD):
        raise ValueError("USD50 ledger has unknown/concurrent reserve or contingent hold differs")
    fee011_failed_request_hold(state)
    return state


def competing_gate_inventory() -> dict[str, str]:
    """Bind every existing immutable predecessor gate byte, not this study."""
    names = []
    for name in ("MPP010", "ERC8183_FEE010", "ERC8183_FEE011"):
        base = ROOT / "artifacts/gates" / name
        if base.is_dir():
            names.extend(p for p in base.rglob("*") if p.is_file())
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(names)}


def cross_study_clearance(state: dict, *, current_head: bool) -> dict:
    """Require a reviewed disposition bound to the exact pre-freeze ledger head."""
    if not CLEARANCE.is_file() or CLEARANCE.is_symlink():
        raise ValueError("MPP010-first cross-study clearance is absent")
    saved = json.loads(CLEARANCE.read_bytes())
    inventory = competing_gate_inventory()
    if (saved.get("schema") != "x402-live011-cross-study-clearance-v1"
            or saved.get("status") != "GO_AFTER_MPP010_FINAL_DISPOSITION"
            or saved.get("mpp010_disposition") not in {
                "CLOSED_AFTER_COMPLETE_COLLECTION", "CLOSED_AFTER_STOPPED_COLLECTION"}
            or saved.get("fee011_disposition") not in {
                "NOT_FROZEN", "CLOSED_AFTER_ALL_ROWS_COLLECTED",
                "CLOSED_AFTER_STOPPED_COLLECTION"}
            or saved.get("competing_gate_inventory_sha256") != digest(inventory)
            or saved.get("ledger_at_clearance", {}).get("cap_usd") != "50"):
        raise ValueError("cross-study clearance content or predecessor inventory differs")
    head = saved.get("ledger_at_clearance", {})
    if (not isinstance(head.get("seq"), int)
            or not isinstance(head.get("last_hash"), str)
            or (current_head and head != {"seq": state["seq"],
                                        "last_hash": state["last_hash"],
                                        "cap_usd": "50"})):
        raise ValueError("cross-study clearance ledger head differs")
    lines = CANONICAL_LEDGER.read_bytes().splitlines()
    if (head["seq"] > state["seq"] or len(lines) <= head["seq"]
            or json.loads(lines[head["seq"]])["hash"] != head["last_hash"]):
        raise ValueError("cross-study clearance head is not a ledger ancestor")
    # A declared predecessor stop/finish must be backed by its entire frozen
    # ten-row denominator, not only by the existence of a first-freeze lock.
    mpp_lock_path = ROOT / "artifacts/gates/MPP010/one-time-freeze.lock.json"
    mpp = ROOT / "artifacts/gates/MPP010/assignment-001/assignment_manifest.json"
    if (not mpp.is_file() or not mpp_lock_path.is_file()
            or str(mpp.relative_to(ROOT)) not in inventory
            or str(mpp_lock_path.relative_to(ROOT)) not in inventory):
        raise ValueError("MPP010 final assignment evidence missing")
    mpp_lock = json.loads(mpp_lock_path.read_bytes())
    if (mpp_lock.get("schema") != "mpp010-one-time-freeze-v1"
            or mpp_lock.get("assignment_manifest_sha256") != sha(mpp)):
        raise ValueError("MPP010 final assignment lock differs")
    relative = saved.get("mpp010_final_collection_path")
    if not isinstance(relative, str):
        raise ValueError("MPP010 final collection path missing")
    collection = ROOT / relative
    if (not collection.resolve().is_relative_to(
            (ROOT / "artifacts/gates/MPP010").resolve())
            or str(collection.relative_to(ROOT)) not in inventory
            or saved.get("mpp010_final_collection_sha256") != sha(collection)):
        raise ValueError("MPP010 final collection path/hash differs")
    manifest = json.loads(mpp.read_bytes())
    report = json.loads(collection.read_bytes())
    assigned = manifest.get("execution_order", [])
    reported = report.get("rows", [])
    if (report.get("schema") != "mpp010-collection-v1"
            or report.get("assignment_manifest_sha256") != sha(mpp)
            or report.get("planned_episodes") != 10
            or len(reported) != 10 or len(assigned) != 10
            or [item.get("episode_id") for item in reported] != assigned
            or any(item.get("status") not in {"COMPLETE", "STOPPED", "PENDING"}
                   for item in reported)):
        raise ValueError("MPP010 final collection denominator or verification differs")
    statuses = [item["status"] for item in reported]
    if saved["mpp010_disposition"] == "CLOSED_AFTER_COMPLETE_COLLECTION":
        if statuses != ["COMPLETE"] * 10:
            raise ValueError("MPP010 all-complete clearance differs")
    else:
        stop = next((i for i, status in enumerate(statuses)
                     if status == "STOPPED"), None)
        if (stop is None or statuses[:stop] != ["COMPLETE"] * stop
                or statuses[stop:] != ["STOPPED"] + ["PENDING"] * (9 - stop)):
            raise ValueError("MPP010 stopped-prefix clearance differs")
    fee_gate = ROOT / "artifacts/gates/ERC8183_FEE011"
    fee_manifest = fee_gate / "assignment-001/assignment_manifest.json"
    fee_lock = fee_gate / "first-freeze.lock.json"
    fee_collection_sha = None
    if saved["fee011_disposition"] == "NOT_FROZEN":
        if fee_lock.exists() or fee_manifest.exists() or (fee_gate / "assignment-001").exists():
            raise ValueError("FEE011 was frozen after NOT_FROZEN clearance declaration")
    else:
        if (not fee_lock.is_file() or not fee_manifest.is_file()
                or str(fee_lock.relative_to(ROOT)) not in inventory
                or str(fee_manifest.relative_to(ROOT)) not in inventory):
            raise ValueError("FEE011 closed disposition lacks frozen assignment")
        fee_relative = saved.get("fee011_final_collection_path")
        if not isinstance(fee_relative, str):
            raise ValueError("FEE011 final collection path missing")
        fee_collection = ROOT / fee_relative
        if (not fee_collection.resolve().is_relative_to(fee_gate.resolve())
                or str(fee_collection.relative_to(ROOT)) not in inventory
                or saved.get("fee011_final_collection_sha256") != sha(fee_collection)):
            raise ValueError("FEE011 final collection path/hash differs")
        fee_frozen = json.loads(fee_manifest.read_bytes())
        fee_saved_lock = json.loads(fee_lock.read_bytes())
        if (fee_saved_lock.get("schema") != "fee011-first-freeze-lock-v1"
                or fee_saved_lock.get("assignment_manifest_sha256") != sha(fee_manifest)):
            raise ValueError("FEE011 final assignment lock differs")
        fee_report = json.loads(fee_collection.read_bytes())
        fee_assigned = fee_frozen.get("execution_order", [])
        fee_reported = fee_report.get("rows", [])
        if (fee_report.get("schema") != "fee011-itt-collection-v1"
                or fee_report.get("assignment_manifest_sha256") != sha(fee_manifest)
                or fee_report.get("planned_episodes") != 8
                or len(fee_assigned) != 8 or len(fee_reported) != 8
                or [item.get("episode_id") for item in fee_reported] != fee_assigned
                or any(item.get("status") not in {
                    "COMPLETE", "OBSERVED_INCOMPLETE", "STOPPED", "PENDING"}
                       for item in fee_reported)):
            raise ValueError("FEE011 final collection denominator differs")
        fee_statuses = [item["status"] for item in fee_reported]
        if saved["fee011_disposition"] == "CLOSED_AFTER_ALL_ROWS_COLLECTED":
            if any(item not in {"COMPLETE", "OBSERVED_INCOMPLETE"}
                   for item in fee_statuses):
                raise ValueError("FEE011 all-row closure differs")
        else:
            fee_stop = next((i for i, status in enumerate(fee_statuses)
                             if status == "STOPPED"), None)
            if (fee_stop is None
                    or any(item not in {"COMPLETE", "OBSERVED_INCOMPLETE"}
                           for item in fee_statuses[:fee_stop])
                    or fee_statuses[fee_stop:] !=
                    ["STOPPED"] + ["PENDING"] * (7 - fee_stop)):
                raise ValueError("FEE011 stopped-prefix closure differs")
        fee_collection_sha = sha(fee_collection)
    return {"sha256": sha(CLEARANCE), "inventory_sha256": digest(inventory),
            "ledger_at_clearance": head,
            "mpp010_disposition": saved["mpp010_disposition"],
            "mpp010_final_collection_sha256": sha(collection),
            "fee011_disposition": saved["fee011_disposition"],
            "fee011_final_collection_sha256": fee_collection_sha}


def _runtime() -> dict:
    native = native_source_readiness()
    result = {"orbit": version("orbit"), "inspect_ai": version("inspect_ai"),
              "native_source_readiness": native}
    if (result["orbit"] != "1.0.3" or result["inspect_ai"] != "0.3.263"
            or not native["all_native_sources_ready"]):
        raise ValueError("pinned ORBIT/Inspect/native runtime differs")
    return result


def _offline() -> dict:
    older = verify_010(OFFLINE_010)
    current = verify_011(OFFLINE_011)
    if (older["status"] != "PASS" or older["native_cells_reverified"] != 4
            or current["status"] != "PASS"
            or current["scripted_cases_reverified"] != 3):
        raise ValueError("native x402 control matrix differs")
    tools = offline_real_tool_schema_control()
    if tools["status"] != "PASS" or tools["paid_model_calls"] != 0:
        raise ValueError("actual ORBIT strict tool schemas differ")
    return {"archived_010": older, "scripted_011": current,
            "strict_orbit_tools": tools}


def _budget(state: dict, rows, prices: dict) -> dict:
    per_row = {row.episode_id: str(reserve_pair(prices, row)) for row in rows}
    needed = required_headroom(prices, rows)
    if needed > Decimal(state["available_usd"]):
        raise ValueError("full four-row x402 block exceeds shared USD50 headroom")
    return {"per_row_worst_case_usd": per_row,
            "full_block_plus_contingency_residual_usd": str(needed),
            "ledger_available_usd": state["available_usd"]}


def freeze_payload(seed_hex: str, rows, *, sources: dict, runtime: dict,
                   offline: dict, prices: dict, state: dict, clearance: dict) -> dict:
    """Pure serializer; the fixed preview fields must match before overrides."""
    preview = prospective_manifest(seed_hex, rows)
    return {**preview,
            "schema": "x402-live011-first-assignment-v1",
            "status": "FROZEN_NOT_EXECUTED",
            "source_sha256": sources,
            "source_inventory_sha256": digest(sources),
            "runtime_pins": runtime, "offline_readiness": offline,
            "public_pricing_snapshot": prices,
            "budget_at_freeze": {k: state[k] for k in
                ("seq", "last_hash", "cap_usd", "available_usd")},
            "prior_ledger_run_ids": sorted(state["runs"]),
            "prior_ledger_runs_sha256": digest(state["runs"]),
            "cross_study_clearance": clearance,
            "budget_gate": _budget(state, rows, prices),
            "model_tier": "REAL_LLM_REMOTE_APPROVED",
            "payment_tier": "NATIVE_LOCAL_PROTOCOL",
            "no_reroll_or_model_substitution": True,
            "x402_payment_claim": "intake only; no truth/atomicity/PSP capture"}


def validate_frozen_manifest(seed_hex: str, frozen: dict, rows) -> None:
    """Avoid the FEE010 preview-versus-frozen schema/status trap."""
    expected = prospective_manifest(seed_hex, rows)
    for key, value in expected.items():
        if key in {"schema", "status"}:
            continue
        if frozen.get(key) != value:
            raise ValueError(f"x402 011 frozen {key} differs from preview")
    if (frozen.get("schema") != "x402-live011-first-assignment-v1"
            or frozen.get("status") != "FROZEN_NOT_EXECUTED"):
        raise ValueError("x402 011 frozen schema/status differs")


def freeze(*, seed_hex: str | None = None) -> dict:
    _canonical_root()
    if os.environ.get("X402_LIVE011_FREEZE_ALLOWED", "false").lower() != "true":
        raise ValueError("explicit x402 011 one-time freeze switch absent")
    if LOCK.exists() or ASSIGNMENT.exists():
        raise FileExistsError("x402 011 already or partially frozen; no reroll")
    if not clean_versioned_sources():
        raise ValueError("tracked x402 011 source differs before freeze")
    sources, runtime, offline = source_inventory(), _runtime(), _offline()
    state = _ledger()
    clearance = cross_study_clearance(state, current_head=True)
    prices = pricing_snapshots()
    seed = seed_hex if seed_hex is not None else secrets.token_hex(32)
    rows = make_schedule(seed)
    payload = freeze_payload(seed, rows, sources=sources, runtime=runtime,
                             offline=offline, prices=prices,
                             state=state, clearance=clearance)
    if BudgetLedger(CANONICAL_LEDGER).snapshot()["last_hash"] != state["last_hash"]:
        raise ValueError("shared ledger changed during one-time freeze preflight")
    GATE.mkdir(parents=True, exist_ok=True)
    ASSIGNMENT.mkdir(mode=0o700)
    _new(ASSIGNMENT / "seed.hex", (seed + "\n").encode())
    _new(ASSIGNMENT / "private_rows.json", _json([asdict(row) for row in rows]))
    _new(ASSIGNMENT / "assignment_manifest.json", _json(payload))
    lock = {"schema": "x402-live011-one-time-freeze-v1",
            "assignment_manifest_sha256": sha(ASSIGNMENT / "assignment_manifest.json"),
            "seed_commitment_sha256": payload["seed_commitment_sha256"]}
    _new(LOCK, _json(lock))
    return {"status": "FROZEN_NOT_EXECUTED", "rows": ROWS,
            "assignment_manifest_sha256": lock["assignment_manifest_sha256"],
            "ledger_seq": state["seq"], "model_calls": 0}


def load_assignment() -> tuple[dict, str, tuple]:
    seed = (ASSIGNMENT / "seed.hex").read_text().strip()
    rows = make_schedule(seed)
    private = json.loads((ASSIGNMENT / "private_rows.json").read_bytes())
    manifest_path = ASSIGNMENT / "assignment_manifest.json"
    frozen = json.loads(manifest_path.read_bytes())
    if private != [asdict(row) for row in rows]:
        raise ValueError("x402 011 private rows differ from seed")
    validate_frozen_manifest(seed, frozen, rows)
    expected_lock = {"schema": "x402-live011-one-time-freeze-v1",
                     "assignment_manifest_sha256": sha(manifest_path),
                     "seed_commitment_sha256": frozen["seed_commitment_sha256"]}
    if json.loads(LOCK.read_bytes()) != expected_lock:
        raise ValueError("x402 011 first-freeze lock differs")
    return frozen, sha(manifest_path), rows


def verify_static() -> dict:
    _canonical_root()
    frozen, assignment_sha, rows = load_assignment()
    if (frozen.get("source_sha256") != source_inventory()
            or frozen.get("source_inventory_sha256") != digest(source_inventory())):
        raise ValueError("x402 011 frozen executable source changed")
    clearance = frozen["cross_study_clearance"]
    if (clearance.get("sha256") != sha(CLEARANCE)
            or clearance.get("inventory_sha256") != digest(competing_gate_inventory())):
        raise ValueError("x402 011 predecessor clearance changed")
    if frozen["offline_readiness"] != _offline():
        raise ValueError("x402 011 archived native controls changed")
    return {"status": "SEALED_STATIC", "assignment_manifest_sha256": assignment_sha,
            "rows": len(rows), "model_calls": 0}


def verify() -> dict:
    static = verify_static()
    frozen, _, _ = load_assignment()
    state = BudgetLedger(CANONICAL_LEDGER).snapshot()
    prior = frozen["budget_at_freeze"]
    lines = CANONICAL_LEDGER.read_bytes().splitlines()
    if (state["cap_usd"] != "50" or state["blocked"] or state["unknown_run_ids"]
            or state["seq"] < prior["seq"] or len(lines) <= prior["seq"]
            or json.loads(lines[prior["seq"]])["hash"] != prior["last_hash"]):
        raise ValueError("x402 011 frozen USD50 ledger head not a safe ancestor")
    return {**static, "ledger_seq": state["seq"]}


def readiness() -> dict:
    checks = {}
    for name, fn in (("canonical_checkout", _canonical_root),
                     ("one_time_freeze_available", lambda: (
                         (_ for _ in ()).throw(FileExistsError("already frozen"))
                         if LOCK.exists() or ASSIGNMENT.exists() else None)),
                     ("source_clean", lambda: (
                         None if clean_versioned_sources() else
                         (_ for _ in ()).throw(ValueError("tracked source dirty")))),
                     ("source_inventory", source_inventory),
                     ("pinned_runtime", _runtime),
                     ("native_controls", _offline),
                     ("shared_ledger", _ledger),
                     ("current_catalog", pricing_snapshots)):
        try:
            value = fn()
            checks[name] = "PASS"
            if name == "shared_ledger":
                state = value
            elif name == "current_catalog":
                prices = value
        except Exception as exc:
            checks[name] = type(exc).__name__ + ": " + str(exc)
    if checks.get("shared_ledger") == "PASS":
        try:
            cross_study_clearance(state, current_head=True)
            checks["cross_study_clearance"] = "PASS"
        except Exception as exc:
            checks["cross_study_clearance"] = type(exc).__name__ + ": " + str(exc)
    if checks.get("shared_ledger") == "PASS" and checks.get("current_catalog") == "PASS":
        try:
            budget = _budget(state, make_schedule("ab" * 32), prices)
            checks["full_block_budget"] = "PASS"
        except Exception as exc:
            checks["full_block_budget"] = type(exc).__name__ + ": " + str(exc)
            budget = None
    else:
        budget = None
    ready = checks and all(value == "PASS" for value in checks.values())
    return {"status": "READY" if ready else "BLOCKED", "would_freeze": bool(ready),
            "would_call_paid_model": False, "checks": checks,
            "budget": budget, "model_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("readiness", "freeze", "verify", "verify-static"),
                        nargs="?", default="readiness")
    args = parser.parse_args()
    result = {"readiness": readiness, "freeze": freeze,
              "verify": verify, "verify-static": verify_static}[args.command]()
    print(json.dumps(result, sort_keys=True))
