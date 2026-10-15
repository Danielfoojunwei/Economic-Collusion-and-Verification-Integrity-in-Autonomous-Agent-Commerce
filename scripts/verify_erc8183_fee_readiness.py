#!/usr/bin/env python3
"""Independent, read-only ERC-8183 fee study source/native/budget readiness.

The default command writes nothing. A later reviewed --save operation may
commit one immutable readiness record for the separate assignment freezer.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import subprocess

from agent_economic_trust.erc8183_fee_plan import (CANONICAL_LEDGER,
    read_only_headroom)
from agent_economic_trust.erc8183_fee_clearance import sealed_mpp009_disposition
from agent_economic_trust.mpp008_pricing import pricing_snapshots
from agent_economic_trust.remote_budget import BudgetLedger
from scripts.verify_erc8183_fee_control import verify_directory


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_RUNTIME = {"orbit": "1.0.3", "inspect-ai": "0.3.263"}
CONTROL = ROOT / "artifacts/prospective/erc8183-fee-live/zero-model-001"
READINESS = ROOT / "artifacts/prospective/erc8183-fee-live/readiness-001.json"
BASE_SOURCES = (
    "scripts/run_erc8183_local.py", "scripts/run_erc8183_fee_control.py",
    "scripts/verify_erc8183_fee_control.py",
    "src/agent_economic_trust/ap2_live_fixture.py",
    "src/agent_economic_trust/open004_task.py",
    "src/agent_economic_trust/core.py",
    "src/agent_economic_trust/remote_budget.py",
    "src/agent_economic_trust/remote_pricing.py",
    "src/agent_economic_trust/mpp005_plan.py",
    "src/agent_economic_trust/mpp005_boundary.py",
    "src/agent_economic_trust/mpp008_plan.py",
    "src/agent_economic_trust/mpp008_budget.py",
    "src/agent_economic_trust/mpp008_pricing.py",
    "docs/PROSPECTIVE_ERC8183_EVALUATOR_FEE_LIVE_010.md",
)
TEST_MODULES = (
    "tests.test_erc8183_fee_control", "tests.test_erc8183_fee_plan",
    "tests.test_erc8183_fee_task_scaffold", "tests.test_erc8183_fee_live",
)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def file_sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"source/evidence must be a regular file: {path}")
    return sha256(path.read_bytes()).hexdigest()


def source_inventory() -> dict[str, str]:
    names = set(BASE_SOURCES)
    names.update(str(p.relative_to(ROOT)) for p in
                 (ROOT / "scripts").glob("*erc8183_fee*.py"))
    names.update(str(p.relative_to(ROOT)) for p in
                 (ROOT / "src/agent_economic_trust").glob("erc8183_fee_*.py"))
    names.update(str(p.relative_to(ROOT)) for p in
                 (ROOT / "tests").glob("test_erc8183_fee*.py"))
    required = {"scripts/freeze_erc8183_fee.py", "scripts/run_erc8183_fee_live.py",
                "scripts/collect_erc8183_fee.py",
                "src/agent_economic_trust/erc8183_fee_remote.py",
                "src/agent_economic_trust/erc8183_fee_native.py",
                "src/agent_economic_trust/erc8183_fee_native_verifier.py",
                "tests/test_erc8183_fee_live.py"}
    if not required.issubset(names):
        raise ValueError("versioned live source set is incomplete")
    return {name: file_sha(ROOT / name) for name in sorted(names)}


def require_canonical_root() -> None:
    if ROOT.resolve() != CANONICAL_LEDGER.parents[2].resolve():
        raise ValueError("fee study readiness/freeze must run in canonical shared-ledger checkout")


def sealed_sources_committed(inventory: dict[str, str]) -> None:
    """Check only sealed sources; later ledger/artifact writes may dirty this checkout."""
    paths = sorted(inventory)
    if not paths or subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", *paths], cwd=ROOT,
            capture_output=True, text=True).returncode:
        raise ValueError("every sealed fee study source must be committed")
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *paths],
                      cwd=ROOT, capture_output=True, text=True).returncode:
        raise ValueError("sealed fee study source differs from committed HEAD")


def installed_runtime_versions() -> dict[str, str]:
    observed = {name: version(name) for name in EXPECTED_RUNTIME}
    if observed != EXPECTED_RUNTIME:
        raise ValueError("fee study ORBIT/Inspect runtime versions differ")
    return observed


def verify(*, run_tests: bool = True, catalog: dict | None = None) -> dict:
    inventory = source_inventory()
    runtime = installed_runtime_versions()
    native = verify_directory(CONTROL)
    if native["status"] != "PASS" or len(native["cases"]) != 9:
        raise ValueError("saved nine-case native control failed")
    if run_tests:
        python = Path("/workspace/upstreams/orbit-smoke/.venv/bin/python")
        if not python.is_file():
            raise FileNotFoundError(python)
        process = subprocess.run([str(python), "-m", "unittest", "discover", "-s", "tests",
                                  "-p", "test_erc8183_fee*.py"],
                                 cwd=ROOT, env={"PYTHONPATH": f"{ROOT / 'src'}:{ROOT}:" + str(ROOT / "scripts"),
                                                "PYTHON_DOTENV_DISABLED": "1"},
                                 text=True, capture_output=True, timeout=240)
        if process.returncode:
            raise ValueError("fee live independent test suite failed: " +
                             process.stderr[-1000:])
        tested = True
    else:
        tested = False
    snapshots = pricing_snapshots(catalog=catalog)
    ledger = BudgetLedger(CANONICAL_LEDGER).snapshot()
    predecessor = sealed_mpp009_disposition(ledger)
    headroom = read_only_headroom(ledger, snapshots)
    if not headroom["affordable_at_snapshot"]:
        raise ValueError("eight-row full block plus contingency exceeds current USD50 headroom")
    return {"schema": "erc8183-fee-independent-readiness-v1",
            "status": "PASS_READ_ONLY", "study": "erc8183-native-evaluator-fee-live-010",
            "source_sha256": inventory,
            "source_inventory_sha256": sha256(canonical(inventory)).hexdigest(),
            "control_summary_sha256": file_sha(CONTROL / "summary.json"),
            "control_verification_sha256": file_sha(CONTROL / "verification.json"),
            "native_cases_verified": 9, "tests_executed": tested,
            "test_modules": list(TEST_MODULES), "role_models": list(snapshots),
            "runtime_versions": runtime,
            "public_pricing_snapshot": snapshots, "budget_preview": headroom,
            "mpp009_predecessor_disposition": predecessor,
            "paid_model_calls": 0, "assignment_frozen": False}


def save() -> dict:
    require_canonical_root()
    if READINESS.exists():
        raise FileExistsError("fee study readiness is immutable")
    record = verify()
    sealed_sources_committed(record["source_sha256"])
    READINESS.parent.mkdir(parents=True, exist_ok=True)
    with READINESS.open("x") as handle:
        handle.write(json.dumps(record, sort_keys=True, indent=2) + "\n")
    return {"status": "SAVED_READINESS_NOT_FROZEN", "sha256": file_sha(READINESS)}


def reopen_saved() -> dict:
    saved = json.loads(READINESS.read_text())
    current = source_inventory()
    if (saved.get("schema") != "erc8183-fee-independent-readiness-v1"
            or saved.get("status") != "PASS_READ_ONLY"
            or saved.get("source_sha256") != current
            or saved.get("source_inventory_sha256") != sha256(canonical(current)).hexdigest()
            or saved.get("runtime_versions") != installed_runtime_versions()
            or saved.get("native_cases_verified") != 9
            or saved.get("tests_executed") is not True
            or saved.get("paid_model_calls") != 0
            or saved.get("assignment_frozen") is not False
            or saved.get("control_summary_sha256") != file_sha(CONTROL / "summary.json")
            or saved.get("control_verification_sha256") != file_sha(CONTROL / "verification.json")):
        raise ValueError("saved independent readiness or source changed")
    if verify_directory(CONTROL)["status"] != "PASS":
        raise ValueError("native controls differ from saved readiness")
    if saved.get("mpp009_predecessor_disposition") != sealed_mpp009_disposition(
            BudgetLedger(CANONICAL_LEDGER).snapshot()):
        raise ValueError("sealed MPP009 predecessor changed after readiness")
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    print(json.dumps(save() if args.save else verify(), sort_keys=True))


if __name__ == "__main__":
    main()
