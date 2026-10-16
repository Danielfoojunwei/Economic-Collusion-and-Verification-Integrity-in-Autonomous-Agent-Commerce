#!/usr/bin/env python3
"""Second AP2 LIVE source/assignment gate; default action is read-only.

This module has no remote-model call. `--prepare` creates a fresh assignment
only after the saved native/Inspect controls, source pins, prices and entire
four-row USD reserve pass. Do not run `--prepare` during implementation review.
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
import shutil
import subprocess
import tempfile

from agent_economic_trust.ap2_live_v2_plan import (
    CANONICAL_LEDGER_PATH, CONTINGENCY_USD, MAX_CALLS_PER_EPISODE,
    MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS, MODEL_ID, canonical, make_schedule,
    manifest)
from agent_economic_trust.ap2_live_budget import (
    MPP006_STOPPED_RUN_ID, UNASSIGNED_ACCOUNT_RESIDUAL_USD,
    mpp006_contingent_exposure, required_headroom)
from agent_economic_trust.remote_budget import BudgetLedger
from agent_economic_trust.remote_pricing import pricing_snapshot, reserve_worst_case
from agent_economic_trust.ap2_live_fixture import invoice_case
from agent_economic_trust.ap2_live_purchase import validate_ap2_authorization
from scripts.verify_ap2_live_offline import verify as verify_offline


ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "artifacts/gates/AP2_LIVE_V2"
ASSIGNMENT = GATE / "assignment-001"
LOCK = GATE / "first-freeze.lock.json"
OFFLINE = ROOT / "artifacts/prospective/ap2-live-audit-purchase/offline-006"
READINESS = ROOT / "artifacts/prospective/ap2-live-audit-purchase-v2/readiness-001.json"
PRIOR_READINESS = ROOT / "artifacts/prospective/ap2-live-audit-purchase/readiness-008.json"
PRIOR_GATE = ROOT / "artifacts/gates/AP2_LIVE"
PRIOR_ASSIGNMENT_SHA256 = "299834e068dcfe2db0f5c398c61e1b67fc0615b819e822ecc4c506bd979460a0"
PRIOR_STOPPED_SHA256 = "73734f00ea7319095b9e39202fa447e40b15f2eb6dea6ac3ff2693244b48dec2"
PRIOR_COLLECTION_SHA256 = "b97f9e9b53446aafd5d6f9f8044fa55185a94487c6df04c575e4bdf6fde383ea"
PRIOR_STOPPED_EPISODE_ID = "ap2live-f8f08bd97a348e352fb6e02f"
AP2_PYTHON = Path("/workspace/upstreams/ap2-w15/.venv/bin/python")
AP2_PIN = "b4587ac1d055888a73b4b21750973cffba961793"
ERC8183_PIN = "142e669c1fd318486a4628395b629f033654dd06"
NEW_SOURCE = (
    "docs/PROSPECTIVE_AP2_AUDIT_PURCHASE_LIVE_002.md",
    "scripts/collect_ap2_live_v2.py",
    "scripts/freeze_ap2_live_v2.py",
    "scripts/run_ap2_live_v2.py",
    "src/agent_economic_trust/ap2_live_v2_plan.py",
    "src/agent_economic_trust/ap2_live_v2_remote.py",
    "tests/test_ap2_live_v2.py",
)


def file_sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"source or evidence is not a regular file: {path}")
    return sha256(path.read_bytes()).hexdigest()


def source_inventory() -> dict[str, str]:
    """Seal unchanged v1/AP2/native import closure and new v2 behavior."""
    from scripts.freeze_ap2_live import source_inventory as inherited
    result = inherited()
    for name in NEW_SOURCE:
        result[name] = file_sha(ROOT / name)
    return dict(sorted(result.items()))


def _readiness(inventory: dict[str, str]) -> dict:
    saved = json.loads(READINESS.read_text())
    prior = json.loads(PRIOR_READINESS.read_text())
    changed = tuple(sorted(name for name in set(inventory) | set(prior["source_sha256"])
                           if inventory.get(name) != prior["source_sha256"].get(name)))
    if (saved.get("schema") != "ap2-live-v2-offline-readiness-v1"
            or saved.get("status") != "PASS"
            or saved.get("source_sha256") != inventory
            or saved.get("source_inventory_sha256") != sha256(canonical(inventory)).hexdigest()
            or saved.get("prior_readiness_sha256") != file_sha(PRIOR_READINESS)
            or saved.get("source_change_scope") != "AP2_V2_BILLING_AND_CHANNEL_EXPOSURE_CORRECTION"
            or saved.get("changed_source_paths") != list(changed)
            or changed != tuple(sorted(NEW_SOURCE))
            or saved.get("offline_report_sha256") != file_sha(OFFLINE / "report.json")
            or saved.get("public_input_equality_verified") is not True
            or saved.get("max_serialized_model_input_bytes", MAX_INPUT_BYTES + 1)
            > MAX_INPUT_BYTES or saved.get("paid_model_calls") != 0
            or saved.get("forwarded_cap_bytes") != MAX_INPUT_BYTES
            or saved.get("verified_rows") != 4
            or saved.get("prior_disposition") != prior_disposition()):
        raise ValueError("AP2 LIVE v2 offline readiness/source does not match current freeze")
    return saved


def prior_disposition() -> dict:
    """Prove the original assigned denominator remains 0/1/3 and archived."""
    from scripts.collect_ap2_live import collect as collect_prior
    from scripts.freeze_ap2_live import verify as verify_prior
    assignment = PRIOR_GATE / "assignment-001/assignment_manifest.json"
    stopped = PRIOR_GATE / "runs-001/episodes" / PRIOR_STOPPED_EPISODE_ID / "STOPPED.json"
    collection = PRIOR_GATE / "collection-001-after-first-stop.json"
    if (file_sha(assignment) != PRIOR_ASSIGNMENT_SHA256
            or file_sha(stopped) != PRIOR_STOPPED_SHA256
            or file_sha(collection) != PRIOR_COLLECTION_SHA256):
        raise ValueError("original AP2 assignment, stop or collection bytes differ")
    if verify_prior()[1] != PRIOR_ASSIGNMENT_SHA256:
        raise ValueError("original AP2 frozen assignment cannot be verified")
    saved = json.loads(collection.read_text())
    current = collect_prior()
    if ({k: v for k, v in current.items() if k != "shared_ledger_seq"}
            != {k: v for k, v in saved.items() if k != "shared_ledger_seq"}
            or (saved.get("completed_episodes"), saved.get("stopped_episodes"),
                saved.get("pending_episodes")) != (0, 1, 3)
            or saved["rows"][0]["episode_id"] != PRIOR_STOPPED_EPISODE_ID):
        raise ValueError("original AP2 denominator or stopped row differs")
    return {"assignment_sha256": PRIOR_ASSIGNMENT_SHA256,
            "stopped_sha256": PRIOR_STOPPED_SHA256,
            "collection_sha256": PRIOR_COLLECTION_SHA256,
            "completed_episodes": 0, "stopped_episodes": 1,
            "pending_episodes": 3, "original_study_restarted": False}


def _clean_upstream(path: Path, expected: str) -> None:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path,
                          capture_output=True, text=True, check=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=path,
                           capture_output=True, text=True, check=True).stdout.strip()
    if head != expected or dirty:
        raise ValueError("official protocol checkout is dirty or differs from pin")


def _budget_gate() -> tuple[dict, Decimal, dict, dict]:
    state = BudgetLedger(CANONICAL_LEDGER_PATH).snapshot()
    if (state["cap_usd"] != "50" or state["blocked"]
            or state["unknown_run_ids"] or state["reserved_usd"] != "6.30784"):
        raise ValueError("shared USD50 ledger is blocked or another study holds a reserve")
    exposure = mpp006_contingent_exposure(state)
    prices = pricing_snapshot(MODEL_ID)
    reserve = reserve_worst_case(prices, MAX_CALLS_PER_EPISODE,
                                 MAX_INPUT_BYTES, MAX_OUTPUT_TOKENS)
    if required_headroom(reserve, 4) > Decimal(state["available_usd"]):
        raise ValueError("AP2 LIVE block and contingency exceed USD50 headroom net of MPP006 hold")
    return prices, reserve, state, exposure


def _issue(path: Path, row, cross_obligation: str, artifact_digest: str) -> dict:
    subprocess.run([
        str(AP2_PYTHON), "-m", "scripts.ap2_live_authorization", "issue",
        "--obligation", row.obligation_id,
        "--artifact-digest", artifact_digest,
        "--cross-obligation", cross_obligation,
        "--output", str(path),
    ], cwd=ROOT, env={"PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1"},
       capture_output=True, text=True, check=True, timeout=45)
    return json.loads(path.read_text())


def prepare() -> dict:
    """Write one assignment exactly once; no model or payment transaction."""
    if ASSIGNMENT.exists() or LOCK.exists():
        raise ValueError("AP2 LIVE v2 assignment already exists; no reroll")
    prior = prior_disposition()
    if verify_offline(OFFLINE)["status"] != "PASS":
        raise ValueError("saved four-cell offline control failed")
    _clean_upstream(Path("/workspace/upstreams/ap2-w15"), AP2_PIN)
    _clean_upstream(Path("/workspace/upstreams/erc8183"), ERC8183_PIN)
    inventory = source_inventory()
    _readiness(inventory)
    prices, reserve, state, exposure = _budget_gate()
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()
    if subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                      cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip():
        raise ValueError("tracked source must be committed before freeze")
    seed = secrets.token_hex(32)
    rows = make_schedule(seed)
    frozen = manifest(seed, rows)
    frozen["status"] = "FROZEN_NOT_EXECUTED"
    frozen.update({
        "prior_ap2_live_v1_disposition": prior,
        "version_reason": "prospective Decimal billing and ORBIT channel-exposure correction after v1 technical STOPPED row",
        "source_commit": head, "source_sha256": inventory,
        "source_inventory_sha256": sha256(canonical(inventory)).hexdigest(),
        "offline_report_sha256": file_sha(OFFLINE / "report.json"),
        "offline_readiness_sha256": file_sha(READINESS),
        "public_pricing_snapshot": prices,
        "worst_case_reserve_usd_per_episode": str(reserve),
        "worst_case_reserve_usd_full_block": str(reserve * 4),
        "contingency_reserve_usd": str(CONTINGENCY_USD),
        "prior_mpp006_contingent_exposure": exposure,
        "prior_mpp006_ledger_run_at_freeze": state["runs"][MPP006_STOPPED_RUN_ID],
        "ledger_reserved_at_freeze_usd": state["reserved_usd"],
        "unassigned_account_residual_usd": str(UNASSIGNED_ACCOUNT_RESIDUAL_USD),
        "required_headroom_usd": str(required_headroom(reserve, 4)),
        "ledger_seq_at_freeze": state["seq"],
        "ledger_hash_at_freeze": state["last_hash"],
        "ap2_upstream_commit": AP2_PIN,
        "erc8183_upstream_commit": ERC8183_PIN,
    })
    GATE.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".ap2-assignment-", dir=GATE))
    try:
        (temp / "authorizations").mkdir()
        (temp / "seed.hex").write_text(seed + "\n")
        os.chmod(temp / "seed.hex", 0o600)
        (temp / "private_rows.json").write_text(
            json.dumps([asdict(row) for row in rows], sort_keys=True, indent=2) + "\n")
        os.chmod(temp / "private_rows.json", 0o600)
        authorizations = {}
        for row in rows:
            _, artifact = invoice_case(row.truth)
            cross = next(other.obligation_id for other in rows
                         if other.obligation_id != row.obligation_id)
            name = row.episode_id + ".json"
            path = temp / "authorizations" / name
            record = _issue(path, row, cross, artifact.digest())
            authorizations[row.episode_id] = {
                "path": "authorizations/" + name,
                "sha256": file_sha(path),
                "trusted_issuer_public_sha256": record["trusted_issuer_public_sha256"],
                "authorization_reference": record["authorization_reference"],
                "issued_at": record["issued_at"], "expires_at": record["expires_at"],
            }
        if len({x["authorization_reference"] for x in authorizations.values()}) != 4:
            raise ValueError("AP2 mandate reference replay across assigned rows")
        frozen["authorization_records"] = authorizations
        manifest_path = temp / "assignment_manifest.json"
        manifest_path.write_bytes(canonical(frozen) + b"\n")
        manifest_sha = file_sha(manifest_path)
        temp.rename(ASSIGNMENT)
        LOCK.write_bytes(canonical({"schema": "ap2-live-v2-first-freeze-v1",
                                    "assignment_manifest_sha256": manifest_sha,
                                    "source_inventory_sha256": frozen["source_inventory_sha256"],
                                    "source_commit": head,
                                    "paid_model_calls": 0}) + b"\n")
    except BaseException:
        if temp.exists():
            shutil.rmtree(temp)
        raise
    return {"status": "FROZEN_NOT_EXECUTED", "assignment_manifest_sha256": manifest_sha,
            "full_reserve_usd": str(reserve * 4), "paid_model_calls": 0}


def verify() -> tuple[dict, str, tuple]:
    """Read-only source, seed, signed-token archive and assignment verification."""
    frozen_path = ASSIGNMENT / "assignment_manifest.json"
    _clean_upstream(Path("/workspace/upstreams/ap2-w15"), AP2_PIN)
    _clean_upstream(Path("/workspace/upstreams/erc8183"), ERC8183_PIN)
    frozen = json.loads(frozen_path.read_bytes())
    digest = file_sha(frozen_path)
    lock = json.loads(LOCK.read_bytes())
    current_inventory = source_inventory()
    _readiness(current_inventory)
    if (lock["assignment_manifest_sha256"] != digest
            or lock.get("schema") != "ap2-live-v2-first-freeze-v1"
            or frozen.get("schema") != "ap2-live-prospective-assignment-v2"
            or frozen.get("prior_ap2_live_v1_disposition") != prior_disposition()
            or frozen.get("version_reason") !=
               "prospective Decimal billing and ORBIT channel-exposure correction after v1 technical STOPPED row"
            or frozen["source_sha256"] != current_inventory
            or frozen["source_inventory_sha256"] != sha256(
                canonical(frozen["source_sha256"])).hexdigest()
            or frozen["ap2_upstream_commit"] != AP2_PIN
            or frozen["erc8183_upstream_commit"] != ERC8183_PIN
            or frozen["offline_report_sha256"] != file_sha(OFFLINE / "report.json")
            or frozen["offline_readiness_sha256"] != file_sha(READINESS)
            or frozen["required_headroom_usd"] != str(required_headroom(
                Decimal(frozen["worst_case_reserve_usd_per_episode"]), 4))
            or frozen["unassigned_account_residual_usd"] != str(UNASSIGNED_ACCOUNT_RESIDUAL_USD)
            or frozen["ledger_reserved_at_freeze_usd"] != "6.30784"
            or frozen["prior_mpp006_contingent_exposure"] != mpp006_contingent_exposure(
                {"contingent_run_ids": [MPP006_STOPPED_RUN_ID],
                 "runs": {MPP006_STOPPED_RUN_ID:
                    frozen["prior_mpp006_ledger_run_at_freeze"]}})):
        raise ValueError("AP2 LIVE frozen source, offline gate or assignment differs")
    if verify_offline(OFFLINE)["status"] != "PASS":
        raise ValueError("AP2 LIVE saved offline controls differ")
    seed = (ASSIGNMENT / "seed.hex").read_text().strip()
    rows = make_schedule(seed)
    if (frozen["public_rows"] != manifest(seed, rows)["public_rows"]
            or json.loads((ASSIGNMENT / "private_rows.json").read_text())
            != [asdict(row) for row in rows]
            or len(frozen["authorization_records"]) != 4):
        raise ValueError("AP2 LIVE seeded rows or denominator differ")
    references = set()
    for row in rows:
        info = frozen["authorization_records"][row.episode_id]
        path = ASSIGNMENT / info["path"]
        record = json.loads(path.read_text())
        if (file_sha(path) != info["sha256"]
                or record["trusted_issuer_public_sha256"] != info["trusted_issuer_public_sha256"]
                or record["authorization_reference"] != info["authorization_reference"]
                or record["purchase_intent"]["invoice_obligation_id"] != row.obligation_id):
            raise ValueError("AP2 LIVE frozen signed authorization differs")
        _, artifact = invoice_case(row.truth)
        validate_ap2_authorization(
            path, obligation_id=row.obligation_id,
            artifact_digest=artifact.digest(),
            issuer_public_sha256=info["trusted_issuer_public_sha256"],
            archive_at=record["issued_at"])
        references.add(record["authorization_reference"])
    if len(references) != 4:
        raise ValueError("AP2 LIVE signed mandate reference replay")
    return frozen, digest, rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    result = prepare() if args.prepare else {"status": "VERIFIED",
        "assignment_manifest_sha256": verify()[1]}
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
