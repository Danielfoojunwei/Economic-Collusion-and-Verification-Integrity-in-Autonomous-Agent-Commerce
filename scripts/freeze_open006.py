#!/usr/bin/env python3
"""One-time OPEN006 assignment and read-only source/budget preflight."""
from __future__ import annotations

import argparse
import ast
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
import json
from importlib.metadata import version
import subprocess
import shutil
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from agent_economic_trust.open006_plan import (  # noqa: E402
    MAX_CALLS_PER_EPISODE, MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS, canonical,
    digest, make_schedule, manifest,
)
from agent_economic_trust.open006_plan import CANONICAL_LEDGER_PATH as PROJECT_LEDGER_PATH  # noqa: E402
from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402
from agent_economic_trust.remote_pricing import pricing_snapshot, reserve_worst_case  # noqa: E402

GATE_ROOT = ROOT / "artifacts/gates/OPEN006"
ASSIGNMENT_DIR = GATE_ROOT / "assignment-invoice-001"
FREEZE_LOCK = GATE_ROOT / "invoice-first-freeze.lock.json"
OFFLINE_REPORT = GATE_ROOT / "offline-invoice/report.json"
LEDGER = PROJECT_LEDGER_PATH
CONTINGENCY_USD = Decimal("2")
PRIOR_004_COMMIT = "9fd4cad"
PRIOR_005_COMMIT = "b4f72e9"


def sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("source/evidence path must be a regular file")
    return sha256(path.read_bytes()).hexdigest()


SOURCE_SEEDS = (
    "src/agent_economic_trust/__init__.py",
    "src/agent_economic_trust/open006_plan.py", "src/agent_economic_trust/open006_remote.py",
    "src/agent_economic_trust/open006_reporting.py", "src/agent_economic_trust/open005_task.py",
    "src/agent_economic_trust/open005_native.py", "src/agent_economic_trust/open005_native_verifier.py",
    "scripts/freeze_open006.py", "scripts/run_open006.py", "scripts/run_open006_offline.py",
    "scripts/collect_open006.py", "scripts/verify_open006_billing_regression.py", "tests/test_open006_runner.py", "tests/test_open005_amendment.py",
    # runpy uses literal paths: include those dynamic control dependencies.
    "tests/test_open004_task.py",
)
SOURCE_ASSETS = (
    "AGENTS.md", "UPSTREAM_PINNED.json", "docs/PROSPECTIVE_HETEROGENEOUS_SERVICES_006.md",
    "docs/PROSPECTIVE_INVOICE_AMENDMENT_005.md", "scripts/run_x402_local.mjs",
    "contracts/x402/TestEIP3009Token.sol",
)


def source_inventory() -> dict[str, str]:
    """Seal explicit 006 entrypoints and their complete first-party import closure.

    This does not collect unrelated task families. Relative, absolute and lazy
    imports are all parsed; missing first-party modules/assets fail closed.
    Dynamic runpy control files and non-Python protocol assets are explicit.
    """
    pending = list(SOURCE_SEEDS)
    files = set(SOURCE_ASSETS)
    def module_for(name: str) -> str:
        parts = Path(name).with_suffix("").parts
        return ".".join(parts[1:] if parts[0] == "src" else parts)
    def path_for(module: str) -> str | None:
        if module.startswith("agent_economic_trust"):
            relative = Path("src") / Path(*module.split("."))
        elif module == "scripts" or module.startswith("scripts."):
            relative = Path(*module.split("."))
        elif module == "tests" or module.startswith("tests."):
            relative = Path(*module.split("."))
        else:
            return None
        for candidate in (relative.with_suffix(".py"), relative / "__init__.py"):
            if (ROOT / candidate).is_file():
                return str(candidate)
        return None
    while pending:
        name = pending.pop()
        if name in files:
            continue
        path = ROOT / name
        sha(path)  # Missing or symlinked entrypoints are never silently omitted.
        files.add(name)
        module = module_for(name)
        for node in ast.walk(ast.parse(path.read_bytes(), filename=name)):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                prefix = module.split(".")[:-node.level] if node.level else []
                base = ".".join([*prefix, *([node.module] if node.module else [])])
                imported = [base, *(base + "." + alias.name for alias in node.names)]
                # A relative first-party import must resolve even when its
                # symbols are attributes rather than modules.
                first_party = node.level or base.startswith(("agent_economic_trust.", "scripts.", "tests."))
                if first_party and not path_for(base):
                    raise ValueError("unresolved first-party source import: " + base)
            else:
                continue
            for imported_module in imported:
                dependency = path_for(imported_module)
                if dependency is not None and dependency not in files:
                    pending.append(dependency)
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


def prior_004_disposition() -> dict:
    """Reopen the entire 004 archive against its immutable Git commit."""
    def git(*args: str) -> bytes:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                              check=True, timeout=30).stdout
    commit = git("rev-parse", PRIOR_004_COMMIT + "^{commit}").decode().strip()
    listed = git("ls-tree", "-r", "--name-only", commit).decode().splitlines()
    def archived(name: str) -> bool:
        return (name.startswith("artifacts/gates/OPEN004/")
                or "open004" in Path(name).name.lower()
                or name in {"docs/PROSPECTIVE_HETEROGENEOUS_SERVICES_004.md",
                            "src/agent_economic_trust/x402_invoice_adapter.py",
                            "src/agent_economic_trust/x402_invoice_verifier.py",
                            "scripts/run_x402_local.mjs", "contracts/x402/TestEIP3009Token.sol"})
    names = sorted(name for name in listed if archived(name))
    if not names or not any(name.endswith("STOPPED.json") for name in names):
        raise ValueError("004 immutable stop archive is missing")
    expected = {name: sha256(git("show", commit + ":" + name)).hexdigest() for name in names}
    if any(sha(ROOT / name) != value for name, value in expected.items()):
        raise ValueError("004 archived source or evidence changed from fixed commit")
    archive_dir = ROOT / "artifacts/gates/OPEN004"
    actual_artifacts = {str(p.relative_to(ROOT)) for p in archive_dir.rglob("*") if p.is_file()}
    expected_artifacts = {name for name in names if name.startswith("artifacts/gates/OPEN004/")}
    if actual_artifacts != expected_artifacts:
        raise ValueError("004 archived artifacts added or removed; no retry/pooling")
    collection = json.loads((archive_dir / "collection-invoice-001-after-first-stop.json").read_bytes())
    rows = collection["rows"]
    if (collection["planned_episodes"] != 8 or collection["completed_episodes"] != 0
            or len(rows) != 8 or sum(r["status"] == "PENDING" for r in rows) != 7
            or sum(r["status"] == "FAILED_OR_INCOMPLETE" for r in rows) != 1):
        raise ValueError("004 archived assigned denominator changed")
    stopped = next(r for r in rows if r["status"] == "FAILED_OR_INCOMPLETE")
    stop_path = archive_dir / "runs-invoice-001/episodes" / stopped["episode_id"] / "STOPPED.json"
    stop = json.loads(stop_path.read_bytes())
    if stop.get("no_retry_or_substitution") is not True or stop.get("budget_state") != "SETTLED":
        raise ValueError("004 immutable stop or billing disposition missing")
    archived_ledger = git("show", commit + ":artifacts/budget/openrouter-ledger.jsonl")
    current = LEDGER.read_bytes()
    if not current.startswith(archived_ledger):
        raise ValueError("current lifetime ledger does not descend from 004 archived ledger")
    state = _ledger_snapshot()
    if state["runs"].get(stop["ledger_run_id"], {}).get("status") != "SETTLED":
        raise ValueError("004 stopped model episode is not settled in shared ledger")
    return {"status": "IRREVOCABLY_STOPPED_NO_RETRY_NO_POOLING", "archive_commit": commit,
            "file_count": len(expected), "tree_sha256": digest(expected),
            "archive_sha256": expected, "complete": 0, "failed_or_incomplete": 1, "pending": 7,
            "remaining_004_obligation_reserve_usd": "0",
            "archived_ledger_prefix_sha256": sha256(archived_ledger).hexdigest()}

def prior_005_disposition() -> dict:
    """Reopen the entire 005 archive against its immutable Git commit."""
    def git(*args: str) -> bytes:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                              check=True, timeout=30).stdout
    commit = git("rev-parse", PRIOR_005_COMMIT + "^{commit}").decode().strip()
    listed = git("ls-tree", "-r", "--name-only", commit).decode().splitlines()
    def archived(name: str) -> bool:
        return (name.startswith("artifacts/gates/OPEN005/")
                or "open005" in Path(name).name.lower()
                or name in {"docs/PROSPECTIVE_HETEROGENEOUS_SERVICES_005.md",
                            "src/agent_economic_trust/x402_invoice_adapter.py",
                            "src/agent_economic_trust/x402_invoice_verifier.py",
                            "scripts/run_x402_local.mjs", "contracts/x402/TestEIP3009Token.sol"})
    assignment_path = "artifacts/gates/OPEN005/assignment-invoice-001/assignment_manifest.json"
    archived_assignment = json.loads(git("show", commit + ":" + assignment_path))
    shared_sources = archived_assignment.get("source_sha256")
    if not isinstance(shared_sources, dict) or not shared_sources:
        raise ValueError("005 archived assignment has no transitive source inventory")
    if any(not isinstance(name, str) or name not in listed
           or Path(name).is_absolute() or ".." in Path(name).parts
           for name in shared_sources):
        raise ValueError("005 archived assignment source path is missing or unsafe")
    names = sorted({name for name in listed if archived(name)} | set(shared_sources))
    if not names or not any(name.endswith("STOPPED.json") for name in names):
        raise ValueError("005 immutable stop archive is missing")
    expected = {name: sha256(git("show", commit + ":" + name)).hexdigest() for name in names}
    if any(expected[name] != value for name, value in shared_sources.items()):
        raise ValueError("005 archived assignment source hash differs from pinned Git bytes")
    if any(sha(ROOT / name) != value for name, value in expected.items()):
        raise ValueError("005 archived source or evidence changed from fixed commit")
    archive_dir = ROOT / "artifacts/gates/OPEN005"
    actual_artifacts = {str(p.relative_to(ROOT)) for p in archive_dir.rglob("*") if p.is_file()}
    expected_artifacts = {name for name in names if name.startswith("artifacts/gates/OPEN005/")}
    if actual_artifacts != expected_artifacts:
        raise ValueError("005 archived artifacts added or removed; no retry/pooling")
    collection = json.loads((archive_dir / "collection-invoice-001-after-first-stop.json").read_bytes())
    rows = collection["rows"]
    if (collection["planned_episodes"] != 8 or collection["completed_episodes"] != 0
            or len(rows) != 8 or sum(r["status"] == "PENDING" for r in rows) != 7
            or sum(r["status"] == "FAILED_OR_INCOMPLETE" for r in rows) != 1):
        raise ValueError("005 archived assigned denominator changed")
    stopped = next(r for r in rows if r["status"] == "FAILED_OR_INCOMPLETE")
    stop_path = archive_dir / "runs-invoice-001/episodes" / stopped["episode_id"] / "STOPPED.json"
    stop = json.loads(stop_path.read_bytes())
    if stop.get("no_retry_or_substitution") is not True or stop.get("budget_state") != "SETTLED":
        raise ValueError("005 immutable stop or billing disposition missing")
    archived_ledger = git("show", commit + ":artifacts/budget/openrouter-ledger.jsonl")
    current = LEDGER.read_bytes()
    if not current.startswith(archived_ledger):
        raise ValueError("current lifetime ledger does not descend from 005 archived ledger")
    state = _ledger_snapshot()
    if state["runs"].get(stop["ledger_run_id"], {}).get("status") != "SETTLED":
        raise ValueError("005 stopped model episode is not settled in shared ledger")
    return {"status": "IRREVOCABLY_STOPPED_NO_RETRY_NO_POOLING", "archive_commit": commit,
            "file_count": len(expected), "tree_sha256": digest(expected),
            "archived_assignment_source_file_count": len(shared_sources),
            "archive_sha256": expected, "complete": 0, "failed_or_incomplete": 1, "pending": 7,
            "remaining_005_obligation_reserve_usd": "0",
            "archived_ledger_prefix_sha256": sha256(archived_ledger).hexdigest()}


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
            raise ValueError("OPEN006 upstream checkout differs from clean commit")
        return head
    for name, expected_version in (("orbit", "1.0.3"), ("inspect_ai", "0.3.263")):
        pin = pins[name]
        if version(name) != expected_version:
            raise ValueError("OPEN006 installed orchestration version differs")
        output[name] = {"commit": clean(Path(pin["source_checkout"]), pin["commit"]),
                        "version": expected_version}
    from scripts.run_erc8183_local import ANVIL, FORGE, CAST, SOLC, UPSTREAM, PIN, SUBMODULE_PINS
    output["erc8183"] = clean(UPSTREAM, PIN)
    output["erc8183_submodules"] = {name: clean(UPSTREAM / name, commit)
                                        for name, commit in SUBMODULE_PINS.items()}
    output["native_toolchain"] = {name: sha(path) for name, path in
                                   (("anvil", ANVIL), ("forge", FORGE), ("cast", CAST), ("solc", SOLC))}
    x402_anvil = Path(os.environ.get("X402_ANVIL", "/workspace/.tools/foundry/v1.8.5/anvil"))
    x402_solc = Path(os.environ.get("X402_SOLC", "/workspace/.tools/solc/v0.8.28/solc"))
    if sha(x402_anvil) != sha(ANVIL) or sha(x402_solc) != sha(SOLC):
        raise ValueError("x402 native toolchain differs from frozen ERC8183 toolchain")
    node = shutil.which("node")
    if node is None:
        raise ValueError("x402 Node runtime missing")
    output["node_runtime_sha256"] = sha(Path(node).resolve())
    output["erc8183_builds"] = {name: sha(UPSTREAM / "out" / (name + ".sol") / (name + ".json"))
                                for name in ("ERC8183", "ERC1967Proxy", "MockUSDC")}
    sdk = Path(os.environ.get("X402_SDK_ROOT", "/workspace/upstreams/x402/typescript"))
    output["x402"] = clean(sdk.parent, "e95b06661e1a2a8a9a21fce34cc28b9934834650")
    dist_files = list((sdk / "packages").rglob("dist/esm/**/*.mjs"))
    if not dist_files:
        raise ValueError("OPEN006 x402 built SDK missing")
    output["x402_runtime_sha256"] = {str(p.relative_to(sdk)): sha(p) for p in sorted(dist_files)}
    return output


def offline_readiness(sources: dict[str, str]) -> dict:
    """Reopen every saved control rather than trusting a report PASS string."""
    report = json.loads(OFFLINE_REPORT.read_bytes())
    if (report.get("schema") != "open006-offline-invoice-v1"
            or report.get("paid_model_calls") != 0
            or report.get("source_inventory_sha256") != digest(sources)):
        raise ValueError("OPEN006 offline source seal or report differs")
    from agent_economic_trust.open006_reporting import verify_offline_controls
    verified = verify_offline_controls(OFFLINE_REPORT.parent, report)
    if verified.get("status") != "PASS":
        raise ValueError("OPEN006 offline controls failed independent verification")
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
    if lock != {"schema": "open006-one-time-freeze-v1",
                "assignment_manifest_sha256": sha(path),
                "seed_commitment_sha256": expected["seed_commitment_sha256"]}:
        raise ValueError("one-time OPEN006 freeze lock changed")
    return frozen, sha(path), rows


def freeze(*, seed_hex: str | None = None) -> dict:
    if FREEZE_LOCK.exists() or ASSIGNMENT_DIR.exists():
        raise FileExistsError("OPEN006 already or partially frozen; no reroll")
    seed_hex = secrets.token_hex(32) if seed_hex is None else seed_hex
    rows = make_schedule(seed_hex)
    payload = manifest(seed_hex, rows)
    sources = source_inventory()
    offline = offline_readiness(sources)
    runtime = runtime_pins()
    prior = prior_003_disposition()
    prior004 = prior_004_disposition()
    prior005 = prior_005_disposition()
    prices = pricing_snapshot()
    reserve = reserve_worst_case(prices, MAX_CALLS_PER_EPISODE, MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS)
    state = _ledger_snapshot()
    if reserve * len(rows) + CONTINGENCY_USD > Decimal(state["available_usd"]):
        raise ValueError("full OPEN006 block worst-case reserve exceeds lifetime headroom")
    payload.update(source_sha256=sources, offline_readiness=offline, runtime_pins=runtime, prior_003_disposition=prior, prior_004_disposition=prior004, prior_005_disposition=prior005,
                   contingency_reserve_usd=str(CONTINGENCY_USD),
                   public_pricing_snapshot=prices,
                   budget_at_freeze={k: state[k] for k in ("seq", "last_hash", "cap_usd", "available_usd")},
                   worst_case_reserve_usd_per_episode=str(reserve),
                   worst_case_reserve_usd_full_block=str(reserve * len(rows)))
    GATE_ROOT.mkdir(parents=True, exist_ok=True)
    raw = canonical(payload) + b"\n"
    # Claim the one-time lock before making any assignment files. A partial
    # failure permanently stops this assignment rather than permitting rerolls.
    _new(FREEZE_LOCK, canonical({"schema": "open006-one-time-freeze-v1",
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
        raise ValueError("OPEN006 executable source changed")
    if frozen["offline_readiness"] != offline_readiness(frozen["source_sha256"]):
        raise ValueError("OPEN006 offline readiness changed")
    if frozen["prior_005_disposition"] != prior_005_disposition():
        raise ValueError("005 fixed archive source/evidence or ledger ancestry changed")
    if frozen["prior_004_disposition"] != prior_004_disposition():
        raise ValueError("004 fixed archive source/evidence or ledger ancestry changed")
    if frozen["prior_003_disposition"] != prior_003_disposition() or frozen["contingency_reserve_usd"] != str(CONTINGENCY_USD):
        raise ValueError("archived 003 disposition or frozen contingency changed")
    if frozen["runtime_pins"] != runtime_pins():
        raise ValueError("OPEN006 upstream runtime or deployed bytecode changed")
    reserve = reserve_worst_case(frozen["public_pricing_snapshot"], MAX_CALLS_PER_EPISODE,
                                 MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS)
    if (str(reserve) != frozen["worst_case_reserve_usd_per_episode"]
            or str(reserve * len(rows)) != frozen["worst_case_reserve_usd_full_block"]):
        raise ValueError("OPEN006 reservation changed")
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
