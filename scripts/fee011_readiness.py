#!/usr/bin/env python3
"""Independent read-only FEE011 successor readiness; --save is a later gate."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from agent_economic_trust.erc8183_fee_plan import CANONICAL_LEDGER, read_only_headroom
from agent_economic_trust.erc8183_fee_clearance import sealed_mpp009_disposition
from agent_economic_trust.fee010_closure import (CLOSURE_SHA256,
    OLD_ASSIGNMENT_SHA256, OLD_GATE, file_sha, verify_closure)
from agent_economic_trust.mpp008_pricing import pricing_snapshots
from agent_economic_trust.remote_budget import BudgetLedger
from scripts.verify_erc8183_fee_control import verify_directory
from scripts.verify_erc8183_fee_readiness import (canonical,
    installed_runtime_versions, sealed_sources_committed)


ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "artifacts/prospective/fee011/readiness-001.json"
CONTROL = ROOT / "artifacts/prospective/erc8183-fee-live/zero-model-001"
NEW_SOURCES = (
    "artifacts/gates/ERC8183_FEE010/verification-stop-001.json",
    "docs/PROSPECTIVE_FEE011_SUCCESSOR.md",
    "scripts/fee011_readiness.py", "scripts/fee011_freeze.py",
    "scripts/fee011_runner.py", "scripts/fee011_collect.py",
    "scripts/verify_fee010_closure.py",
    "src/agent_economic_trust/fee010_closure.py",
    "src/agent_economic_trust/fee011_remote.py",
    "tests/test_fee010_closure.py",
    "tests/test_fee011.py",
)


def source_inventory() -> dict[str, str]:
    old = json.loads((OLD_GATE / "assignment-001/assignment_manifest.json").read_text())
    if old.get("source_commit") != "be284036ae17f129b757b29c058adde2dff613aa":
        raise ValueError("FEE010 frozen source commit differs")
    original = old.get("source_sha256")
    if not isinstance(original, dict) or len(original) != 28:
        raise ValueError("FEE010 frozen source inventory differs")
    names = sorted(set(original) | set(NEW_SOURCES))
    inventory = {name: file_sha(ROOT / name) for name in names}
    if {name: inventory[name] for name in original} != original:
        raise ValueError("FEE010 inherited source changed in FEE011 checkout")
    if inventory[NEW_SOURCES[0]] != CLOSURE_SHA256:
        raise ValueError("FEE010 verifier-stop report changed")
    return inventory


def require_canonical_root() -> None:
    if ROOT.resolve() != CANONICAL_LEDGER.parents[2].resolve():
        raise ValueError("FEE011 readiness must run in canonical shared-ledger checkout")


def verify(*, run_tests: bool = True, catalog: dict | None = None) -> dict:
    stop, rows = verify_closure()
    inventory = source_inventory()
    runtime = installed_runtime_versions()
    native = verify_directory(CONTROL)
    if native["status"] != "PASS" or len(native["cases"]) != 9:
        raise ValueError("nine inherited native controls failed replay")
    if run_tests:
        python = Path("/workspace/upstreams/orbit-smoke/.venv/bin/python")
        if not python.is_file():
            raise FileNotFoundError(python)
        process = subprocess.run([str(python), "-m", "unittest", "discover", "-s", "tests",
                                  "-p", "test_fee011.py"], cwd=ROOT,
                                 env={"PYTHONPATH": f"{ROOT / 'src'}:{ROOT}:{ROOT / 'scripts'}",
                                      "PYTHON_DOTENV_DISABLED": "1",
                                      "XDG_DATA_HOME": str(ROOT.parent / ".local/share"),
                                      "XDG_CACHE_HOME": str(ROOT.parent / ".cache"),
                                      "XDG_CONFIG_HOME": str(ROOT.parent / ".config")},
                                 text=True, capture_output=True, timeout=240)
        if process.returncode:
            raise ValueError("FEE011 successor regression suite failed: " +
                             process.stderr[-1500:])
    prices = pricing_snapshots(catalog=catalog)
    ledger = BudgetLedger(CANONICAL_LEDGER).snapshot()
    predecessor = sealed_mpp009_disposition(ledger)
    headroom = read_only_headroom(ledger, prices)
    if not headroom["affordable_at_snapshot"]:
        raise ValueError("FEE011 eight-row full block plus contingency unaffordable")
    return {"schema": "fee011-independent-readiness-v1", "status": "PASS_READ_ONLY",
            "study": "erc8183-native-evaluator-fee-live-011",
            "original_assignment_sha256": OLD_ASSIGNMENT_SHA256,
            "original_preexecution_closure_sha256": CLOSURE_SHA256,
            "original_execution_order": stop["execution_order"],
            "assigned_rows": len(rows), "paid_model_calls": 0,
            "source_sha256": inventory,
            "source_inventory_sha256": sha256(canonical(inventory)).hexdigest(),
            "runtime_versions": runtime,
            "control_summary_sha256": file_sha(CONTROL / "summary.json"),
            "control_verification_sha256": file_sha(CONTROL / "verification.json"),
            "native_cases_verified": 9, "tests_executed": run_tests,
            "test_modules": ["tests.test_fee011"],
            "public_pricing_snapshot": prices, "budget_preview": headroom,
            "mpp009_predecessor_disposition": predecessor,
            "assignment_frozen": False}


def save() -> dict:
    require_canonical_root()
    if READINESS.exists():
        raise FileExistsError("FEE011 readiness is immutable")
    record = verify()
    sealed_sources_committed(record["source_sha256"])
    READINESS.parent.mkdir(parents=True, exist_ok=True)
    with READINESS.open("x") as handle:
        handle.write(json.dumps(record, sort_keys=True, indent=2) + "\n")
    return {"status": "SAVED_READINESS_NOT_FROZEN", "sha256": file_sha(READINESS)}


def reopen_saved() -> dict:
    saved = json.loads(READINESS.read_text())
    current = source_inventory()
    stop, rows = verify_closure()
    if (saved.get("schema") != "fee011-independent-readiness-v1"
            or saved.get("status") != "PASS_READ_ONLY"
            or saved.get("study") != "erc8183-native-evaluator-fee-live-011"
            or saved.get("source_sha256") != current
            or saved.get("source_inventory_sha256") != sha256(canonical(current)).hexdigest()
            or saved.get("original_assignment_sha256") != OLD_ASSIGNMENT_SHA256
            or saved.get("original_preexecution_closure_sha256") != CLOSURE_SHA256
            or saved.get("original_execution_order") != stop["execution_order"]
            or saved.get("assigned_rows") != len(rows)
            or saved.get("runtime_versions") != installed_runtime_versions()
            or saved.get("native_cases_verified") != 9
            or saved.get("tests_executed") is not True
            or saved.get("paid_model_calls") != 0
            or saved.get("assignment_frozen") is not False
            or saved.get("control_summary_sha256") != file_sha(CONTROL / "summary.json")
            or saved.get("control_verification_sha256") != file_sha(CONTROL / "verification.json")):
        raise ValueError("saved FEE011 independent readiness/source differs")
    if verify_directory(CONTROL)["status"] != "PASS":
        raise ValueError("inherited native controls changed after FEE011 readiness")
    if saved.get("mpp009_predecessor_disposition") != sealed_mpp009_disposition(
            BudgetLedger(CANONICAL_LEDGER).snapshot()):
        raise ValueError("sealed MPP009 predecessor changed after FEE011 readiness")
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    print(json.dumps(save() if args.save else verify(), sort_keys=True))


if __name__ == "__main__":
    main()
