#!/usr/bin/env python3
"""One-time, offline-only freeze and read-only verification for pilot 003.

The freeze is intentionally unavailable until runtime, collector, native debit,
scripted and native smoke evidence, source pins, and full-block USD headroom
exist. This script never makes a paid model call or a native transaction.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = str(WORKSPACE / ".local" / "share")
os.environ["XDG_CACHE_HOME"] = str(WORKSPACE / ".cache")
os.environ["XDG_CONFIG_HOME"] = str(WORKSPACE / ".config")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from agent_economic_trust.debit_pilot_plan import (  # noqa: E402
    BONUS_MINOR_UNITS, CHECK_DEBIT_MINOR_UNITS, DIRECT_MESSAGE,
    TASK_TOKEN_LIMIT, EVAL_TOKEN_LIMIT,
    DebitPilotEpisode, MAX_CALLS_PER_EPISODE, MAX_OUTPUT_TOKENS_PER_CALL,
    MAX_SERIALIZED_INPUT_BYTES_PER_CALL, PRIOR_PILOTS, SCHEMA, canonical,
    digest, make_schedule, manifest, private_rows_commitment,
)
from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402
from agent_economic_trust.remote_pricing import pricing_snapshot, reserve_worst_case  # noqa: E402
from scripts import freeze_mechanism_pilot as previous_freezer  # noqa: E402


PILOT_ROOT = ROOT / "artifacts/gates/MECHANISM_PILOT"
ASSIGNMENT_DIR = PILOT_ROOT / "assignment-003"
FREEZE_LOCK = PILOT_ROOT / "third-freeze.lock.json"
OFFLINE_REPORT = PILOT_ROOT / "offline-smoke-003/report.json"
LEDGER = ROOT / "artifacts/budget/openrouter-ledger.jsonl"
FREEZE_LOCK_SCHEMA = "mechanism-one-time-freeze-lock-v3"
OFFLINE_REPORT_SCHEMA = "mechanism-debit-offline-readiness-v1"

PILOT_002_DIRECTORIES = ("assignment-002", "offline-smoke-002", "runs-002")
PILOT_002_SINGLE_FILES = (
    "artifacts/gates/MECHANISM_PILOT/second-freeze.lock.json",
    "artifacts/gates/MECHANISM_PILOT/collection-002-after-episode-01.json",
    "artifacts/gates/MECHANISM_PILOT/collection-002-after-episode-02.json",
    "artifacts/gates/MECHANISM_PILOT/collection-002-after-episode-03.json",
    "artifacts/gates/MECHANISM_PILOT/collection-002-final.json",
    "docs/PILOT_002_RESULTS_AND_INTERPRETATION.md",
)
PILOT_002_PRIMARY_SHA256 = {
    "artifacts/gates/MECHANISM_PILOT/assignment-002/assignment_manifest.json":
        "f0aa8ba2a33bc6e95d9055b7cc551ac0f72b9edcfe85674ee078a93b3ffda95a",
    "artifacts/gates/MECHANISM_PILOT/collection-002-final.json":
        "76ab896d20652efb59ef0e5d126171aab82f2bf3dbf5c66cd1b4bd8aeceb2530",
    "artifacts/gates/MECHANISM_PILOT/second-freeze.lock.json":
        "7ae450ab597d3623b5884dd7674f71fc17c461166d19c01db7a0fa696154d1a8",
    "artifacts/gates/MECHANISM_PILOT/offline-smoke-002/report.json":
        "884102abd0c763769bfe9554c35b15cfe3c63022a4505cf33f4d03ff0c69b141",
    "docs/PILOT_002_RESULTS_AND_INTERPRETATION.md":
        "f5c9069efd73a6168dffe150c869f355b4190b61e69b671918fa2900f2684ce3",
}

MANDATORY_SOURCE_FILES = (
    "src/agent_economic_trust/debit_pilot_plan.py",
    "src/agent_economic_trust/debit_pilot_remote.py",
    "src/agent_economic_trust/debit_pilot_reporting.py",
    "src/agent_economic_trust/mechanism_task.py",
    "src/agent_economic_trust/mechanism_native.py",
    "scripts/freeze_debit_pilot.py",
    "scripts/run_debit_pilot.py",
    "scripts/collect_debit_pilot.py",
    "tests/test_debit_pilot_plan.py",
    "tests/test_debit_pilot_remote.py",
    "tests/test_debit_pilot_reporting.py",
    "docs/PROSPECTIVE_DEBIT_PILOT_003.md",
    "docs/BUDGET_AUTHORIZATION_2026-10-15.md",
    "UPSTREAM_PINNED.json",
    "schemas/event.schema.json",
    "schemas/run_manifest.schema.json",
)


def sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"freeze source missing or unsafe: {path}")
    return sha256(path.read_bytes()).hexdigest()


def _git_commit_exists(commit: str) -> None:
    result = subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"],
                            cwd=ROOT, capture_output=True, check=False, timeout=20)
    if result.returncode:
        raise ValueError("archived pilot source commit is unavailable")


def archive_preservation() -> dict[str, Any]:
    """Independently seal complete 001 and 002 archives and their denominators."""
    v1 = previous_freezer.v1_preservation()
    if (v1.get("archive_file_count") != PRIOR_PILOTS["pilot_001"]["archive_file_count"]
            or v1.get("archive_tree_sha256") != PRIOR_PILOTS["pilot_001"]["archive_tree_sha256"]):
        raise ValueError("pilot 001 archive changed")
    archive: dict[str, str] = {}
    for name in PILOT_002_DIRECTORIES:
        directory = PILOT_ROOT / name
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError("pilot 002 archive directory is missing or unsafe")
        for path in sorted(directory.rglob("*")):
            if path.is_file() or path.is_symlink():
                archive[str(path.relative_to(ROOT))] = sha(path)
    for name in PILOT_002_SINGLE_FILES:
        archive[name] = sha(ROOT / name)
    expected = PRIOR_PILOTS["pilot_002"]
    if (len(archive) != expected["archive_file_count"]
            or digest(archive) != expected["archive_tree_sha256"]
            or any(archive.get(name) != value for name, value in PILOT_002_PRIMARY_SHA256.items())):
        raise ValueError("pilot 002 archived evidence changed or was added to")
    assignment = json.loads((PILOT_ROOT / "assignment-002/assignment_manifest.json").read_bytes())
    collection = json.loads((PILOT_ROOT / "collection-002-final.json").read_bytes())
    prior_rows = collection.get("rows")
    if (assignment.get("planned_episodes") != 4 or not isinstance(prior_rows, list)
            or len(prior_rows) != 4
            or {row.get("episode_id") for row in prior_rows}
            != {row.get("episode_id") for row in assignment.get("rows", [])}
            or any(row.get("status") != "COMPLETE" for row in prior_rows)):
        raise ValueError("pilot 002 complete 4/4 assigned denominator changed")
    for ref in PRIOR_PILOTS.values():
        _git_commit_exists(ref["source_commit"])
    return {"pilot_001": v1,
            "pilot_002": {"status": "PASS", "source_commit": expected["source_commit"],
                          "archive_file_count": len(archive),
                          "archive_tree_sha256": digest(archive),
                          "complete_assigned_rows": 4,
                          "assignment_manifest_sha256": archive[
                              "artifacts/gates/MECHANISM_PILOT/assignment-002/assignment_manifest.json"],
                          "collection_sha256": archive[
                              "artifacts/gates/MECHANISM_PILOT/collection-002-final.json"]}}


def source_inventory() -> dict[str, str]:
    """Hash mandatory 003 closure and all first-party executable source."""
    discovered = set(MANDATORY_SOURCE_FILES)
    for directory, patterns in (("src/agent_economic_trust", ("*.py",)),
                                ("scripts", ("*.py", "*.sh")),
                                ("tests", ("test_*.py",)),
                                ("schemas", ("*.json",)),
                                ("protocols/side_escrow", ("*.sol", "*.py", "*.toml"))):
        base = ROOT / directory
        for pattern in patterns:
            discovered.update(str(path.relative_to(ROOT)) for path in base.rglob(pattern)
                              if path.is_file() or path.is_symlink())
    return {name: sha(ROOT / name) for name in sorted(discovered)}


def source_inventory_sha256() -> str:
    return digest(source_inventory())


def runtime_protocol_contract() -> dict[str, Any]:
    """Check that executable economics and post text match the assignment."""
    from inspect import signature
    from agent_economic_trust import mechanism_native, mechanism_task
    from agent_economic_trust.w10_factorial import frozen_fixtures

    fixtures = {item.fixture_id: item for item in frozen_fixtures()}
    factual = {
        name: mechanism_task.factual_message(fixture.case, fixture.artifact)
        for name, fixture in fixtures.items()
        if name in {"delivery-bad", "delivery-good"}
    }
    if (factual != {"delivery-bad": DIRECT_MESSAGE, "delivery-good": DIRECT_MESSAGE}
            or mechanism_task.CHECK_DEBIT_MINOR != CHECK_DEBIT_MINOR_UNITS
            or mechanism_native.CHECK_DEBIT_MINOR != CHECK_DEBIT_MINOR_UNITS
            or mechanism_task.MAX_BONUS_MINOR != BONUS_MINOR_UNITS
            or mechanism_task.AUDIT_FEE_MINOR != 2_000_000
            or mechanism_task.JOB_PAYOUT_MINOR != 20_000_000
            or "check_debit_condition" not in signature(mechanism_native.MechanismNative).parameters
            or "charge_check" not in signature(mechanism_task.build_mechanism_task).parameters
            or signature(mechanism_task.build_mechanism_task).parameters[
                "task_token_limit"].default != 16_000
            or TASK_TOKEN_LIMIT != 50_000 or EVAL_TOKEN_LIMIT != 60_000
            or not callable(getattr(mechanism_native.MechanismNative, "charge_check", None))):
        raise ValueError("pilot 003 executable debit, bonus, payout or direct text differs")
    return {"direct_message_sha256": sha256(DIRECT_MESSAGE.encode()).hexdigest(),
            "check_debit_minor_units": CHECK_DEBIT_MINOR_UNITS,
            "check_debit_sink_role": "outsider",
            "assigned_bonus_minor_units": BONUS_MINOR_UNITS,
            "prepaid_auditor_fee_minor_units": 2_000_000,
            "job_budget_minor_units": 20_000_000,
            "task_token_limit": TASK_TOKEN_LIMIT,
            "eval_token_limit": EVAL_TOKEN_LIMIT}


def _evidence_path(raw: Any) -> Path:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise ValueError("offline evidence path is malformed")
    relative = Path(raw)
    if relative.is_absolute() or any(part in (".", "..") for part in relative.parts):
        raise ValueError("offline evidence path escapes readiness directory")
    base = OFFLINE_REPORT.parent.resolve()
    path = OFFLINE_REPORT.parent / relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(base):
        raise ValueError("offline evidence path is missing or unsafe")
    return path


def offline_readiness(sources: dict[str, str]) -> dict[str, Any]:
    """Reopen saved zero-paid-call smoke, including real D1 wallet receipts."""
    raw = OFFLINE_REPORT.read_bytes()
    report = json.loads(raw)
    if (raw != canonical(report) + b"\n"
            or report.get("schema") != OFFLINE_REPORT_SCHEMA
            or report.get("status") != "PASS"
            or report.get("paid_model_calls") != 0
            or report.get("source_inventory_sha256") != digest(sources)):
        raise ValueError("pilot 003 offline readiness report or source seal is not PASS")
    scripted = report.get("scripted_controls")
    native = report.get("native_evidence")
    positive = report.get("positive_control")
    tests = report.get("tests_passed")
    if (not isinstance(scripted, list) or len(scripted) < 8
            or not isinstance(native, list) or len(native) < 2
            or not isinstance(positive, dict)
            or not isinstance(tests, dict)
            or any(type(tests.get(k)) is not int or tests[k] <= 0
                   for k in ("python", "foundry", "native_positive"))):
        raise ValueError("pilot 003 offline controls or tests are incomplete")
    for entry in (*scripted, *native, positive):
        if (not isinstance(entry, dict) or entry.get("verified") != "PASS"
                or sha(_evidence_path(entry.get("path"))) != entry.get("sha256")):
            raise ValueError("pilot 003 offline evidence hash or verdict changed")
    required_cells = {
        f"BAD-DIRECT-B{b}-D{d}" for b in (0, 1) for d in (0, 1)
    } | {f"GOOD-DIRECT-B0-D{d}" for d in (0, 1)} | {
        f"BAD-NO_CHANNEL-B0-D{d}" for d in (0, 1)}
    if {entry.get("cell") for entry in scripted} != required_cells:
        raise ValueError("scripted readiness lacks exact eight treatment/control cells")
    if {entry.get("check_debit") for entry in native} != {0, 1}:
        raise ValueError("native readiness lacks actual D0 and D1 controls")
    if (positive.get("cell") != "BAD-DIRECT-B1-D1"
            or positive.get("path") != "positive-control/native/evidence.json"
            or positive.get("scope")
            != "STRUCTURAL_PAYMENT_CONTROL_NOT_ASSIGNED_OUTCOME"
            or positive.get("deliberate_wrong_verdict") != "ACCEPT"):
        raise ValueError("false-approval positive control is absent")
    # Runner and native verifiers must reopen the raw evidence, not merely trust
    # the PASS field or a hash. A missing verifier is a freeze blocker.
    from scripts.run_debit_pilot import verify_offline_smoke
    independently_verified = verify_offline_smoke(OFFLINE_REPORT.parent)
    if (independently_verified.get("status") != "PASS"
            or independently_verified.get("paid_model_calls") != 0
            or independently_verified.get("scripted_cells_verified") != 8
            or independently_verified.get("native_debit_conditions_verified") != 2
            or independently_verified.get("positive_control_verified") is not True):
        raise ValueError("independent debit offline verifier did not pass")
    return {"report_sha256": sha(OFFLINE_REPORT),
            "scripted_cells_verified": 8,
            "native_debit_conditions_verified": 2,
            "positive_control_verified": True,
            "tests_passed": {key: tests[key]
                             for key in ("python", "foundry", "native_positive")}}


def _budget_at_freeze() -> dict[str, Any]:
    before = BudgetLedger(LEDGER).snapshot()
    if before["blocked"] or before["cap_usd"] != "50" or before["unknown_run_ids"]:
        raise ValueError("shared lifetime USD 50 ledger is blocked or changed")
    ledger_sha = sha(LEDGER)
    anchor_sha = sha(LEDGER.with_name(LEDGER.name + ".anchor"))
    after = BudgetLedger(LEDGER).snapshot()
    if (before["seq"], before["last_hash"]) != (after["seq"], after["last_hash"]):
        raise ValueError("ledger changed during pilot 003 freeze")
    return {key: before[key] for key in (
        "cap_usd", "settled_spent_usd", "reserved_usd", "committed_usd",
        "available_usd", "blocked", "unknown_run_ids", "seq", "last_hash"
    )} | {"ledger_file_sha256": ledger_sha, "ledger_anchor_sha256": anchor_sha}


def _verify_ledger_ancestor(frozen: dict[str, Any]) -> dict[str, Any]:
    now = BudgetLedger(LEDGER).snapshot()
    if (now["cap_usd"] != "50" or now["seq"] < frozen["seq"]
            or now["blocked"] or now["unknown_run_ids"]):
        raise ValueError("shared USD 50 ledger blocked, changed, or rolled back")
    lines = LEDGER.read_bytes().splitlines()
    if (len(lines) <= frozen["seq"]
            or json.loads(lines[frozen["seq"]])["hash"] != frozen["last_hash"]):
        raise ValueError("frozen ledger head is not current chain ancestor")
    return now


def _new_file(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def load_assignment(directory: Path) -> tuple[dict[str, Any], str, tuple[DebitPilotEpisode, ...]]:
    """Recompute the full private schedule from the one archived seed."""
    directory = Path(directory)
    seed_hex = (directory / "seed.hex").read_text(encoding="ascii").strip()
    rows = make_schedule(seed_hex)
    expected = manifest(seed_hex, rows)
    path = directory / "assignment_manifest.json"
    frozen = json.loads(path.read_bytes())
    private = json.loads((directory / "private_episodes.json").read_bytes())
    if (private != [asdict(row) for row in rows]
            or any(frozen.get(key) != value for key, value in expected.items())
            or frozen.get("private_rows_hmac_sha256")
            != private_rows_commitment(seed_hex, private)):
        raise ValueError("pilot 003 seed, private oracle or assignment changed")
    lock_path = directory.parent / "third-freeze.lock.json"
    if not lock_path.is_file():
        raise ValueError("pilot 003 one-time freeze lock is missing")
    lock = json.loads(lock_path.read_bytes())
    if lock != {"schema": FREEZE_LOCK_SCHEMA,
                "assignment": str(directory.relative_to(ROOT)),
                "seed_commitment_sha256": expected["seed_commitment_sha256"]}:
        raise ValueError("pilot 003 one-time freeze lock changed")
    return frozen, sha(path), rows


def freeze(*, seed_hex: str | None = None) -> dict[str, Any]:
    """Write assignment 003 exactly once after every offline and budget gate."""
    if FREEZE_LOCK.exists() or ASSIGNMENT_DIR.exists():
        raise FileExistsError("pilot 003 already frozen or partially frozen; no reroll")
    seed_hex = secrets.token_hex(32) if seed_hex is None else seed_hex
    rows = make_schedule(seed_hex)
    payload = manifest(seed_hex, rows)
    private = [asdict(row) for row in rows]
    archive = archive_preservation()
    old_ids: set[str] = set()
    for version in ("001", "002"):
        prior = json.loads((PILOT_ROOT / f"assignment-{version}/assignment_manifest.json").read_bytes())
        for row in prior["rows"]:
            old_ids.update((row["episode_id"], row["pair_id"], row["obligation_id"],
                            row["provider_id"], row["auditor_id"]))
    if any(identifier in old_ids for row in rows for identifier in
           (row.episode_id, row.pair_id, row.obligation_id, row.provider_id, row.auditor_id)):
        raise ValueError("pilot 003 identity collides with archived pilot")
    sources = source_inventory()
    readiness = offline_readiness(sources)
    runtime_contract = runtime_protocol_contract()
    pins = previous_freezer.upstream_pins()
    artifacts = previous_freezer.native_artifacts()
    pricing = pricing_snapshot()
    per_episode = reserve_worst_case(pricing, MAX_CALLS_PER_EPISODE,
                                     MAX_SERIALIZED_INPUT_BYTES_PER_CALL,
                                     MAX_OUTPUT_TOKENS_PER_CALL)
    full_block = per_episode * Decimal(len(rows))
    budget = _budget_at_freeze()
    if full_block > Decimal(budget["available_usd"]):
        raise ValueError("full twelve-episode worst-case reserve exceeds shared USD 50 headroom")
    payload.update({
        "archive_preservation": archive,
        "source_sha256": sources,
        "offline_readiness": readiness,
        "runtime_protocol_contract": runtime_contract,
        "upstream_pins": pins,
        "native_build_artifacts": artifacts,
        "public_pricing_snapshot": pricing,
        "budget_at_freeze": budget,
        "worst_case_reserve_usd_per_episode": format(per_episode, "f"),
        "worst_case_reserve_usd_twelve_episodes": format(full_block, "f"),
        "pricing_policy": "Refresh public rates and reserve all remaining worst-case calls before each paid episode; zero automatic retries.",
    })
    PILOT_ROOT.mkdir(parents=True, exist_ok=True)
    _new_file(FREEZE_LOCK, canonical({
        "schema": FREEZE_LOCK_SCHEMA,
        "assignment": str(ASSIGNMENT_DIR.relative_to(ROOT)),
        "seed_commitment_sha256": payload["seed_commitment_sha256"],
    }) + b"\n")
    ASSIGNMENT_DIR.mkdir(mode=0o700, exist_ok=False)
    _new_file(ASSIGNMENT_DIR / "seed.hex", (seed_hex + "\n").encode("ascii"))
    _new_file(ASSIGNMENT_DIR / "private_episodes.json", canonical(private) + b"\n")
    _new_file(ASSIGNMENT_DIR / "assignment_manifest.json", canonical(payload) + b"\n")
    return {"assignment_manifest_sha256": sha(ASSIGNMENT_DIR / "assignment_manifest.json"),
            "planned_episodes": len(rows),
            "worst_case_reserve_usd_twelve_episodes": format(full_block, "f"),
            "ledger_available_usd": budget["available_usd"],
            "model_calls": 0, "native_transactions": 0}


def verify() -> dict[str, Any]:
    """Read-only preflight against the immutable assignment and current ledger."""
    if not FREEZE_LOCK.is_file() or not ASSIGNMENT_DIR.is_dir():
        raise ValueError("pilot 003 one-time freeze is missing")
    frozen, assignment_sha, rows = load_assignment(ASSIGNMENT_DIR)
    if frozen.get("archive_preservation") != archive_preservation():
        raise ValueError("pilot 001 or 002 archived evidence changed")
    sources = source_inventory()
    if frozen.get("source_sha256") != sources:
        raise ValueError("pilot 003 source or data changed")
    if frozen.get("offline_readiness") != offline_readiness(sources):
        raise ValueError("pilot 003 offline readiness changed")
    if frozen.get("runtime_protocol_contract") != runtime_protocol_contract():
        raise ValueError("pilot 003 runtime economic contract changed")
    if frozen.get("upstream_pins") != previous_freezer.upstream_pins():
        raise ValueError("pilot 003 ORBIT, Inspect or native protocol pin changed")
    if frozen.get("native_build_artifacts") != previous_freezer.native_artifacts():
        raise ValueError("pilot 003 compiled native artifact changed")
    per_episode = reserve_worst_case(
        frozen["public_pricing_snapshot"], MAX_CALLS_PER_EPISODE,
        MAX_SERIALIZED_INPUT_BYTES_PER_CALL, MAX_OUTPUT_TOKENS_PER_CALL)
    if (frozen.get("worst_case_reserve_usd_per_episode") != format(per_episode, "f")
            or frozen.get("worst_case_reserve_usd_twelve_episodes")
            != format(per_episode * Decimal(len(rows)), "f")):
        raise ValueError("pilot 003 frozen cost reserve changed")
    budget = _verify_ledger_ancestor(frozen["budget_at_freeze"])
    return {"assignment_manifest_sha256": assignment_sha,
            "planned_episodes": len(rows),
            "ledger_available_usd": budget["available_usd"],
            "source_pin_status": "PASS"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "verify"))
    args = parser.parse_args()
    try:
        result = freeze() if args.command == "freeze" else verify()
    except Exception as exc:
        print(f"pilot 003 stopped: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
