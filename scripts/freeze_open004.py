#!/usr/bin/env python3
"""One-time OPEN004 assignment and read-only source/budget preflight."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
import json
from importlib.metadata import version
import subprocess
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from agent_economic_trust.open004_plan import (  # noqa: E402
    MAX_CALLS_PER_EPISODE, MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS, canonical,
    digest, make_schedule, manifest,
)
from agent_economic_trust.remote import PROJECT_LEDGER_PATH  # noqa: E402
from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402
from agent_economic_trust.remote_pricing import pricing_snapshot, reserve_worst_case  # noqa: E402

GATE_ROOT = ROOT / "artifacts/gates/OPEN004"
ASSIGNMENT_DIR = GATE_ROOT / "assignment-invoice-001"
FREEZE_LOCK = GATE_ROOT / "invoice-first-freeze.lock.json"
OFFLINE_REPORT = GATE_ROOT / "offline-invoice/report.json"
LEDGER = PROJECT_LEDGER_PATH
CONTINGENCY_USD = Decimal("2")


def sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("source/evidence path must be a regular file")
    return sha256(path.read_bytes()).hexdigest()


def source_inventory() -> dict[str, str]:
    """Seal executable closure and native dependency declarations, not artifacts."""
    files = {"docs/PROSPECTIVE_HETEROGENEOUS_SERVICES_004.md", "AGENTS.md",
             "UPSTREAM_PINNED.json", "contracts/x402/TestEIP3009Token.sol"}
    for directory, patterns in (("src/agent_economic_trust", ("*.py",)),
                                 ("scripts", ("*.py", "*.mjs", "*.sh")),
                                 ("tests", ("test_open004*.py", "test_x402_invoice*.py")),
                                 ("protocols", ("*.json", "*.toml", "*.sol"))):
        for pattern in patterns:
            files.update(str(p.relative_to(ROOT)) for p in (ROOT / directory).rglob(pattern)
                         if p.is_file() and "node_modules" not in p.parts)
    return {name: sha(ROOT / name) for name in sorted(files)}


def prior_003_disposition() -> dict:
    """Authenticate the archived preregistered stop; never reopen 003 execution."""
    base = ROOT / "artifacts/gates/MECHANISM_PILOT"
    collection_path = base / "collection-003-after-episode-01.json"
    assignment_path = base / "assignment-003/assignment_manifest.json"
    expected_collection = "36e9057f67e25b7ec57a0dfcda1786de70cab1bd021a6f4d9f02d94fdffd24aa"
    expected_assignment = "c5ff690b2af5a67846ef49ea4851d7ee66a428994b2f7c28ff79385e8b92ff53"
    if sha(collection_path) != expected_collection or sha(assignment_path) != expected_assignment:
        raise ValueError("archived 003 disposition or assignment changed")
    collection = json.loads(collection_path.read_bytes())
    assignment = json.loads(assignment_path.read_bytes())
    rows = collection["rows"]
    if (len(rows) != 12 or sum(r["status"] == "COMPLETE" for r in rows) != 1
            or sum(r["status"] == "PENDING" for r in rows) != 11
            or collection["assignment_manifest_sha256"] != expected_assignment
            or {r["episode_id"] for r in rows} != {r["episode_id"] for r in assignment["rows"]}):
        raise ValueError("archived 003 assigned denominator differs")
    completed = next(r for r in rows if r["status"] == "COMPLETE")
    if (completed.get("direct_message_exact") is not False
            or completed.get("direct_read_exact") is not False):
        raise ValueError("archived 003 preregistered exact-post stop absent")
    documentation = ROOT / "docs/PILOT_003_EARLY_STOP_AND_FINDINGS.md"
    files = (collection_path, assignment_path, base / "third-freeze.lock.json", documentation)
    return {"status": "IRREVOCABLY_STOPPED_BY_PREREGISTERED_DIRECT_POST_FAILURE",
            "remaining_003_obligation_reserve_usd": "0", "complete": 1, "pending_preserved": 11,
            "archive_sha256": {str(p.relative_to(ROOT)): sha(p) for p in files}}


def runtime_pins() -> dict:
    """Seal clean upstream commits, installed runtime and actual deployable bytes."""
    pins = json.loads((ROOT / "UPSTREAM_PINNED.json").read_bytes())["sources"]
    output = {}
    def clean(path: Path, expected: str) -> str:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, capture_output=True,
                              text=True, check=True, timeout=20).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=path, capture_output=True,
                               text=True, check=True, timeout=20).stdout.strip()
        if head != expected or dirty:
            raise ValueError("OPEN004 upstream checkout differs from clean commit")
        return head
    for name, expected_version in (("orbit", "1.0.3"), ("inspect_ai", "0.3.263")):
        pin = pins[name]
        if version(name) != expected_version:
            raise ValueError("OPEN004 installed orchestration version differs")
        output[name] = {"commit": clean(Path(pin["source_checkout"]), pin["commit"]),
                        "version": expected_version}
    from scripts.run_erc8183_local import ANVIL, FORGE, CAST, SOLC, UPSTREAM, PIN, SUBMODULE_PINS
    output["erc8183"] = clean(UPSTREAM, PIN)
    output["erc8183_submodules"] = {name: clean(UPSTREAM / name, commit)
                                        for name, commit in SUBMODULE_PINS.items()}
    output["native_toolchain"] = {name: sha(path) for name, path in
                                   (("anvil", ANVIL), ("forge", FORGE), ("cast", CAST), ("solc", SOLC))}
    output["erc8183_builds"] = {name: sha(UPSTREAM / "out" / (name + ".sol") / (name + ".json"))
                                for name in ("ERC8183", "ERC1967Proxy", "MockUSDC")}
    sdk = Path(os.environ.get("X402_SDK_ROOT", "/workspace/upstreams/x402/typescript"))
    output["x402"] = clean(sdk.parent, "e95b06661e1a2a8a9a21fce34cc28b9934834650")
    dist_files = list((sdk / "packages").rglob("dist/esm/**/*.mjs"))
    if not dist_files:
        raise ValueError("OPEN004 x402 built SDK missing")
    output["x402_runtime_sha256"] = {str(p.relative_to(sdk)): sha(p) for p in sorted(dist_files)}
    return output


def offline_readiness(sources: dict[str, str]) -> dict:
    """Reopen every saved control rather than trusting a report PASS string."""
    report = json.loads(OFFLINE_REPORT.read_bytes())
    if (report.get("schema") != "open004-offline-invoice-v1"
            or report.get("paid_model_calls") != 0
            or report.get("source_inventory_sha256") != digest(sources)):
        raise ValueError("OPEN004 offline source seal or report differs")
    from agent_economic_trust.open004_reporting import verify_offline_controls
    verified = verify_offline_controls(OFFLINE_REPORT.parent, report)
    if verified.get("status") != "PASS":
        raise ValueError("OPEN004 offline controls failed independent verification")
    return {"report_sha256": sha(OFFLINE_REPORT), **verified}


def _ledger_snapshot() -> dict:
    state = BudgetLedger(LEDGER).snapshot()
    if state["cap_usd"] != "50" or state["blocked"] or state["unknown_run_ids"]:
        raise ValueError("canonical lifetime USD50 ledger blocked")
    return state


def verify_ledger_ancestor(frozen: dict) -> dict:
    state = _ledger_snapshot()
    lines = LEDGER.read_bytes().splitlines()
    if (state["seq"] < frozen["seq"] or len(lines) <= frozen["seq"]
            or json.loads(lines[frozen["seq"]])["hash"] != frozen["last_hash"]):
        raise ValueError("frozen budget head is not current ledger ancestor")
    return state


def _new(path: Path, content: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())


def load_assignment(directory: Path = ASSIGNMENT_DIR) -> tuple[dict, str, tuple]:
    directory = Path(directory)
    rows = make_schedule((directory / "seed.hex").read_text().strip())
    expected = manifest((directory / "seed.hex").read_text().strip(), rows)
    path = directory / "assignment_manifest.json"
    frozen = json.loads(path.read_bytes())
    if (any(frozen.get(k) != v for k, v in expected.items())
            or json.loads((directory / "private_episodes.json").read_bytes()) != [asdict(r) for r in rows]):
        raise ValueError("seed or private assignment changed")
    lock = json.loads((directory.parent / FREEZE_LOCK.name).read_bytes())
    if lock != {"schema": "open004-one-time-freeze-v1",
                "assignment_manifest_sha256": sha(path),
                "seed_commitment_sha256": expected["seed_commitment_sha256"]}:
        raise ValueError("one-time OPEN004 freeze lock changed")
    return frozen, sha(path), rows


def freeze(*, seed_hex: str | None = None) -> dict:
    if FREEZE_LOCK.exists() or ASSIGNMENT_DIR.exists():
        raise FileExistsError("OPEN004 already or partially frozen; no reroll")
    seed_hex = secrets.token_hex(32) if seed_hex is None else seed_hex
    rows = make_schedule(seed_hex)
    payload = manifest(seed_hex, rows)
    sources = source_inventory()
    offline = offline_readiness(sources)
    runtime = runtime_pins()
    prior = prior_003_disposition()
    prices = pricing_snapshot()
    reserve = reserve_worst_case(prices, MAX_CALLS_PER_EPISODE, MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS)
    state = _ledger_snapshot()
    if reserve * len(rows) + CONTINGENCY_USD > Decimal(state["available_usd"]):
        raise ValueError("full OPEN004 block worst-case reserve exceeds lifetime headroom")
    payload.update(source_sha256=sources, offline_readiness=offline, runtime_pins=runtime, prior_003_disposition=prior,
                   contingency_reserve_usd=str(CONTINGENCY_USD),
                   public_pricing_snapshot=prices,
                   budget_at_freeze={k: state[k] for k in ("seq", "last_hash", "cap_usd", "available_usd")},
                   worst_case_reserve_usd_per_episode=str(reserve),
                   worst_case_reserve_usd_full_block=str(reserve * len(rows)))
    GATE_ROOT.mkdir(parents=True, exist_ok=True)
    raw = canonical(payload) + b"\n"
    # Claim the one-time lock before making any assignment files. A partial
    # failure permanently stops this assignment rather than permitting rerolls.
    _new(FREEZE_LOCK, canonical({"schema": "open004-one-time-freeze-v1",
         "assignment_manifest_sha256": sha256(raw).hexdigest(),
         "seed_commitment_sha256": payload["seed_commitment_sha256"]}) + b"\n")
    ASSIGNMENT_DIR.mkdir(mode=0o700)
    _new(ASSIGNMENT_DIR / "seed.hex", (seed_hex + "\n").encode())
    _new(ASSIGNMENT_DIR / "private_episodes.json", canonical([asdict(r) for r in rows]) + b"\n")
    _new(ASSIGNMENT_DIR / "assignment_manifest.json", raw)
    return {"planned_episodes": len(rows), "assignment_manifest_sha256": sha256(raw).hexdigest(),
            "full_reserve_usd": str(reserve * len(rows)), "paid_model_calls": 0}


def verify() -> dict:
    frozen, assignment_sha, rows = load_assignment(ASSIGNMENT_DIR)
    if frozen["source_sha256"] != source_inventory():
        raise ValueError("OPEN004 executable source changed")
    if frozen["offline_readiness"] != offline_readiness(frozen["source_sha256"]):
        raise ValueError("OPEN004 offline readiness changed")
    if frozen["prior_003_disposition"] != prior_003_disposition() or frozen["contingency_reserve_usd"] != str(CONTINGENCY_USD):
        raise ValueError("archived 003 disposition or frozen contingency changed")
    if frozen["runtime_pins"] != runtime_pins():
        raise ValueError("OPEN004 upstream runtime or deployed bytecode changed")
    reserve = reserve_worst_case(frozen["public_pricing_snapshot"], MAX_CALLS_PER_EPISODE,
                                 MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS)
    if (str(reserve) != frozen["worst_case_reserve_usd_per_episode"]
            or str(reserve * len(rows)) != frozen["worst_case_reserve_usd_full_block"]):
        raise ValueError("OPEN004 reservation changed")
    state = verify_ledger_ancestor(frozen["budget_at_freeze"])
    return {"status": "PASS", "assignment_manifest_sha256": assignment_sha,
            "planned_episodes": len(rows), "available_usd": state["available_usd"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "verify"))
    args = parser.parse_args()
    print(json.dumps(freeze() if args.command == "freeze" else verify(), sort_keys=True))


if __name__ == "__main__":
    main()
