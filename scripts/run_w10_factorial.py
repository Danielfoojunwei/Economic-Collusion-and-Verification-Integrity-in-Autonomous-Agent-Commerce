#!/usr/bin/env python3
"""Freeze or audit W10 pair-level assignments without calling a model.

This CLI deliberately has no paid ``--execute`` mode. Economic execution
needs a native per-pair funding verifier and a bounded live runner connection;
the separate W10 protected-receipt pilot supplies neither relationship arm.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = str(WORKSPACE / ".local" / "share")
os.environ["XDG_CACHE_HOME"] = str(WORKSPACE / ".cache")
os.environ["XDG_CONFIG_HOME"] = str(WORKSPACE / ".config")
sys.path.insert(0, str(ROOT / "src"))

from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402
from agent_economic_trust.w10_factorial import (  # noqa: E402
    _canonical, _hash, analyze_assignments, assignment_manifest,
    frozen_fixtures, make_assignments,
)


LEDGER = ROOT / "artifacts" / "budget" / "openrouter-ledger.jsonl"


def _new_file(path: Path, value: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def freeze(output: Path, seed_hex: str, ledger_path: Path) -> dict:
    if output.exists():
        raise FileExistsError("W10 plan output already exists")
    if ledger_path.resolve() != LEDGER.resolve():
        raise ValueError("W10 must inspect the one project-wide ledger")
    budget = BudgetLedger(ledger_path).snapshot()
    if budget["cap_usd"] != "20":
        raise ValueError("project ledger cap differs from owner's USD 20 authorization")
    manifest = assignment_manifest(seed_hex)
    private = [fixture.private_row() for fixture in frozen_fixtures()]
    if manifest["fixtures_private_sha256"] != _hash(private):
        raise AssertionError("private fixture commitment changed")
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    _new_file(output / "seed.hex", (seed_hex + "\n").encode("ascii"))
    _new_file(output / "private_fixtures.json", _canonical(private) + b"\n")
    budget_summary = {
        "cap_usd": budget["cap_usd"],
        "settled_spent_usd": budget["settled_spent_usd"],
        "reserved_usd": budget["reserved_usd"],
        "available_usd": budget["available_usd"],
        "blocked": budget["blocked"],
        "ledger_last_hash": budget["last_hash"],
    }
    manifest.update({
        "budget_at_freeze": budget_summary,
        "project_ledger": str(ledger_path.resolve()),
        "source_sha256": {
            path: sha256((ROOT / path).read_bytes()).hexdigest()
            for path in (
                "src/agent_economic_trust/w10_factorial.py",
                "src/agent_economic_trust/protected_receipts.py",
                "scripts/run_w10_factorial.py",
            )
        },
        "upstream_versions": {"orbit": "1.0.3", "inspect_ai": "0.3.263"},
        "economic_execution_ready": False,
        "execution_blocker": "per_pair_native_funding_verifier_not_integrated",
    })
    _new_file(output / "assignment_manifest.json", _canonical(manifest) + b"\n")
    return {
        "mode": "freeze_only", "assignment_count": manifest["primary_episodes"],
        "assignment_manifest_sha256": sha256(
            (output / "assignment_manifest.json").read_bytes()).hexdigest(),
        "economic_execution_ready": False,
        "model_calls": 0, "payment_transactions": 0,
        "ledger_available_usd": budget_summary["available_usd"],
    }


def analyze(plan_dir: Path, records_path: Path, output: Path) -> dict:
    seed_hex = (plan_dir / "seed.hex").read_text(encoding="ascii").strip()
    manifest = json.loads((plan_dir / "assignment_manifest.json").read_text())
    private = json.loads((plan_dir / "private_fixtures.json").read_text())
    if _hash(private) != manifest["fixtures_private_sha256"]:
        raise ValueError("private fixture commitment differs from frozen plan")
    trials = make_assignments(seed_hex)
    if _hash([trial.as_dict() for trial in trials]) != manifest["assignments_sha256"]:
        raise ValueError("assignment rows differ from frozen plan")
    records = []
    for raw in records_path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            records.append(json.loads(raw))
    result = analyze_assignments(trials, records)
    result.update({
        "assignment_manifest_sha256": sha256(
            (plan_dir / "assignment_manifest.json").read_bytes()).hexdigest(),
        "records_sha256": sha256(records_path.read_bytes()).hexdigest(),
        "economic_claim_ready": False,
        "reason": "analysis validates record fields but does not verify native files or payment linkage",
    })
    _new_file(output, _canonical(result) + b"\n")
    return {"mode": "descriptive_audit_only", "assignment_count": len(trials),
            "reported_count": len(records), "economic_claim_ready": False,
            "analysis_sha256": sha256(output.read_bytes()).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    freeze_args = modes.add_parser("freeze")
    freeze_args.add_argument("--output", type=Path, required=True)
    freeze_args.add_argument("--seed", default=None,
                             help="32 bytes of lowercase hex, generated if omitted")
    freeze_args.add_argument("--ledger", type=Path, default=LEDGER)
    analyze_args = modes.add_parser("analyze")
    analyze_args.add_argument("--plan", type=Path, required=True)
    analyze_args.add_argument("--records", type=Path, required=True)
    analyze_args.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.mode == "freeze":
            result = freeze(args.output, args.seed or secrets.token_hex(32), args.ledger)
        else:
            result = analyze(args.plan, args.records, args.output)
    except Exception as exc:
        print(f"W10 factorial stopped: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
