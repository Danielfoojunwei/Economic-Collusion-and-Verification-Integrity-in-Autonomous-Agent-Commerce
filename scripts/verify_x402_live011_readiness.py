#!/usr/bin/env python3
"""Read-only prospective x402 011 readiness and lifetime-USD50 headroom gate.

This script cannot freeze an assignment, reserve budget, or call a paid model.
It reports concrete blockers until versioned freeze, boundary and collector
review are complete on the canonical checkout.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from agent_economic_trust.mpp005_plan import canonical_project_root  # noqa: E402
from agent_economic_trust.mpp008_pricing import pricing_snapshots  # noqa: E402
from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402
from agent_economic_trust.x402_live011_budget import fee011_failed_request_hold  # noqa: E402
from agent_economic_trust.x402_live011_plan import (  # noqa: E402
    CANONICAL_LEDGER, SOL, SONNET, make_schedule, required_headroom,
    reserve_pair)
from agent_economic_trust.x402_live011_boundary import offline_real_tool_schema_control  # noqa: E402
from scripts.verify_x402_retainer_offline import verify as verify_010  # noqa: E402
from scripts.verify_x402_live011_offline import verify as verify_011  # noqa: E402
from scripts.preview_x402_retainer import source_readiness as native_source_readiness  # noqa: E402


SOURCE_FILES = (
    "AGENTS.md", "UPSTREAM_PINNED.json",
    "docs/PROSPECTIVE_X402_AUDIT_RETAINER_010.md",
    "docs/PROSPECTIVE_X402_LIVE011.md",
    "contracts/x402/TestEIP3009Token.sol",
    "scripts/run_erc8183_local.py", "scripts/run_x402_audit_retainer.mjs",
    "scripts/run_x402_live011_offline.py",
    "scripts/freeze_x402_live011.py",
    "scripts/run_x402_live011.py",
    "scripts/collect_x402_live011.py",
    "scripts/verify_x402_live011_readiness.py",
    "scripts/verify_x402_live011_offline.py",
    "scripts/verify_x402_retainer_offline.py",
    "src/agent_economic_trust/ap2_live_fixture.py",
    "src/agent_economic_trust/core.py",
    "src/agent_economic_trust/mpp005_boundary.py",
    "src/agent_economic_trust/mpp005_plan.py",
    "src/agent_economic_trust/mpp008_budget.py",
    "src/agent_economic_trust/mpp008_pricing.py",
    "src/agent_economic_trust/remote_budget.py",
    "src/agent_economic_trust/reporting.py",
    "src/agent_economic_trust/x402_audit_retainer.py",
    "src/agent_economic_trust/x402_audit_retainer_verifier.py",
    "src/agent_economic_trust/x402_retainer_job.py",
    "src/agent_economic_trust/x402_retainer_job_verifier.py",
    "src/agent_economic_trust/x402_live011_plan.py",
    "src/agent_economic_trust/x402_live011_task.py",
    "src/agent_economic_trust/x402_live011_boundary.py",
    "src/agent_economic_trust/x402_live011_native.py",
    "src/agent_economic_trust/x402_live011_native_verifier.py",
    "tests/test_x402_live011.py",
)
OFFLINE_010 = ROOT / "artifacts/gates/X402_RETAINER_010/offline-native-001"
OFFLINE_011 = ROOT / "artifacts/prospective/X402_LIVE011/offline-native-003"


def sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("source or archive path absent/symlinked")
    return sha256(path.read_bytes()).hexdigest()


def source_inventory() -> dict[str, str]:
    return {name: sha(ROOT / name) for name in source_file_names()}


def source_file_names() -> tuple[str, ...]:
    """Seal the entire local Python/Node executable closure and named controls."""
    names = set(SOURCE_FILES)
    for directory, suffixes in ((ROOT / "src/agent_economic_trust", {".py"}),
                                (ROOT / "scripts", {".py", ".mjs"})):
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix in suffixes:
                names.add(str(path.relative_to(ROOT)))
    for path in (ROOT / "tests").glob("test_x402*.py"):
        names.add(str(path.relative_to(ROOT)))
    return tuple(sorted(names))


def clean_versioned_sources() -> bool:
    names = source_file_names()
    tracked = subprocess.run(["git", "ls-files", "--", *names],
                             cwd=ROOT, capture_output=True, text=True, check=True)
    if set(tracked.stdout.splitlines()) != set(names):
        return False
    result = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                            cwd=ROOT, capture_output=True, text=True, check=True)
    changed = {line[3:] for line in result.stdout.splitlines() if len(line) >= 4}
    return not (changed & set(names))


def read_only_readiness(*, refresh_pricing: bool) -> dict:
    sources = source_inventory()
    archive = verify_010(OFFLINE_010)
    if (OFFLINE_011 / "report.json").is_file():
        try:
            offline_011 = verify_011(OFFLINE_011)
        except Exception as exc:
            offline_011 = {"status": "FAILED", "error_type": type(exc).__name__}
    else:
        offline_011 = {"status": "MISSING"}
    strict_tools = offline_real_tool_schema_control()
    native_sources = native_source_readiness()
    runtime = {"orbit_version": version("orbit"),
               "inspect_ai_version": version("inspect_ai"),
               "native_sources_ready": native_sources["all_native_sources_ready"],
               "upstreams": native_sources["upstreams"]}
    state = BudgetLedger(CANONICAL_LEDGER).snapshot()
    reasons = []
    if ROOT.resolve() != canonical_project_root().resolve():
        reasons.append("NONCANONICAL_WORKTREE")
    if not clean_versioned_sources():
        reasons.append("VERSIONED_SOURCE_DIRTY")
    if archive["status"] != "PASS" or archive["native_cells_reverified"] != 4:
        reasons.append("NATIVE_010_FOUR_CELL_ARCHIVE_FAILED")
    if (offline_011.get("status") != "PASS"
            or offline_011.get("scripted_cases_reverified") != 3):
        reasons.append("NATIVE_011_SCRIPTED_BRIDGE_CONTROLS_FAILED_OR_MISSING")
    if strict_tools["status"] != "PASS":
        reasons.append("REAL_ORBIT_TOOL_SCHEMAS_NOT_STRICT")
    if (runtime["orbit_version"] != "1.0.3"
            or runtime["inspect_ai_version"] != "0.3.263"
            or not runtime["native_sources_ready"]):
        reasons.append("PINNED_RUNTIME_OR_NATIVE_SOURCE_NOT_READY")
    if (state.get("cap_usd") != "50" or state.get("blocked")
            or state.get("unknown_run_ids")):
        reasons.append("CANONICAL_USD50_LEDGER_BLOCKED")
    try:
        fee011_failed_request_hold(state)
    except (ValueError, KeyError):
        reasons.append("PRIOR_MPP006_OR_FEE011_HOLD_NOT_RECONCILED")
    if refresh_pricing:
        prices = pricing_snapshots()
        rows = make_schedule("00" * 32)  # design-only IDs, never a live assignment
        by_cell = {f"{r.truth}:{r.payer_role}": str(reserve_pair(prices, r))
                   for r in rows}
        required = required_headroom(prices, rows)
        if required > Decimal(state["available_usd"]):
            reasons.append("FULL_FOUR_ROW_BLOCK_EXCEEDS_CURRENT_HEADROOM")
        price = {"basis": "CURRENT_PUBLIC_MODEL_CATALOG_NO_BILLING_KEY",
                 "catalog_model_sha256": {m: prices[m]["catalog_model_sha256"]
                                          for m in (SOL, SONNET)},
                 "worst_case_usd_by_cell": by_cell,
                 "full_four_row_plus_contingency_and_residual_usd": str(required)}
    else:
        price = {"basis": "UNREFRESHED_NO_SPEND_AUTHORIZATION"}
        reasons.append("CURRENT_PUBLIC_PRICE_REFRESH_REQUIRED")
    reasons.extend(("PROSPECTIVE_ASSIGNMENT_NOT_FROZEN",
                    "LIVE_RAW_MODEL_BOUNDARY_AND_COLLECTOR_NOT_YET_REVIEWED",
                    "INDEPENDENT_GO_REVIEW_NOT_RECORDED"))
    return {"schema": "x402-live011-read-only-readiness-v1",
            "would_freeze": False, "would_call_paid_model": False,
            "source_inventory_sha256": sha256(json.dumps(sources, sort_keys=True,
                separators=(",", ":")).encode()).hexdigest(),
            "source_sha256": sources,
            "offline_010": archive,
            "offline_011": offline_011,
            "actual_orbit_tool_schema_control": strict_tools,
            "runtime_pins": runtime,
            "ledger": {k: state[k] for k in ("seq", "last_hash", "cap_usd",
                                              "settled_spent_usd", "reserved_usd",
                                              "available_usd", "unknown_run_ids")},
            "pricing": price,
            "blockers": reasons,
            "permission_to_freeze_or_pay": False,
            "payment_limitations": {
                "x402": "local exact/EIP-3009 retainer buys intake only",
                "erc8183": "separate local job; application dispatches verdict",
                "psp_capture": False,
                "cross_chain_atomic": False}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-pricing", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = read_only_readiness(refresh_pricing=args.refresh_pricing)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"would_freeze": result["would_freeze"],
                      "ledger_seq": result["ledger"]["seq"],
                      "available_usd": result["ledger"]["available_usd"],
                      "pricing": result["pricing"],
                      "blockers": result["blockers"]}, sort_keys=True))
