#!/usr/bin/env python3
"""First assignment freezer for the prospective ERC-8183 fee study.

Default status is read-only. --prepare requires independently saved readiness,
full shared USD50 headroom, committed source, and an explicit freeze flag.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile

from agent_economic_trust.erc8183_fee_plan import (CANONICAL_LEDGER, ROWS,
    make_schedule, prospective_manifest, read_only_headroom)
from agent_economic_trust.erc8183_fee_clearance import sealed_mpp009_disposition
from agent_economic_trust.mpp008_pricing import pricing_snapshots
from agent_economic_trust.remote_budget import BudgetLedger
from scripts.verify_erc8183_fee_readiness import (ROOT, READINESS, canonical,
    file_sha, installed_runtime_versions, reopen_saved, sealed_sources_committed,
    source_inventory)


GATE = ROOT / "artifacts/gates/ERC8183_FEE010"
ASSIGNMENT = GATE / "assignment-001"
LOCK = GATE / "first-freeze.lock.json"


def _head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()


def _canonical_root() -> None:
    if ROOT.resolve() != CANONICAL_LEDGER.parents[2].resolve():
        raise ValueError("fee study freeze/verify must run in canonical shared-ledger checkout")


def prepare() -> dict:
    _canonical_root()
    if os.environ.get("ERC8183_FEE010_FREEZE_ALLOWED") != "true":
        raise ValueError("explicit versioned fee-study freeze flag required")
    if ASSIGNMENT.exists() or LOCK.exists():
        raise FileExistsError("fee study first assignment already exists")
    saved = reopen_saved()
    inventory = source_inventory()
    sealed_sources_committed(inventory)
    if saved["source_sha256"] != inventory:
        raise ValueError("source differs from independent readiness")
    prices = pricing_snapshots()
    state = BudgetLedger(CANONICAL_LEDGER).snapshot()
    if sealed_mpp009_disposition(state) != saved["mpp009_predecessor_disposition"]:
        raise ValueError("MPP009 stopped predecessor clearance differs")
    budget = read_only_headroom(state, prices)
    if not budget["affordable_at_snapshot"]:
        raise ValueError("all eight fee rows and contingency are unaffordable")
    seed = secrets.token_hex(32)
    rows = make_schedule(seed)
    manifest = prospective_manifest(seed, rows)
    manifest.update({
        "schema": "erc8183-fee-first-assignment-v1",
        "status": "FROZEN_NOT_EXECUTED", "source_commit": _head(),
        "source_sha256": inventory,
        "runtime_versions": installed_runtime_versions(),
        "source_inventory_sha256": sha256(canonical(inventory)).hexdigest(),
        "readiness_sha256": file_sha(READINESS),
        "mpp009_predecessor_disposition": saved["mpp009_predecessor_disposition"],
        "zero_model_summary_sha256": saved["control_summary_sha256"],
        "public_pricing_snapshot": prices, "budget_at_freeze": budget,
        "ledger_seq_at_freeze": state["seq"],
        "ledger_hash_at_freeze": state["last_hash"],
        "erc8183_upstream_commit": "142e669c1fd318486a4628395b629f033654dd06",
    })
    GATE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fee010-assignment-", dir=GATE) as temporary:
        temp = Path(temporary)
        (temp / "seed.hex").write_text(seed + "\n")
        os.chmod(temp / "seed.hex", 0o600)
        (temp / "private_rows.json").write_text(json.dumps(
            [asdict(row) for row in rows], sort_keys=True, indent=2) + "\n")
        os.chmod(temp / "private_rows.json", 0o600)
        (temp / "assignment_manifest.json").write_bytes(canonical(manifest) + b"\n")
        manifest_sha = file_sha(temp / "assignment_manifest.json")
        temp.rename(ASSIGNMENT)
    with LOCK.open("x") as handle:
        handle.write(json.dumps({"schema": "erc8183-fee-first-freeze-lock-v1",
                                 "assignment_manifest_sha256": manifest_sha,
                                 "source_inventory_sha256": manifest["source_inventory_sha256"],
                                 "source_commit": manifest["source_commit"],
                                 "paid_model_calls": 0}, sort_keys=True) + "\n")
    return {"status": "FROZEN_NOT_EXECUTED", "assignment_manifest_sha256": manifest_sha,
            "assigned_rows": ROWS, "paid_model_calls": 0}


def verify() -> tuple[dict, str, tuple]:
    _canonical_root()
    saved = reopen_saved()
    manifest_path = ASSIGNMENT / "assignment_manifest.json"
    frozen = json.loads(manifest_path.read_text())
    lock = json.loads(LOCK.read_text())
    digest = file_sha(manifest_path)
    seed = (ASSIGNMENT / "seed.hex").read_text().strip()
    rows = make_schedule(seed)
    preview = prospective_manifest(seed, rows)
    inventory = source_inventory()
    if (frozen.get("schema") != "erc8183-fee-first-assignment-v1"
            or frozen.get("status") != "FROZEN_NOT_EXECUTED"
            or lock.get("schema") != "erc8183-fee-first-freeze-lock-v1"
            or lock.get("assignment_manifest_sha256") != digest
            or lock.get("source_inventory_sha256") != frozen.get("source_inventory_sha256")
            or lock.get("source_commit") != frozen.get("source_commit")
            or lock.get("paid_model_calls") != 0
            or frozen.get("source_sha256") != inventory
            or frozen.get("runtime_versions") != saved["runtime_versions"]
            or frozen.get("runtime_versions") != installed_runtime_versions()
            or frozen.get("source_inventory_sha256") != sha256(canonical(inventory)).hexdigest()
            or frozen.get("readiness_sha256") != file_sha(READINESS)
            or frozen.get("zero_model_summary_sha256") != saved["control_summary_sha256"]
            or frozen.get("mpp009_predecessor_disposition") !=
                saved["mpp009_predecessor_disposition"]
            or frozen.get("erc8183_upstream_commit") !=
                "142e669c1fd318486a4628395b629f033654dd06"
            or json.loads((ASSIGNMENT / "private_rows.json").read_text())
                != [asdict(row) for row in rows]
            or any(frozen.get(key) != preview[key] for key in preview)):
        raise ValueError("frozen fee study assignment/source differs")
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
