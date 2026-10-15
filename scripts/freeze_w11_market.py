#!/usr/bin/env python3
"""Freeze or revalidate W11 market assignments; never calls a paid model."""

from __future__ import annotations

import argparse
from importlib.metadata import version
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = str(WORKSPACE / ".local" / "share")
os.environ["XDG_CACHE_HOME"] = str(WORKSPACE / ".cache")
os.environ["XDG_CONFIG_HOME"] = str(WORKSPACE / ".config")
sys.path.insert(0, str(ROOT / "src"))

from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402
from agent_economic_trust.w11_market_plan import (  # noqa: E402
    canonical, digest, make_market_schedule, manifest,
)


LEDGER = ROOT / "artifacts/budget/openrouter-ledger.jsonl"
G4_AGGREGATE = ROOT / "artifacts/gates/G4/aggregate-pilot-001/aggregate_run_manifest.json"
SOURCE_FILES = (
    "src/agent_economic_trust/__init__.py",
    "src/agent_economic_trust/w11_market_plan.py",
    "src/agent_economic_trust/w11_market_task.py",
    "src/agent_economic_trust/w11_market_native.py",
    "src/agent_economic_trust/w11_market_remote.py",
    "src/agent_economic_trust/w11_market_log_integrity.py",
    "src/agent_economic_trust/w11_market_reporting.py",
    "src/agent_economic_trust/w11_market_analysis.py",
    "src/agent_economic_trust/w10_factorial.py",
    "src/agent_economic_trust/w10_factorial_remote.py",
    "src/agent_economic_trust/w10_factorial_reporting.py",
    "src/agent_economic_trust/w10_live_native.py",
    "src/agent_economic_trust/w10_funding.py",
    "src/agent_economic_trust/protected_receipts.py",
    "src/agent_economic_trust/remote.py",
    "src/agent_economic_trust/remote_reporting.py",
    "src/agent_economic_trust/remote_budget.py",
    "src/agent_economic_trust/remote_pricing.py",
    "src/agent_economic_trust/orbit_task.py",
    "src/agent_economic_trust/reporting.py",
    "src/agent_economic_trust/evidence.py",
    "src/agent_economic_trust/core.py",
    "schemas/event.schema.json",
    "schemas/run_manifest.schema.json",
    "scripts/run_erc8183_local.py",
    "scripts/run_w11_market.py",
    "scripts/run_w11_market_scripted_smoke.py",
    "scripts/collect_w11_market.py",
    "scripts/freeze_w11_market.py",
    "tests/test_w11_market_task.py",
)


def sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def upstream_pins() -> dict:
    pinned_path = ROOT / "UPSTREAM_PINNED.json"
    pinned = json.loads(pinned_path.read_bytes())
    sources = pinned["sources"]
    for name, release in (("orbit", "1.0.3"), ("inspect_ai", "0.3.263")):
        source = sources[name]
        checkout = Path(source["source_checkout"])
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=checkout,
                              capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=checkout,
                               capture_output=True, text=True, check=True).stdout.strip()
        if head != source["commit"] or dirty or version(name) != release:
            raise ValueError(f"{name} installed/source version differs from W01 pin")
    return {"pin_manifest_sha256": sha(pinned_path),
            "orbit_commit": sources["orbit"]["commit"],
            "orbit_wheel_sha256": sources["orbit"]["wheel_sha256"],
            "inspect_ai_commit": sources["inspect_ai"]["commit"],
            "inspect_ai_wheel_sha256": sources["inspect_ai"]["installed_wheel_sha256"]}


def _new_file(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def freeze(output: Path, *, seed_hex: str, blocks: int = 1) -> dict:
    if output.exists():
        raise FileExistsError("W11 assignment output already exists")
    aggregate = json.loads(G4_AGGREGATE.read_bytes())
    if (aggregate.get("schema") != "g4-aggregate-run-manifest-v1"
            or aggregate.get("status") != "COMPLETE_VERIFIED"
            or aggregate.get("independently_reverified_count") != 32):
        raise ValueError("G4 32-trial verified aggregate prerequisite is missing")
    budget = BudgetLedger(LEDGER).snapshot()
    if budget["blocked"] or budget["cap_usd"] != "20":
        raise ValueError("shared USD 20 project ledger is blocked or changed")
    rows = make_market_schedule(seed_hex, blocks=blocks)
    payload = manifest(seed_hex, rows)
    payload["g4_aggregate_manifest_sha256"] = sha(G4_AGGREGATE)
    payload["g4_assignment_manifest_sha256"] = aggregate["assignment_manifest_sha256"]
    payload["source_sha256"] = {name: sha(ROOT / name) for name in SOURCE_FILES}
    payload["upstream_pins"] = upstream_pins()
    payload["budget_at_freeze"] = {
        key: budget[key] for key in ("cap_usd", "settled_spent_usd", "reserved_usd",
                                       "available_usd", "blocked", "last_hash")
    }
    payload["economic_execution_status"] = "PENDING_W11_SCRIPTED_AND_NATIVE_GATES"
    private = [row.__dict__ for row in rows]
    if digest(private) != payload["private_rows_sha256"]:
        raise AssertionError("private market assignment digest differs")
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    _new_file(output / "seed.hex", (seed_hex + "\n").encode("ascii"))
    _new_file(output / "private_rounds.json", canonical(private) + b"\n")
    _new_file(output / "assignment_manifest.json", canonical(payload) + b"\n")
    return {"assignment_manifest_sha256": sha(output / "assignment_manifest.json"),
            "markets": payload["planned_markets"], "episodes": payload["planned_episodes"],
            "g4_aggregate_manifest_sha256": payload["g4_aggregate_manifest_sha256"],
            "ledger_available_usd": budget["available_usd"],
            "model_calls": 0, "payment_transactions": 0}


def verify(plan_dir: Path) -> dict:
    raw = (plan_dir / "assignment_manifest.json").read_bytes()
    payload = json.loads(raw)
    seed_hex = (plan_dir / "seed.hex").read_text(encoding="ascii").strip()
    private = json.loads((plan_dir / "private_rounds.json").read_bytes())
    if payload.get("schema") != "w11-prospective-market-assignment-v2":
        raise ValueError("not a W11 prospective market plan")
    rows = make_market_schedule(seed_hex,
                                blocks=len({row["block_id"] for row in private}),
                                r_values=tuple(sorted({row["r"] for row in private})))
    expected_core = json.loads(canonical(manifest(seed_hex, rows)))
    if (any(payload.get(key) != value for key, value in expected_core.items())
            or json.loads(canonical([row.__dict__ for row in rows])) != private
            or payload["private_rows_sha256"] != digest(private)
            or payload["public_rows_sha256"] != digest([row.public_row() for row in rows])
            or payload["rows"] != json.loads(canonical([row.public_row() for row in rows]))
            or payload["g4_aggregate_manifest_sha256"] != sha(G4_AGGREGATE)
            or payload["upstream_pins"] != upstream_pins()
            or payload["source_sha256"] != {name: sha(ROOT / name) for name in SOURCE_FILES}):
        raise ValueError("frozen market inputs or source changed")
    budget = BudgetLedger(LEDGER).snapshot()
    if budget["blocked"] or budget["cap_usd"] != "20":
        raise ValueError("shared project ledger is blocked or changed")
    return {"assignment_manifest_sha256": sha(plan_dir / "assignment_manifest.json"),
            "markets": len({row.market_id for row in rows}), "episodes": len(rows),
            "ledger_available_usd": budget["available_usd"], "blocked": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    frozen = commands.add_parser("freeze")
    frozen.add_argument("--output", type=Path, required=True)
    frozen.add_argument("--seed", default=None)
    frozen.add_argument("--blocks", type=int, default=1)
    verified = commands.add_parser("verify")
    verified.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = (freeze(args.output, seed_hex=args.seed or secrets.token_hex(32),
                         blocks=args.blocks) if args.command == "freeze" else
                  verify(args.plan))
    except Exception as exc:
        print(f"W11 assignment stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
