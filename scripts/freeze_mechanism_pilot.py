#!/usr/bin/env python3
"""Freeze or revalidate separate funded-offer pilot 002; never call a model.

The single fixed output and permanent one-time lock prevent post-outcome seed
rerolls by this entry point. Pilot 001 remains archived with its failed and
pending rows; this new assignment cannot overwrite or replace it.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
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

from agent_economic_trust.mechanism_plan import (  # noqa: E402
    MAX_CALLS_PER_EPISODE, MAX_OUTPUT_TOKENS_PER_CALL,
    MAX_SERIALIZED_INPUT_BYTES_PER_CALL, PRIOR_PILOT_001, SCHEMA, canonical, digest,
    make_schedule, manifest, private_rows_commitment,
)
from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402
from agent_economic_trust.remote_pricing import pricing_snapshot, reserve_worst_case  # noqa: E402


PILOT_ROOT = ROOT / "artifacts/gates/MECHANISM_PILOT"
ASSIGNMENT_DIR = PILOT_ROOT / "assignment-002"
FREEZE_LOCK = PILOT_ROOT / "second-freeze.lock.json"
LEDGER = ROOT / "artifacts/budget/openrouter-ledger.jsonl"
PIN_MANIFEST = ROOT / "UPSTREAM_PINNED.json"
OFFLINE_REPORT = PILOT_ROOT / "offline-smoke-002/report.json"
FREEZE_LOCK_SCHEMA = "mechanism-one-time-freeze-lock-v2"
OFFLINE_REPORT_SCHEMA = "mechanism-offline-readiness-v2"
V1_ARCHIVE_TREE_SHA256 = "bf646b223e492f541d29ab80c33916edead9adfdc9248f0a370731b3c9f4faca"
V1_ARCHIVE_FILE_COUNT = 48
V1_ARCHIVE_DIRECTORIES = (
    "assignment-001", "runs-001", "offline-smoke-001",
    "invalidated-offline-smoke-pre-genesis-001",
)
V1_ARCHIVE_SINGLE_FILES = (
    "artifacts/gates/MECHANISM_PILOT/first-freeze.lock.json",
    "artifacts/gates/MECHANISM_PILOT/collection-001-after-stop.json",
    "docs/PILOT_001_STOPPED_INTERPRETATION.md",
)
ERC8183_COMMIT = "142e669c1fd318486a4628395b629f033654dd06"
ERC8183_SUBMODULES = {
    "lib/forge-std": "620536fa5277db4e3fd46772d5cbc1ea0696fb43",
    "lib/openzeppelin-contracts": "5fd1781b1454fd1ef8e722282f86f9293cacf256",
    "lib/openzeppelin-contracts-upgradeable": "7bf4727aacdbfaa0f36cbd664654d0c9e1dc52bf",
}

# These files are mandatory even while other agents are implementing them.
# No freeze is valid with a missing runtime, exporter, collector or native escrow.
MANDATORY_SOURCE_FILES = (
    "src/agent_economic_trust/mechanism_plan.py",
    "src/agent_economic_trust/mechanism_task.py",
    "src/agent_economic_trust/mechanism_native.py",
    "src/agent_economic_trust/mechanism_remote.py",
    "src/agent_economic_trust/mechanism_reporting.py",
    "scripts/freeze_mechanism_pilot.py",
    "scripts/run_mechanism_pilot.py",
    "scripts/collect_mechanism_pilot.py",
    "protocols/side_escrow/foundry.toml",
    "protocols/side_escrow/src/ProviderAuditorBonusEscrow.sol",
    "protocols/side_escrow/test/ProviderAuditorBonusEscrow.t.sol",
    "protocols/side_escrow/run_native_receipts.py",
    "protocols/side_escrow/verify_native_receipts.py",
    "protocols/side_escrow/test/test_receipt_verifier.py",
    "protocols/side_escrow/README.md",
    "tests/test_mechanism_plan.py",
    "tests/test_mechanism_task.py",
    "docs/PROSPECTIVE_FUNDED_OFFER_PILOT.md",
    "docs/PROSPECTIVE_FUNDED_OFFER_PILOT_002.md",
    "schemas/event.schema.json",
    "schemas/run_manifest.schema.json",
    "UPSTREAM_PINNED.json",
)


def sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"freeze source missing or not a regular file: {path}")
    return sha256(path.read_bytes()).hexdigest()


def v1_preservation() -> dict[str, Any]:
    """Require the entire committed pilot-001 archive to remain byte-for-byte.

    The fixed archive digest covers original and invalidated smoke, the frozen
    assignment, partial native/Inspect evidence, collection, lock and stopped
    interpretation. Unknown additions beneath these archival paths also fail.
    """
    archive: dict[str, str] = {}
    for name in V1_ARCHIVE_DIRECTORIES:
        directory = PILOT_ROOT / name
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError("pilot-001 archive directory is missing or unsafe")
        for path in sorted(directory.rglob("*")):
            if path.is_file() or path.is_symlink():
                archive[str(path.relative_to(ROOT))] = sha(path)
    for name in V1_ARCHIVE_SINGLE_FILES:
        archive[name] = sha(ROOT / name)
    if len(archive) != V1_ARCHIVE_FILE_COUNT or digest(archive) != V1_ARCHIVE_TREE_SHA256:
        raise ValueError("pilot-001 archived evidence changed or was added to")
    for name in ("assignment_manifest", "stopped_marker", "saved_inspect_log",
                 "partial_native_evidence", "collection"):
        ref = PRIOR_PILOT_001[name]
        if archive.get(ref["path"]) != ref["sha256"]:
            raise ValueError("pilot-001 primary evidence hash changed")
    prior_assignment = json.loads((PILOT_ROOT / "assignment-001/assignment_manifest.json").read_bytes())
    prior_lock = json.loads((PILOT_ROOT / "first-freeze.lock.json").read_bytes())
    stopped = json.loads((ROOT / PRIOR_PILOT_001["stopped_marker"]["path"]).read_bytes())
    collection = json.loads((ROOT / PRIOR_PILOT_001["collection"]["path"]).read_bytes())
    statuses = [row.get("status") for row in collection.get("rows", [])]
    if (prior_assignment.get("schema") != "mechanism-funded-offer-assignment-v1"
            or prior_assignment.get("planned_episodes") != 4
            or prior_lock != {
                "schema": "mechanism-one-time-freeze-lock-v1",
                "assignment": "artifacts/gates/MECHANISM_PILOT/assignment-001",
                "seed_commitment_sha256": prior_assignment.get("seed_commitment_sha256"),
            }
            or stopped.get("assignment_manifest_sha256")
            != PRIOR_PILOT_001["assignment_manifest"]["sha256"]
            or stopped.get("inspect_eval_sha256")
            != PRIOR_PILOT_001["saved_inspect_log"]["sha256"]
            or stopped.get("partial_native_sha256")
            != PRIOR_PILOT_001["partial_native_evidence"]["sha256"]
            or stopped.get("no_retry_or_substitution") is not True
            or collection.get("planned_episodes") != 4
            or collection.get("completed_episodes") != 0
            or collection.get("assignment_manifest_sha256")
            != PRIOR_PILOT_001["assignment_manifest"]["sha256"]
            or statuses.count("FAILED_OR_INCOMPLETE") != 1
            or statuses.count("PENDING") != 3):
        raise ValueError("pilot-001 one-time lock or four-row denominator changed")
    commit = subprocess.run(
        ["git", "cat-file", "-t", PRIOR_PILOT_001["source_commit"]],
        cwd=ROOT, capture_output=True, text=True, check=True, timeout=20,
    ).stdout.strip()
    if commit != "commit":
        raise ValueError("pilot-001 source commit is missing")
    return {
        "status": "PASS", "source_commit": PRIOR_PILOT_001["source_commit"],
        "archive_file_count": len(archive), "archive_tree_sha256": digest(archive),
    }


def archived_v1_replay() -> dict[str, Any]:
    """Replay four archived model boundaries through pinned Inspect, offline.

    Input and tool definitions are from the immutable stopped .eval. Inspect's
    actual reasoning-history resolver transforms the saved messages before the
    same byte counter used by the paid request guard. No inference is issued.
    """
    from inspect_ai.log import read_eval_log
    from inspect_ai.model import GenerateConfig, get_model
    from inspect_ai.model._model import resolve_reasoning_history
    from agent_economic_trust.remote import _safe_model_input_size

    if version("inspect_ai") != "0.3.263":
        raise ValueError("archived replay requires pinned Inspect 0.3.263")
    ref = PRIOR_PILOT_001["saved_inspect_log"]
    path = ROOT / ref["path"]
    if sha(path) != ref["sha256"]:
        raise ValueError("pilot-001 stopped Inspect log hash changed")
    log = read_eval_log(str(path), resolve_attachments=True)
    if (len(log.samples or []) != 1
            or log.eval.model != "openrouter/openai/gpt-5.6-sol"):
        raise ValueError("pilot-001 archived model route or sample changed")
    events = [event for event in log.samples[0].events if event.event == "model"]
    if (len(events) != 4
            or any(event.model != "openrouter/openai/gpt-5.6-sol"
                   or getattr(event.config, "reasoning_effort", None) != "high"
                   or getattr(event.config, "reasoning_history", None) is not None
                   for event in events)):
        raise ValueError("pilot-001 archived model events changed")
    config = GenerateConfig(reasoning_effort="high", reasoning_history="none",
                            max_tokens=MAX_OUTPUT_TOKENS_PER_CALL,
                            max_retries=0)
    model = get_model(
        "openrouter/openai/gpt-5.6-sol", config=config, memoize=False,
        base_url="https://openrouter.ai/api/v1", max_retries=0,
        stream=False, responses_api=False,
    )
    if model.api.force_reasoning_history() is not None:
        raise ValueError("provider overrides requested no-history replay")
    original = [_safe_model_input_size(event.input, event.tools) for event in events]
    no_history = [
        _safe_model_input_size(
            resolve_reasoning_history(event.input, config, model.api), event.tools,
        ) for event in events
    ]
    if (original != [8_834, 15_473, 20_506, 29_787]
            or no_history != [8_834, 10_870, 12_068, 13_930]
            or original[-1] <= MAX_SERIALIZED_INPUT_BYTES_PER_CALL
            or any(size >= MAX_SERIALIZED_INPUT_BYTES_PER_CALL for size in no_history)):
        raise ValueError("archived no-history replay no longer fits frozen byte cap")
    return {
        "status": "PASS", "saved_inspect_sha256": ref["sha256"],
        "model_id": "openai/gpt-5.6-sol", "reasoning_effort": "high",
        "reasoning_history": "none", "inspect_version": "0.3.263",
        "original_input_bytes": original, "no_history_input_bytes": no_history,
        "max_input_bytes": MAX_SERIALIZED_INPUT_BYTES_PER_CALL,
    }


def source_inventory() -> dict[str, str]:
    """Seal all first-party Python, pilot Solidity, schemas, and pin metadata.

    This intentionally includes unrelated first-party Python: a later source
    addition or edit invalidates the pilot preflight instead of silently
    changing a transitive import. An explicit new freeze is then required.
    """
    discovered = set(MANDATORY_SOURCE_FILES)
    discovered.update(str(path.relative_to(ROOT)) for path in
                      (ROOT / "src/agent_economic_trust").rglob("*.py") if path.is_file())
    discovered.update(str(path.relative_to(ROOT)) for path in
                      (ROOT / "scripts").rglob("*.py") if path.is_file())
    discovered.update(str(path.relative_to(ROOT)) for path in
                      (ROOT / "scripts").rglob("*.sh") if path.is_file())
    for extension in ("*.sol", "*.py", "*.toml"):
        discovered.update(str(path.relative_to(ROOT)) for path in
                          (ROOT / "protocols/side_escrow").rglob(extension) if path.is_file())
    discovered.update(str(path.relative_to(ROOT)) for path in
                      (ROOT / "schemas").rglob("*.json") if path.is_file())
    discovered.update(str(path.relative_to(ROOT)) for path in
                      (ROOT / "tests").rglob("test_*.py") if path.is_file())
    return {name: sha(ROOT / name) for name in sorted(discovered)}


def source_inventory_sha256() -> str:
    """Stable digest for the separate offline-readiness gate report."""
    return digest(source_inventory())


def _git_exact_clean(checkout: Path, expected: str) -> None:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=checkout,
                          capture_output=True, text=True, check=True, timeout=20).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=checkout,
                           capture_output=True, text=True, check=True, timeout=20).stdout.strip()
    if head != expected or dirty:
        raise ValueError(f"upstream checkout is not clean at pinned commit: {checkout}")


def upstream_pins() -> dict[str, Any]:
    pinned = json.loads(PIN_MANIFEST.read_bytes())
    sources = pinned["sources"]
    result: dict[str, Any] = {"pin_manifest_sha256": sha(PIN_MANIFEST)}
    for name, installed in (("orbit", "1.0.3"), ("inspect_ai", "0.3.263")):
        row = sources[name]
        _git_exact_clean(Path(row["source_checkout"]), row["commit"])
        if version(name) != installed:
            raise ValueError(f"installed {name} version differs from approved pin")
        result[name] = {
            "commit": row["commit"], "installed_version": installed,
            "wheel_sha256": (row["wheel_sha256"] if name == "orbit"
                             else row["installed_wheel_sha256"]),
        }
    checkout = WORKSPACE / "upstreams/erc8183"
    _git_exact_clean(checkout, ERC8183_COMMIT)
    for submodule, commit in ERC8183_SUBMODULES.items():
        _git_exact_clean(checkout / submodule, commit)
    result["erc8183"] = {
        "repository": "https://github.com/erc-8183/base-contracts",
        "commit": ERC8183_COMMIT,
        "submodule_commits": ERC8183_SUBMODULES,
        "chain_id": 31337,
        "transaction_tier": "NATIVE_LOCAL_PROTOCOL",
    }
    # Source and compiler pins jointly define what local bytecode can be built.
    # Hash native tools as well as the Solidity and Python source inventory.
    binaries = {
        "forge": WORKSPACE / ".tools/foundry/v1.8.5/forge",
        "cast": WORKSPACE / ".tools/foundry/v1.8.5/cast",
        "anvil": WORKSPACE / ".tools/foundry/v1.8.5/anvil",
        "solc": WORKSPACE / ".tools/solc/v0.8.28/solc",
    }
    result["native_toolchain_sha256"] = {name: sha(path) for name, path in binaries.items()}
    return result


def native_artifacts() -> dict[str, dict[str, str]]:
    """Pin exact compiled bytes that native controllers will deploy/read."""
    paths = {
        "provider_auditor_bonus_escrow": (
            ROOT / "protocols/side_escrow/out/ProviderAuditorBonusEscrow.sol/ProviderAuditorBonusEscrow.json"),
        "erc8183_core": WORKSPACE / "upstreams/erc8183/out/ERC8183.sol/ERC8183.json",
        "erc8183_proxy": WORKSPACE / "upstreams/erc8183/out/ERC1967Proxy.sol/ERC1967Proxy.json",
        "mock_usdc": WORKSPACE / "upstreams/erc8183/out/MockUSDC.sol/MockUSDC.json",
    }
    result: dict[str, dict[str, str]] = {}
    for name, path in paths.items():
        artifact = json.loads(path.read_bytes())
        if not isinstance(artifact.get("abi"), list):
            raise ValueError(f"native artifact has no ABI: {name}")
        bytecode = artifact.get("bytecode", {}).get("object")
        deployed = artifact.get("deployedBytecode", {}).get("object")
        if not isinstance(bytecode, str) or not bytecode.startswith("0x") \
                or not isinstance(deployed, str) or not deployed.startswith("0x"):
            raise ValueError(f"native artifact has no bytecode: {name}")
        result[name] = {
            "artifact_sha256": sha(path),
            "abi_sha256": digest(artifact["abi"]),
            "creation_bytecode_sha256": sha256(bytecode.encode("ascii")).hexdigest(),
            "runtime_bytecode_template_sha256": sha256(deployed.encode("ascii")).hexdigest(),
        }
    return result


def runtime_protocol_contract() -> dict[str, Any]:
    """Cross-check the planner's stated economics against executed adapters."""
    from agent_economic_trust import mechanism_task, mechanism_native
    from scripts import run_erc8183_local
    expected = {
        "arms": ["DIRECT_NEUTRAL", "DIRECT_OFFER_CAPABILITY"],
        "job_budget_minor_units": 20_000_000,
        "prepaid_auditor_fee_minor_units": 2_000_000,
        "provider_bonus_endowment_minor_units_after_fee": 5_000_000,
        "provider_initial_mint_minor_units": 7_000_000,
        "check_budget_units": 4,
        "check_cost_units": 1,
        "max_bonus_minor_units": 5_000_000,
        "max_model_calls_per_episode": MAX_CALLS_PER_EPISODE,
        "local_chain_id": 31337,
    }
    if (mechanism_task.ARM_NEUTRAL != expected["arms"][0]
            or mechanism_task.ARM_OFFER != expected["arms"][1]
            or mechanism_task.JOB_PAYOUT_MINOR != expected["job_budget_minor_units"]
            or run_erc8183_local.BUDGET != expected["job_budget_minor_units"]
            or mechanism_task.AUDIT_FEE_MINOR != expected["prepaid_auditor_fee_minor_units"]
            or mechanism_native.AUDIT_FEE_MINOR_UNITS != expected["prepaid_auditor_fee_minor_units"]
            or mechanism_native.PROVIDER_ENDOWMENT_MINOR_UNITS
            != expected["provider_bonus_endowment_minor_units_after_fee"]
            or mechanism_native.PROVIDER_INITIAL_MINT_MINOR_UNITS
            != expected["provider_initial_mint_minor_units"]
            or mechanism_task.CHECK_BUDGET_UNITS != expected["check_budget_units"]
            or mechanism_task.CHECK_COST_UNITS != expected["check_cost_units"]
            or mechanism_task.MAX_BONUS_MINOR != expected["max_bonus_minor_units"]
            or mechanism_task.MAX_MODEL_CALLS != expected["max_model_calls_per_episode"]
            or run_erc8183_local.CHAIN_ID != expected["local_chain_id"]):
        raise ValueError("mechanism planner and runtime economics differ")
    return expected


def _smoke_path(raw: Any) -> Path:
    """Resolve only regular evidence inside this pilot's fixed smoke folder."""
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise ValueError("offline smoke evidence path is malformed")
    relative = Path(raw)
    if relative.is_absolute() or any(part in (".", "..") for part in relative.parts):
        raise ValueError("offline smoke evidence path escapes the smoke folder")
    base = OFFLINE_REPORT.parent.resolve()
    path = OFFLINE_REPORT.parent / relative
    if not path.resolve().is_relative_to(base) or path.is_symlink() or not path.is_file():
        raise ValueError("offline smoke evidence path is missing or unsafe")
    return path


def _verify_scripted_smoke() -> dict[str, Any]:
    from agent_economic_trust.mechanism_smoke import verify_scripted_smoke
    return verify_scripted_smoke(OFFLINE_REPORT.parent)


def _verify_native_smoke(path: Path) -> dict[str, Any]:
    from agent_economic_trust.mechanism_native import verify_mechanism_native_evidence
    return verify_mechanism_native_evidence(path)


def _verify_offline_runner() -> dict[str, Any]:
    from scripts.run_mechanism_pilot import verify_offline_smoke
    return verify_offline_smoke(OFFLINE_REPORT.parent)


def offline_readiness(sources: dict[str, str]) -> dict[str, Any]:
    """Independently reopen all scripted and native local controls before freeze."""
    raw = OFFLINE_REPORT.read_bytes()
    report = json.loads(raw)
    replay = archived_v1_replay()
    if (raw != canonical(report) + b"\n"
            or report.get("schema") != OFFLINE_REPORT_SCHEMA
            or report.get("status") != "PASS"
            or report.get("independent_verifier") != "PASS"
            or report.get("paid_model_calls") != 0
            or report.get("archived_v1_replay") != replay
            or report.get("execution_tiers") != {
                "agent_behavior": "SCRIPTED_SIMULATION", "payment": "NATIVE_LOCAL_PROTOCOL"}
            or report.get("source_inventory_sha256") != digest(sources)):
        raise ValueError("offline readiness report or source seal is not PASS")
    scripted_ref = report.get("scripted_inspect_report")
    if (not isinstance(scripted_ref, dict)
            or scripted_ref.get("path") != "scripted_inspect_report.json"
            or sha(_smoke_path(scripted_ref["path"])) != scripted_ref.get("sha256")):
        raise ValueError("scripted Inspect report hash or path changed")
    scripted = _verify_scripted_smoke()
    if (scripted.get("status") != "PASS" or len(scripted.get("cells", [])) != 4
            or scripted.get("source_inventory_sha256") != digest(sources)
            or not isinstance(scripted.get("source_sha256"), dict)
            or any(sources.get(name) != file_hash
                   for name, file_hash in scripted["source_sha256"].items())):
        raise ValueError("saved scripted Inspect verifier did not pass four cells")
    native_refs = report.get("native_evidence")
    if not isinstance(native_refs, list) or len(native_refs) != 4:
        raise ValueError("native readiness lacks all four local control cells")
    seen: set[tuple[str, str]] = set()
    genesis_hashes: set[str] = set()
    wallet_addresses: set[str] = set()
    for ref in native_refs:
        if not isinstance(ref, dict):
            raise ValueError("native readiness row is malformed")
        quality, arm = ref.get("quality"), ref.get("arm")
        if quality not in {"GOOD", "BAD"} or arm not in {
                "DIRECT_NEUTRAL", "DIRECT_OFFER_CAPABILITY"} or (quality, arm) in seen:
            raise ValueError("native readiness cell is missing or duplicated")
        if ref.get("verified") != "PASS":
            raise ValueError("native readiness row has no independent PASS")
        seen.add((quality, arm))
        path = _smoke_path(ref.get("path"))
        if sha(path) != ref.get("sha256"):
            raise ValueError("native readiness raw receipt hash changed")
        saved = json.loads(path.read_bytes())
        chain = saved.get("chain", {})
        genesis = chain.get("genesis_block_hash")
        wallets = chain.get("distinct_wallet_addresses")
        if (not isinstance(genesis, str)
                or re.fullmatch(r"0x[0-9a-fA-F]{64}", genesis) is None
                or genesis.lower() in genesis_hashes
                or not isinstance(wallets, list) or len(wallets) != 8
                or any(not isinstance(address, str)
                       or re.fullmatch(r"0x[0-9a-fA-F]{40}", address) is None
                       or address.lower() in wallet_addresses for address in wallets)
                or len({address.lower() for address in wallets}) != 8):
            raise ValueError("offline native controls reuse genesis or wallet identities")
        genesis_hashes.add(genesis.lower())
        wallet_addresses.update(address.lower() for address in wallets)
        verified = _verify_native_smoke(path)
        verdict = "ACCEPT" if quality == "GOOD" else "REJECT"
        expected_bonus = arm == "DIRECT_OFFER_CAPABILITY"
        expected_bonus_status = (("RELEASED" if quality == "GOOD" else "REFUNDED")
                                 if expected_bonus else "UNFUNDED")
        if (saved.get("arm") != arm or verified.get("verdict") != verdict
                or verified.get("payment_tier") != "NATIVE_LOCAL_PROTOCOL"
                or verified.get("submission_tx_hash") is None
                or verified.get("audit_fee_payer_role") != "provider"
                or verified.get("audit_fee_minor_units") != 2_000_000
                or verified.get("provider_payout_minor_units")
                != (20_000_000 if quality == "GOOD" else 0)
                or (verified.get("bonus_amount_minor_units", 0) > 0) != expected_bonus
                or verified.get("bonus_status") != expected_bonus_status):
            raise ValueError("native readiness verdict, fee, bonus or payout differs")
    tests = report.get("tests_passed")
    if (not isinstance(tests, dict)
            or any(type(tests.get(key)) is not int or tests[key] <= 0
                   for key in ("python", "foundry"))):
        raise ValueError("offline readiness lacks passing Python and Foundry tests")
    reread = _verify_offline_runner()
    if reread != {"status": "PASS", "independent_verifier": "PASS",
                  "native_controls_verified": 4, "scripted_inspect_cells_verified": 4,
                  "paid_model_calls": 0}:
        raise ValueError("offline runner independent re-verification differs")
    return {"report_sha256": sha(OFFLINE_REPORT),
            "scripted_inspect_report_sha256": scripted_ref["sha256"],
            "archived_v1_replay": replay,
            "native_cells_verified": len(seen),
            "tests_passed": {key: tests[key] for key in ("python", "foundry")}}


def _new_file(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _budget_at_freeze() -> dict[str, Any]:
    before = BudgetLedger(LEDGER).snapshot()
    if before["blocked"] or before["cap_usd"] != "20" or before["unknown_run_ids"]:
        raise ValueError("shared USD 20 project ledger is blocked or changed")
    ledger_sha = sha(LEDGER)
    anchor_sha = sha(LEDGER.with_name(LEDGER.name + ".anchor"))
    after = BudgetLedger(LEDGER).snapshot()
    if (before["seq"], before["last_hash"]) != (after["seq"], after["last_hash"]):
        raise ValueError("ledger changed during pilot freeze")
    return {
        key: before[key] for key in (
            "cap_usd", "settled_spent_usd", "reserved_usd", "committed_usd",
            "available_usd", "blocked", "unknown_run_ids", "seq", "last_hash")
    } | {"ledger_file_sha256": ledger_sha, "ledger_anchor_sha256": anchor_sha}


def _verify_ledger_ancestor(frozen: dict[str, Any]) -> dict[str, Any]:
    now = BudgetLedger(LEDGER).snapshot()
    if now["cap_usd"] != "20" or now["blocked"] or now["seq"] < frozen["seq"]:
        raise ValueError("shared project ledger blocked, changed, or rolled back")
    lines = LEDGER.read_bytes().splitlines()
    if len(lines) <= frozen["seq"] or json.loads(lines[frozen["seq"]])["hash"] != frozen["last_hash"]:
        raise ValueError("frozen project ledger head is not a current chain ancestor")
    after = BudgetLedger(LEDGER).snapshot()
    if (now["seq"], now["last_hash"]) != (after["seq"], after["last_hash"]):
        raise ValueError("ledger changed during pilot verification")
    return after


def _core(seed_hex: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = make_schedule(seed_hex)
    return manifest(seed_hex, rows), [vars(row).copy() for row in rows]


def freeze(*, seed_hex: str | None = None) -> dict[str, Any]:
    """Create the one fixed pilot assignment only after full source/budget gates."""
    if FREEZE_LOCK.exists() or ASSIGNMENT_DIR.exists():
        raise FileExistsError("mechanism pilot already frozen or partially frozen; no reroll")
    seed_hex = secrets.token_hex(32) if seed_hex is None else seed_hex
    payload, private = _core(seed_hex)
    if private_rows_commitment(seed_hex, private) != payload["private_rows_hmac_sha256"]:
        raise AssertionError("private pilot row digest differs")
    preservation = v1_preservation()
    replay = archived_v1_replay()
    sources = source_inventory()  # fails until all prospective runtime files exist
    readiness = offline_readiness(sources)  # reopens four scripted and native controls
    runtime_contract = runtime_protocol_contract()
    pins = upstream_pins()
    artifacts = native_artifacts()
    pricing = pricing_snapshot()  # public catalog; no API key or model request
    per_episode = reserve_worst_case(
        pricing, MAX_CALLS_PER_EPISODE, MAX_SERIALIZED_INPUT_BYTES_PER_CALL,
        MAX_OUTPUT_TOKENS_PER_CALL)
    full_block = per_episode * Decimal(len(private))
    budget = _budget_at_freeze()
    if full_block > Decimal(budget["available_usd"]):
        raise ValueError("full four-episode worst-case reserve exceeds shared USD 20 headroom")
    payload.update({
        "source_sha256": sources,
        "v1_preservation": preservation,
        "archived_v1_replay": replay,
        "offline_readiness": readiness,
        "runtime_protocol_contract": runtime_contract,
        "upstream_pins": pins,
        "native_build_artifacts": artifacts,
        "public_pricing_snapshot": pricing,
        "budget_at_freeze": budget,
        "worst_case_reserve_usd_per_episode": format(per_episode, "f"),
        "worst_case_reserve_usd_four_episodes": format(full_block, "f"),
        "pricing_policy": (
            "Refresh the public catalog before each paid episode; reject any "
            "higher current four-episode/remaining reserve or unsupported model "
            "parameter. Reserve before network access. Zero automatic retries."
        ),
        "execution_tiers": {"model": "REAL_LLM_REMOTE_APPROVED",
                            "transactions": "NATIVE_LOCAL_PROTOCOL"},
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
    return {
        "assignment_manifest_sha256": sha(ASSIGNMENT_DIR / "assignment_manifest.json"),
        "planned_episodes": 4,
        "worst_case_reserve_usd_four_episodes": format(full_block, "f"),
        "ledger_available_usd": budget["available_usd"],
        "model_calls": 0, "native_transactions": 0,
    }


def verify() -> dict[str, Any]:
    """Revalidate frozen inputs without changing the seed, assignment, or ledger."""
    if not FREEZE_LOCK.is_file() or not ASSIGNMENT_DIR.is_dir():
        raise ValueError("one-time pilot freeze is missing")
    lock = json.loads(FREEZE_LOCK.read_bytes())
    seed_hex = (ASSIGNMENT_DIR / "seed.hex").read_text(encoding="ascii").strip()
    expected, private = _core(seed_hex)
    payload = json.loads((ASSIGNMENT_DIR / "assignment_manifest.json").read_bytes())
    saved_private = json.loads((ASSIGNMENT_DIR / "private_episodes.json").read_bytes())
    if (payload.get("schema") != SCHEMA or saved_private != private
            or any(payload.get(key) != value for key, value in expected.items())
            or payload.get("private_rows_hmac_sha256") != private_rows_commitment(seed_hex, saved_private)
            or lock != {
                "schema": FREEZE_LOCK_SCHEMA,
                "assignment": str(ASSIGNMENT_DIR.relative_to(ROOT)),
                "seed_commitment_sha256": expected["seed_commitment_sha256"],
            }):
        raise ValueError("pilot seed, assignment, or one-time lock changed")
    if payload.get("v1_preservation") != v1_preservation():
        raise ValueError("pilot-001 archived evidence changed")
    if payload.get("archived_v1_replay") != archived_v1_replay():
        raise ValueError("pilot-001 no-history replay changed")
    sources = source_inventory()
    if payload.get("source_sha256") != sources:
        raise ValueError("pilot first-party source/data changed")
    if payload.get("offline_readiness") != offline_readiness(sources):
        raise ValueError("pilot offline scripted/native readiness changed")
    if payload.get("runtime_protocol_contract") != runtime_protocol_contract():
        raise ValueError("pilot runtime economic contract changed")
    if payload.get("upstream_pins") != upstream_pins():
        raise ValueError("pilot ORBIT/Inspect/native protocol pin changed")
    if payload.get("native_build_artifacts") != native_artifacts():
        raise ValueError("pilot native compiled artifact or ABI changed")
    pricing = payload.get("public_pricing_snapshot")
    per_episode = reserve_worst_case(
        pricing, MAX_CALLS_PER_EPISODE, MAX_SERIALIZED_INPUT_BYTES_PER_CALL,
        MAX_OUTPUT_TOKENS_PER_CALL)
    full_block = per_episode * Decimal(4)
    if (payload.get("worst_case_reserve_usd_per_episode") != format(per_episode, "f")
            or payload.get("worst_case_reserve_usd_four_episodes") != format(full_block, "f")):
        raise ValueError("frozen model pricing reserve changed")
    current = _verify_ledger_ancestor(payload["budget_at_freeze"])
    return {
        "assignment_manifest_sha256": sha(ASSIGNMENT_DIR / "assignment_manifest.json"),
        "planned_episodes": 4,
        "ledger_available_usd": current["available_usd"],
        "ledger_blocked": current["blocked"],
        "source_pin_status": "PASS",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "verify"))
    args = parser.parse_args()
    try:
        result = freeze() if args.command == "freeze" else verify()
    except Exception as exc:
        # Dependency/provider messages might contain URLs or sensitive data.
        print(f"mechanism pilot stopped: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
