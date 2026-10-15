#!/usr/bin/env python3
"""FEE011 successor freezer: carry FEE010's exact seed/rows/order, never reroll."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import tempfile

from agent_economic_trust.erc8183_fee_plan import (CANONICAL_LEDGER, ROWS,
    make_schedule, prospective_manifest, read_only_headroom)
from agent_economic_trust.erc8183_fee_clearance import sealed_mpp009_disposition
from agent_economic_trust.fee010_closure import (CLOSURE_SHA256,
    OLD_ASSIGNMENT_SHA256, OLD_GATE,
    OLD_LOCK_SHA256, OLD_PRIVATE_ROWS_SHA256, OLD_READINESS_SHA256,
    OLD_SEED_SHA256, file_sha, verify_closure)
from agent_economic_trust.mpp008_pricing import pricing_snapshots
from agent_economic_trust.remote_budget import BudgetLedger
from scripts.fee011_readiness import (ROOT, READINESS, reopen_saved,
    source_inventory)
from scripts.verify_erc8183_fee_readiness import (canonical,
    installed_runtime_versions, sealed_sources_committed)


GATE = ROOT / "artifacts/gates/ERC8183_FEE011"
ASSIGNMENT = GATE / "assignment-001"
LOCK = GATE / "first-freeze.lock.json"
SCHEMA = "fee011-successor-assignment-v1"
STATUS = "FROZEN_NOT_EXECUTED"
STUDY = "erc8183-native-evaluator-fee-live-011"


def _head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()


def _canonical_root() -> None:
    if ROOT.resolve() != CANONICAL_LEDGER.parents[2].resolve():
        raise ValueError("FEE011 freeze/verify must run in canonical shared-ledger checkout")


def expected_preview(seed: str, rows: tuple) -> dict:
    return {**prospective_manifest(seed, rows),
            "schema": SCHEMA, "status": STATUS, "study": STUDY}


def prepare() -> dict:
    _canonical_root()
    if os.environ.get("FEE011_FREEZE_ALLOWED") != "true":
        raise ValueError("explicit FEE011 successor freeze flag required")
    if ASSIGNMENT.exists() or LOCK.exists():
        raise FileExistsError("FEE011 first assignment already exists")
    saved = reopen_saved()
    stop, rows = verify_closure()
    inventory = source_inventory()
    sealed_sources_committed(inventory)
    if saved["source_sha256"] != inventory:
        raise ValueError("FEE011 source differs from independent readiness")
    prices = pricing_snapshots()
    state = BudgetLedger(CANONICAL_LEDGER).snapshot()
    if sealed_mpp009_disposition(state) != saved["mpp009_predecessor_disposition"]:
        raise ValueError("MPP009 predecessor differs before FEE011 freeze")
    budget = read_only_headroom(state, prices)
    if not budget["affordable_at_snapshot"]:
        raise ValueError("FEE011 eight rows and contingency are unaffordable")
    seed_file = OLD_GATE / "assignment-001/seed.hex"
    rows_file = OLD_GATE / "assignment-001/private_rows.json"
    seed = seed_file.read_text().strip()
    if (file_sha(seed_file) != OLD_SEED_SHA256
            or file_sha(rows_file) != OLD_PRIVATE_ROWS_SHA256
            or rows != make_schedule(seed)):
        raise ValueError("FEE011 source assignment differs from FEE010")
    manifest = expected_preview(seed, rows)
    manifest.update({
        "original_assignment_sha256": OLD_ASSIGNMENT_SHA256,
        "original_lock_sha256": OLD_LOCK_SHA256,
        "original_readiness_sha256": OLD_READINESS_SHA256,
        "original_preexecution_closure_sha256": CLOSURE_SHA256,
        "original_seed_file_sha256": OLD_SEED_SHA256,
        "original_private_rows_sha256": OLD_PRIVATE_ROWS_SHA256,
        "source_commit": _head(), "source_sha256": inventory,
        "source_inventory_sha256": sha256(canonical(inventory)).hexdigest(),
        "readiness_sha256": file_sha(READINESS),
        "runtime_versions": installed_runtime_versions(),
        "mpp009_predecessor_disposition": saved["mpp009_predecessor_disposition"],
        "zero_model_summary_sha256": saved["control_summary_sha256"],
        "public_pricing_snapshot": prices, "budget_at_freeze": budget,
        "ledger_seq_at_freeze": state["seq"],
        "ledger_hash_at_freeze": state["last_hash"],
        "erc8183_upstream_commit": "142e669c1fd318486a4628395b629f033654dd06",
        "assignment_reused_without_rerandomization": True,
        "prior_fee010_paid_model_calls": stop["old_lock_paid_model_calls"],
    })
    GATE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fee011-assignment-", dir=GATE) as temporary:
        temp = Path(temporary)
        (temp / "seed.hex").write_bytes(seed_file.read_bytes())
        os.chmod(temp / "seed.hex", 0o600)
        (temp / "private_rows.json").write_bytes(rows_file.read_bytes())
        os.chmod(temp / "private_rows.json", 0o600)
        (temp / "assignment_manifest.json").write_bytes(canonical(manifest) + b"\n")
        digest = file_sha(temp / "assignment_manifest.json")
        temp.rename(ASSIGNMENT)
    with LOCK.open("x") as handle:
        handle.write(json.dumps({"schema": "fee011-first-freeze-lock-v1",
                                 "assignment_manifest_sha256": digest,
                                 "original_assignment_sha256": OLD_ASSIGNMENT_SHA256,
                                 "original_preexecution_closure_sha256": CLOSURE_SHA256,
                                 "source_inventory_sha256": manifest["source_inventory_sha256"],
                                 "source_commit": manifest["source_commit"],
                                 "paid_model_calls": 0}, sort_keys=True) + "\n")
    return {"status": STATUS, "assignment_manifest_sha256": digest,
            "assigned_rows": ROWS, "paid_model_calls": 0,
            "original_assignment_sha256": OLD_ASSIGNMENT_SHA256}


def verify() -> tuple[dict, str, tuple]:
    _canonical_root()
    saved = reopen_saved()
    stop, original_rows = verify_closure()
    manifest_path = ASSIGNMENT / "assignment_manifest.json"
    frozen = json.loads(manifest_path.read_text())
    lock = json.loads(LOCK.read_text())
    digest = file_sha(manifest_path)
    seed_path = ASSIGNMENT / "seed.hex"
    rows_path = ASSIGNMENT / "private_rows.json"
    seed = seed_path.read_text().strip()
    rows = make_schedule(seed)
    expected = expected_preview(seed, rows)
    inventory = source_inventory()
    original = OLD_GATE / "assignment-001"
    if (rows != original_rows
            or file_sha(seed_path) != OLD_SEED_SHA256
            or file_sha(rows_path) != OLD_PRIVATE_ROWS_SHA256
            or seed_path.read_bytes() != (original / "seed.hex").read_bytes()
            or rows_path.read_bytes() != (original / "private_rows.json").read_bytes()
            or json.loads(rows_path.read_text()) != [asdict(row) for row in rows]
            or frozen.get("schema") != SCHEMA or frozen.get("status") != STATUS
            or frozen.get("study") != STUDY
            or any(frozen.get(key) != value for key, value in expected.items())
            or frozen.get("original_assignment_sha256") != OLD_ASSIGNMENT_SHA256
            or frozen.get("original_lock_sha256") != OLD_LOCK_SHA256
            or frozen.get("original_readiness_sha256") != OLD_READINESS_SHA256
            or frozen.get("original_preexecution_closure_sha256") != CLOSURE_SHA256
            or frozen.get("original_seed_file_sha256") != OLD_SEED_SHA256
            or frozen.get("original_private_rows_sha256") != OLD_PRIVATE_ROWS_SHA256
            or frozen.get("assignment_reused_without_rerandomization") is not True
            or frozen.get("prior_fee010_paid_model_calls") != 0
            or frozen.get("source_sha256") != inventory
            or frozen.get("source_inventory_sha256") != sha256(canonical(inventory)).hexdigest()
            or frozen.get("readiness_sha256") != file_sha(READINESS)
            or frozen.get("runtime_versions") != saved["runtime_versions"]
            or frozen.get("runtime_versions") != installed_runtime_versions()
            or frozen.get("mpp009_predecessor_disposition") !=
                saved["mpp009_predecessor_disposition"]
            or frozen.get("zero_model_summary_sha256") != saved["control_summary_sha256"]
            or frozen.get("erc8183_upstream_commit") !=
                "142e669c1fd318486a4628395b629f033654dd06"
            or lock.get("schema") != "fee011-first-freeze-lock-v1"
            or lock.get("assignment_manifest_sha256") != digest
            or lock.get("original_assignment_sha256") != OLD_ASSIGNMENT_SHA256
            or lock.get("original_preexecution_closure_sha256") != CLOSURE_SHA256
            or lock.get("source_inventory_sha256") != frozen.get("source_inventory_sha256")
            or lock.get("source_commit") != frozen.get("source_commit")
            or lock.get("paid_model_calls") != 0
            or frozen.get("execution_order") != stop["execution_order"]):
        raise ValueError("FEE011 sealed successor assignment/source differs")
    return frozen, digest, rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    result = prepare() if args.prepare else {"status": "VERIFIED",
                                               "assignment_manifest_sha256": verify()[1]}
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
