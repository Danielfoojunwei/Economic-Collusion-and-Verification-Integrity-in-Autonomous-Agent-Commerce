#!/usr/bin/env python3
"""Read-only prospective x402 source, native-control and full-block budget preview.

No assignment freeze, remote model call, or budget-ledger mutation occurs here.
The preview deliberately cannot authorize a live run while its ORBIT task,
collector, model-boundary checks and independent GO review are absent.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402
from agent_economic_trust.mpp008_pricing import pricing_snapshots  # noqa: E402


X402_COMMIT = "e95b06661e1a2a8a9a21fce34cc28b9934834650"
ERC_COMMIT = "142e669c1fd318486a4628395b629f033654dd06"
SOL = "openai/gpt-5.6-sol"
SONNET = "anthropic/claude-sonnet-5.5"
INPUT_BYTES = 49_152
FRAMING_TOKENS = 8_192
OUTPUT_TOKENS = 4_096
PROVIDER_CALLS = 5
AUDITOR_CALLS = 7
ROWS = 4
CONTINGENCY_USD = Decimal("2")
RESIDUAL_USD = Decimal("0.0000342")
MAIN_LEDGER = (Path("/workspace/Economic-Collusion-and-Verification-Integrity-in-Autonomous-Agent-Commerce")
               / "artifacts/budget/openrouter-ledger.jsonl")
SOURCES = (
    "AGENTS.md", "UPSTREAM_PINNED.json",
    "docs/PROSPECTIVE_X402_AUDIT_RETAINER_010.md",
    "contracts/x402/TestEIP3009Token.sol",
    "scripts/run_erc8183_local.py", "scripts/run_x402_audit_retainer.mjs",
    "scripts/run_x402_retainer_offline.py", "scripts/preview_x402_retainer.py",
    "scripts/verify_x402_retainer_offline.py",
    "src/agent_economic_trust/ap2_live_fixture.py",
    "src/agent_economic_trust/core.py",
    "src/agent_economic_trust/x402_audit_retainer.py",
    "src/agent_economic_trust/x402_audit_retainer_verifier.py",
    "src/agent_economic_trust/x402_retainer_job.py",
    "src/agent_economic_trust/x402_retainer_job_verifier.py",
    "tests/test_x402_retainer.py",
)


def git(path: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=path, check=True,
                          capture_output=True, text=True).stdout.strip()


def source_readiness() -> dict:
    paths = {}
    for name in SOURCES:
        file = ROOT / name
        if not file.is_file() or file.is_symlink():
            raise ValueError(f"source missing or symlinked: {name}")
        paths[name] = sha256(file.read_bytes()).hexdigest()
    pin = json.loads((ROOT / "UPSTREAM_PINNED.json").read_bytes())["sources"]
    # Check actual install paths, not only a declaration in UPSTREAM_PINNED.
    x402 = Path("/workspace/upstreams/x402")
    erc = Path("/workspace/upstreams/erc8183")
    upstreams = {}
    for label, path, commit in (("x402", x402, X402_COMMIT),
                                ("erc8183", erc, ERC_COMMIT)):
        head = git(path, "rev-parse", "HEAD")
        clean = not git(path, "status", "--porcelain")
        upstreams[label] = {"expected_commit": commit, "observed_commit": head,
                            "clean": clean, "ready": head == commit and clean}
    binaries = {}
    for label, path in {
        "anvil": Path("/workspace/.tools/foundry/v1.8.5/anvil"),
        "forge": Path("/workspace/.tools/foundry/v1.8.5/forge"),
        "solc": Path("/workspace/.tools/solc/v0.8.28/solc"),
    }.items():
        binaries[label] = path.is_file()
    binaries["node"] = shutil.which("node") is not None
    sdk = (x402 / "typescript/packages/mechanisms/evm/dist/esm/exact/client/index.mjs").is_file()
    return {"source_sha256": paths,
            "source_inventory_sha256": sha256(json.dumps(paths, sort_keys=True,
                separators=(",", ":")).encode()).hexdigest(),
            "upstreams": upstreams, "binaries": binaries,
            "x402_exact_sdk_built": sdk,
            "all_native_sources_ready": all(item["ready"] for item in upstreams.values())
                and all(binaries.values()) and sdk,
            "pinned_manifest_present": bool(pin)}


def price_preview(*, refresh: bool) -> dict:
    if refresh:
        snapshots = pricing_snapshots()  # public catalog GET, no authentication
        rates = {model: {
            "input": Decimal(snapshots[model]["input_usd_per_token"]),
            "output": Decimal(snapshots[model]["output_usd_per_token"]),
            "request": Decimal(snapshots[model]["request_usd"]),
        } for model in (SOL, SONNET)}
        for model in (SOL, SONNET):
            if (snapshots[model]["context_length"] < INPUT_BYTES + FRAMING_TOKENS + OUTPUT_TOKENS
                    or snapshots[model]["max_completion_tokens"] < OUTPUT_TOKENS):
                raise ValueError(f"{model} catalog context/completion limit too small")
        origin = "REFRESHED_PUBLIC_CATALOG_NO_BILLING_KEY"
        catalog_hashes = {model: snapshots[model]["catalog_model_sha256"]
                          for model in (SOL, SONNET)}
    else:
        rates = {SOL: {"input": Decimal("0.00001"),
                       "output": Decimal("0.00003"), "request": Decimal(0)},
                 SONNET: {"input": Decimal("0.000004"),
                          "output": Decimal("0.00001"), "request": Decimal(0)}}
        origin = "2026-10-15_15:06_UTC_HISTORICAL_ILLUSTRATION_NOT_CURRENT_PRICE"
        catalog_hashes = None
    def one(model: str, calls: int) -> Decimal:
        rate = rates[model]
        return calls * ((INPUT_BYTES + FRAMING_TOKENS) * rate["input"]
                        + OUTPUT_TOKENS * rate["output"] + rate["request"])
    per_row = one(SOL, PROVIDER_CALLS) + one(SONNET, AUDITOR_CALLS)
    block = ROWS * per_row
    full = block + CONTINGENCY_USD + RESIDUAL_USD
    return {"price_origin": origin, "catalog_model_sha256": catalog_hashes,
            "models": {"provider": SOL, "auditor": SONNET},
            "schedule_calls_per_row": {"provider": PROVIDER_CALLS,
                                       "auditor": AUDITOR_CALLS},
            "max_serialized_input_bytes": INPUT_BYTES,
            "input_framing_tokens_per_call": FRAMING_TOKENS,
            "max_output_tokens_per_call": OUTPUT_TOKENS,
            "rows": ROWS, "per_row_usd": str(per_row),
            "model_block_usd": str(block),
            "contingency_usd": str(CONTINGENCY_USD),
            "unassigned_export_residual_usd": str(RESIDUAL_USD),
            "full_new_block_usd": str(full)}


def preview(ledger: Path, offline_report: Path | None, *, refresh_pricing: bool) -> dict:
    source = source_readiness()
    price = price_preview(refresh=refresh_pricing)
    budget = BudgetLedger(ledger).snapshot()
    if offline_report is None:
        offline = {"status": "UNRUN_IN_THIS_PREFLIGHT"}
    else:
        report = json.loads(offline_report.read_bytes())
        if (report.get("status") != "PASS" or report.get("paid_model_calls") != 0
                or report.get("complete_native_cells") != 4
                or report.get("tamper_negatives_rejected") != 24):
            raise ValueError("offline evidence does not cover four native cells and 24 negatives")
        offline = {"status": "PASS", "sha256": sha256(offline_report.read_bytes()).hexdigest(),
                   "model_tier": "SCRIPTED_SIMULATION",
                   "transaction_tier": "NATIVE_LOCAL_PROTOCOL"}
    available = Decimal(budget["available_usd"])
    needed = Decimal(price["full_new_block_usd"])
    reasons = ["ORBIT_LIVE_TASK_AND_ROLE_BOUNDARY_NOT_YET_IMPLEMENTED",
               "FROZEN_ASSIGNMENT_AND_INDEPENDENT_COLLECTOR_NOT_YET_IMPLEMENTED",
               "INDEPENDENT_GO_REVIEW_NOT_YET_RECORDED"]
    if offline["status"] != "PASS":
        reasons.append("FOUR_CELL_NATIVE_OFFLINE_CONTROLS_NOT_SUPPLIED")
    if budget["unknown_run_ids"]:
        reasons.append("UNKNOWN_PRIOR_BILLING")
    if available < needed:
        reasons.append("FULL_FOUR_ROW_BLOCK_EXCEEDS_CURRENT_LEDGER_HEADROOM")
    if not refresh_pricing:
        reasons.append("HISTORICAL_PRICE_REQUIRES_REFRESH_AT_FREEZE")
    if not source["all_native_sources_ready"]:
        reasons.append("NATIVE_SOURCE_OR_TOOLCHAIN_NOT_READY")
    return {"schema": "x402-retainer-read-only-preview-v1",
            "would_freeze": False, "would_call_paid_model": False,
            "source": source, "offline_controls": offline, "pricing": price,
            "ledger": {"path": str(ledger), "seq": budget["seq"],
                       "cap_usd": budget["cap_usd"],
                       "settled_spent_usd": budget["settled_spent_usd"],
                       "reserved_usd": budget["reserved_usd"],
                       "available_usd": budget["available_usd"],
                       "contingent_run_count": len(budget["contingent_run_ids"]),
                       "unknown_run_count": len(budget["unknown_run_ids"])},
            "full_block_fits_current_headroom": available >= needed,
            "not_live_ready_reasons": reasons}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=MAIN_LEDGER)
    parser.add_argument("--offline-report", type=Path)
    parser.add_argument("--refresh-pricing", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = preview(args.ledger, args.offline_report,
                     refresh_pricing=args.refresh_pricing)
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(serialized)
    print(json.dumps({"would_freeze": result["would_freeze"],
                      "full_block_fits_current_headroom": result["full_block_fits_current_headroom"],
                      "full_new_block_usd": result["pricing"]["full_new_block_usd"],
                      "not_live_ready_reasons": result["not_live_ready_reasons"]},
                     sort_keys=True))
