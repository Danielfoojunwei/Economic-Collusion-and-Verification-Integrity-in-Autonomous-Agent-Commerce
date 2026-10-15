#!/usr/bin/env python3
"""Read-only PARTIAL014 readiness and explicit one-time assignment freeze.

The independent source review, native scripted controls, predecessor closure,
full five-row headroom and canonical checkout are all required before freezing.
No command here invokes a remote model or native payment controller.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from agent_economic_trust.partial014_budget import (  # noqa: E402
    FEE014_PROVISIONAL_EVIDENCE_SHA, FEE014_STOPPED_RUN_ID,
    FEE015_ASSIGNMENT_SHA, FEE015_SETTLED,
    exact_prior_holds, same_usd_amount)
from agent_economic_trust.partial014_plan import (  # noqa: E402
    CANONICAL_LEDGER, ROWS, canonical, digest, make_schedule, per_row_reserve,
    prospective_manifest, required_headroom)
from agent_economic_trust.mpp005_plan import canonical_project_root  # noqa: E402
from agent_economic_trust.mpp008_pricing import pricing_snapshots  # noqa: E402
from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402

GATE = ROOT / "artifacts/gates/ERC8183_PARTIAL_CLAIM014"
ASSIGNMENT = GATE / "assignment-001"
LOCK = GATE / "first-freeze.lock.json"
CLEARANCE = GATE / "cross-study-clearance-001.json"
REVIEW = ROOT / "artifacts/prospective/ERC8183_PARTIAL_CLAIM014/source-review-003.json"
OFFLINE = ROOT / "artifacts/prospective/ERC8183_PARTIAL_CLAIM014/offline-native-001"
FEE013_GATE = ROOT / "artifacts/gates/ERC8183_FEE013"
FEE013_FINAL = FEE013_GATE / "predecessor-collection-final.json"
FEE013_REVIEW = FEE013_GATE / "independent-results-review-final.json"
FEE014_GATE = ROOT / "artifacts/gates/ERC8183_FEE014"
FEE014_ASSIGNMENT_SHA = "d6409ff93bcbd1332aba4ad90b19953c045e9a3136383ea6fa30fe76ece3bfed"
FEE014_COLLECTION = FEE014_GATE / "collection-002-after-first-stop.json"
FEE014_COLLECTION_SHA = "e929867f0e327bba854be8a53d8949ee097a1677adda4e7eb96f98d9ce38444f"
FEE014_FORENSICS = FEE014_GATE / "forensics-first-stop-001/report.json"
FEE014_FORENSICS_SHA = "3ab4ad292c0021124bc396c70400731100e866aa4749c667c2a9c1850b8aaa38"
FEE014_BILLING = ROOT / "artifacts/budget/fee014-first-stop-contingent-001/evidence.json"
FEE014_BILLING_REVIEW = ROOT / "artifacts/budget/fee014-first-stop-contingent-001/independent-review.json"
FEE014_BILLING_REVIEW_SHA = "a4b11d2c7181d76138827b50f318b82f8e2fcde3f368eb42928a11c017c2ec0a"
FEE014_CONTINGENT_LEDGER_SHA = "74ee7d2e4feab7734a88e9730fc29963702018cbe6f94895a4e90d78129532f1"
FEE014_FIRST_EPISODE = "fee014-dcf583877ebb1ae684f45d82"
FEE014_FIRST_RECORD_SHA = "52157834b5bb0e28d2f8bf87513ed532593d0c0e89742d9ddb897983242621d1"
FEE014_STOP_EPISODE = "fee014-deb758472e05bb8622e9a1d6"
FEE014_STOP_ROW = FEE014_GATE / "runs-001/episodes" / FEE014_STOP_EPISODE
FEE014_STOP_SHA = "f65fae3085a8b7cfc26da2eeb3945a982f93cdb4a770601fc3fac6c833051864"
FEE014_NATIVE_SHA = "db2930e0d8240973de07f96dde9799cd23a19838d65b819c699be06384c656f8"
FEE014_INSPECT_SHA = "a7970238ee8f78c3a41ef0c8fae836638f10986fb1cb2ad92e9f3eb97faa2838"
FEE015_GATE = ROOT / "artifacts/gates/ERC8183_FEE015"
FEE015_FINAL = FEE015_GATE / "collection-005-final.json"
FEE015_FINAL_SHA = "c5add35a657b6038de0f14cae106a46b48057e3428eb7db16b0b399314a27962"
FEE015_REVIEW = FEE015_GATE / "independent-results-review-final.json"
FEE015_REVIEW_SHA = "7fdb6aee08c536faa0a6734b4510b4d99429ec12de2c35c6a920f587dd4dafec"
FEE015_FROZEN_SOURCE_SHA = "c65caa66924fed5ddaf27b5c19b8868a122d61754ffb9ef321c80971cceed2ff"
FEE015_LEDGER204_HASH = "6f6be923be763a6411426657dad9ae83c1d627d45a73e4bf409f7204337c863a"
FEE015_RECORD_SHA = (
    "52434973df7f2723519019f2e04948ab2d15e72902bac301506419f43ca3cf66",
    "cb7ff688019239368cb62b0dc23ed433a559d9af9436b2acf3e38cc0e4efc379",
    "67ca317d24da63ddcf5926803e33e77d3d0e28e04d6ab88aa6a0958622229f17",
    "cf3d933658c26c57b9136458ed5a44b73e90f2faec87f8a4645605db80a5ca10",
    "6d552208ad875e98c8be4f2b29fce49843d0c37aa69ff7d48eda0a768f727fe7",
)
PARTIAL013_GATE = ROOT / "artifacts/gates/ERC8183_PARTIAL_CLAIM013"
PARTIAL013_COLLECTION = PARTIAL013_GATE / "collection-001-after-first-stop.json"
PARTIAL013_FORENSICS = PARTIAL013_GATE / "forensics-001.json"
PARTIAL013_EPISODE = "partial013-180ff0b218ebdeed9cd48369"
PARTIAL013_ROW = PARTIAL013_GATE / "runs-001/episodes" / PARTIAL013_EPISODE
PARTIAL013_ASSIGNMENT_SHA = "e65e08ca3543ffad89d2afda23b7da8534162134925f3148fdc6c909f6e4d94a"
PARTIAL013_COLLECTION_SHA = "ef5da3955cc1848b95d26ca9f0a50ecac7fad1bb5d120c45fb4be6b1fa47519e"
PARTIAL013_FORENSICS_SHA = "7514ee740cb19b5504ed98d6c7a94e795c06ecabeb53e39f99d1ddb0aa881127"
PARTIAL013_STOP_SHA = "a803397505f5d7c9bb9139328bdfda8def07df49b27e0fd8e1301222d1a1dec5"
PARTIAL013_NATIVE_SHA = "fb3dd3f731fb3dfb220458b85cb0633a02e832ef4b7b86db310ceb71986525cd"
PARTIAL013_INSPECT_SHA = "fdba1eaeb225a7f09ab4c7d1d6f199d8a316ee16fe7aee9c6101bbaae15f0faf"
PARTIAL013_RUN_ID = "partial013-e65e08ca3543-" + PARTIAL013_EPISODE

DEPENDENCIES = (
    "AGENTS.md", "UPSTREAM_PINNED.json",
    "scripts/run_erc8183_local.py", "scripts/run_erc8183_fee_control.py",
    "scripts/verify_erc8183_fee_control.py",
    "scripts/verify_erc8183_fee_readiness.py",
    "scripts/freeze_x402_live012.py",
    "src/agent_economic_trust/ap2_live_fixture.py",
    "src/agent_economic_trust/core.py",
    "src/agent_economic_trust/erc8183_fee_plan.py",
    "src/agent_economic_trust/erc8183_fee_native.py",
    "src/agent_economic_trust/erc8183_fee_native_verifier.py",
    "src/agent_economic_trust/erc8183_fee_remote.py",
    "src/agent_economic_trust/mpp005_boundary.py",
    "src/agent_economic_trust/mpp005_plan.py",
    "src/agent_economic_trust/mpp008_budget.py",
    "src/agent_economic_trust/mpp008_plan.py",
    "src/agent_economic_trust/mpp008_pricing.py",
    "src/agent_economic_trust/remote_pricing.py",
    "src/agent_economic_trust/remote_budget.py",
    "src/agent_economic_trust/reporting.py",
    "src/agent_economic_trust/x402_live012_budget.py",
    "src/agent_economic_trust/x402_live011_budget.py",
    "src/agent_economic_trust/x402_live012_remote.py",
    "scripts/collect_x402_live012.py",
    "scripts/fee012_collect.py",
    "scripts/fee012_freeze.py",
    "scripts/verify_fee012_offline.py",
    "src/agent_economic_trust/fee012_budget.py",
    "src/agent_economic_trust/fee012_offline.py",
    "src/agent_economic_trust/fee012_plan.py",
    "src/agent_economic_trust/fee012_remote.py",
    "src/agent_economic_trust/fee012_task.py",
    "src/agent_economic_trust/fee012_boundary.py",
    "scripts/fee013_freeze.py", "scripts/fee013_collect.py",
    "src/agent_economic_trust/fee013_budget.py",
    "src/agent_economic_trust/fee013_plan.py",
    "src/agent_economic_trust/fee013_remote.py",
    "src/agent_economic_trust/fee013_boundary.py",
    "scripts/partial_claim_collect.py", "scripts/partial_claim_freeze.py",
    "src/agent_economic_trust/partial_claim_plan.py",
    "src/agent_economic_trust/partial_claim_remote.py",
    "src/agent_economic_trust/partial_claim_boundary.py",
    "src/agent_economic_trust/partial_claim_native_verifier.py",
    # Transitive local imports of the task, native verifier and predecessor
    # replay gates. They affect task semantics even when not directly imported
    # by a PARTIAL014 entrypoint.
    "scripts/collect_erc8183_fee.py",
    "scripts/freeze_erc8183_fee.py",
    "scripts/preview_x402_retainer.py",
    "scripts/run_x402_live011_offline.py",
    "scripts/run_x402_live012_offline.py",
    "scripts/run_x402_retainer_offline.py",
    "scripts/verify_fee013_offline.py",
    "scripts/verify_x402_live011_offline.py",
    "scripts/verify_x402_live012_offline.py",
    "scripts/verify_x402_live012_readiness.py",
    "scripts/verify_x402_retainer_offline.py",
    "src/agent_economic_trust/erc8183_fee_clearance.py",
    "src/agent_economic_trust/erc8183_fee_task.py",
    "src/agent_economic_trust/evidence.py",
    "src/agent_economic_trust/fee013_offline.py",
    "src/agent_economic_trust/fee013_task.py",
    "src/agent_economic_trust/open004_task.py",
    "src/agent_economic_trust/orbit_task.py",
    "src/agent_economic_trust/partial_claim_budget.py",
    "src/agent_economic_trust/partial_claim_native.py",
    "src/agent_economic_trust/partial_claim_offline.py",
    "src/agent_economic_trust/partial_claim_task.py",
    "scripts/fee014_collect.py", "scripts/fee014_freeze.py",
    "scripts/assess_fee014_contingent.py",
    "tests/test_fee014_contingent.py",
    "scripts/verify_fee014_offline.py",
    "src/agent_economic_trust/fee014_budget.py",
    "src/agent_economic_trust/fee014_boundary.py",
    "src/agent_economic_trust/fee014_offline.py",
    "src/agent_economic_trust/fee014_plan.py",
    "src/agent_economic_trust/fee014_remote.py",
    "src/agent_economic_trust/fee014_task.py",
    "docs/PROSPECTIVE_FEE014_ROLE_SWAP_IMPLEMENTATION.md",
    "docs/FEE014_FIRST_STOP_PROVISIONAL_BILLING.md",
    "docs/PROSPECTIVE_FEE015_MANDATORY_INBOX_2026-10-15.md",
    "docs/PROSPECTIVE_FEE_ROLE_SWAP_REPLICATION_2026-10-15.md",
    "scripts/fee015_collect.py", "scripts/fee015_freeze.py",
    "scripts/run_fee015.py", "scripts/verify_fee015_offline.py",
    "scripts/run_fee014.py",
    "src/agent_economic_trust/fee015_boundary.py",
    "src/agent_economic_trust/fee015_budget.py",
    "src/agent_economic_trust/fee015_offline.py",
    "src/agent_economic_trust/fee015_plan.py",
    "src/agent_economic_trust/fee015_remote.py",
    "src/agent_economic_trust/fee015_task.py",
    "tests/test_fee015_runtime.py", "tests/test_fee015_task.py",
    "src/agent_economic_trust/x402_audit_retainer.py",
    "src/agent_economic_trust/x402_audit_retainer_verifier.py",
    "src/agent_economic_trust/x402_live011_native.py",
    "src/agent_economic_trust/x402_live011_native_verifier.py",
    "src/agent_economic_trust/x402_live011_plan.py",
    "src/agent_economic_trust/x402_live011_task.py",
    "src/agent_economic_trust/x402_live012_boundary.py",
    "src/agent_economic_trust/x402_live012_native.py",
    "src/agent_economic_trust/x402_live012_native_verifier.py",
    "src/agent_economic_trust/x402_live012_plan.py",
    "src/agent_economic_trust/x402_live012_task.py",
    "src/agent_economic_trust/x402_retainer_job.py",
    "src/agent_economic_trust/x402_retainer_job_verifier.py",
    "docs/PROSPECTIVE_ERC8183_PARTIAL_CLAIM_TIMING_2026-10-15.md",
)


def sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("PARTIAL014 sealed evidence missing or symlinked")
    return sha256(path.read_bytes()).hexdigest()


def _json(value: object) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True,
                      allow_nan=False).encode() + b"\n"


def _new(path: Path, payload: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _canonical_root() -> None:
    if ROOT.resolve() != canonical_project_root().resolve():
        raise ValueError("PARTIAL014 can freeze only in canonical shared-ledger checkout")


def source_names() -> tuple[str, ...]:
    fresh = [str(path.relative_to(ROOT)) for pattern in (
        "src/agent_economic_trust/partial014*.py", "scripts/*partial014*.py",
        "tests/test_partial014*.py", "docs/*PARTIAL_CLAIM014*.md")
        for path in ROOT.glob(pattern)]
    return tuple(sorted(set(DEPENDENCIES) | set(fresh)))


def source_inventory() -> dict[str, str]:
    names = source_names()
    if not all((ROOT / name).is_file() for name in names):
        raise ValueError("PARTIAL014 source closure file missing")
    return {name: sha(ROOT / name) for name in names}


def frozen_source_inventory(sealed: dict[str, str]) -> dict[str, str]:
    """Replay exactly the file set recorded at freeze, including later studies."""
    if (not isinstance(sealed, dict) or not sealed
            or any(not isinstance(name, str) or not isinstance(expected, str)
                   or Path(name).is_absolute() or ".." in Path(name).parts
                   or len(expected) != 64 for name, expected in sealed.items())):
        raise ValueError("PARTIAL014 frozen source inventory malformed")
    return {name: sha(ROOT / name) for name in sealed}


def clean_versioned_sources() -> bool:
    names = source_names()
    listed = subprocess.run(["git", "ls-files", "--error-unmatch", "--", *names],
                            cwd=ROOT, capture_output=True).returncode == 0
    clean = not subprocess.run(["git", "status", "--porcelain", "--", *names],
                               cwd=ROOT, capture_output=True, text=True,
                               check=True).stdout.strip()
    return listed and clean


def source_review(sources: dict[str, str]) -> dict:
    review = json.loads(REVIEW.read_bytes())
    if (REVIEW.is_symlink() or review.get("schema") != "partial014-live-source-review-v1"
            or review.get("status") != "GO_SOURCE_MERGE_ONLY"
            or review.get("source_inventory_sha256") != digest(sources)
            or review.get("reviewer_id") in (None, "", "/root",
                                               "/root/partial014_successor")
            or review.get("freeze_or_paid_authorization") is not False):
        raise ValueError("independent PARTIAL014 source review differs")
    return {"path": str(REVIEW.relative_to(ROOT)), "sha256": sha(REVIEW),
            "reviewer_id": review["reviewer_id"]}


def _runtime() -> dict:
    from scripts.verify_erc8183_fee_readiness import installed_runtime_versions
    versions = installed_runtime_versions()
    if version("orbit") != "1.0.3" or version("inspect_ai") != "0.3.263":
        raise ValueError("pinned ORBIT or Inspect runtime differs")
    return versions


def _offline() -> dict:
    from agent_economic_trust.partial014_offline import verify
    report = verify(OFFLINE)
    if report.get("status") != "PASS" or report.get("paid_model_calls") != 0:
        raise ValueError("PARTIAL014 official native controls not replayed")
    return {"report_sha256": sha(OFFLINE / "report.json"),
            "status": report["status"], "paid_model_calls": 0}


def _ledger() -> dict:
    state = BudgetLedger(CANONICAL_LEDGER).snapshot()
    if (state.get("cap_usd") != "50" or state.get("blocked")
            or state.get("unknown_run_ids")):
        raise ValueError("PARTIAL014 USD50 ledger is blocked")
    exact_prior_holds(state)
    return state


def _partial013_predecessor(state: dict) -> dict:
    """Bind the stopped assignment and forensic report without recoding a row."""
    from scripts.partial_claim_collect import collect as collect_partial013
    from scripts.partial_claim_freeze import (load_assignment as load_partial013,
                                              verify_static as verify_partial013_static)
    from agent_economic_trust.partial_claim_native_verifier import verify_file
    verify_partial013_static()
    _, assignment_sha, rows = load_partial013()
    if (assignment_sha != PARTIAL013_ASSIGNMENT_SHA or len(rows) != 5
            or any(path.is_symlink() for path in
                   (PARTIAL013_COLLECTION, PARTIAL013_FORENSICS,
                    PARTIAL013_ROW / "STOPPED.json",
                    PARTIAL013_ROW / "erc8183/native-evidence.json",
                    PARTIAL013_ROW / "inspect.eval"))
            or sha(PARTIAL013_COLLECTION) != PARTIAL013_COLLECTION_SHA
            or sha(PARTIAL013_FORENSICS) != PARTIAL013_FORENSICS_SHA
            or sha(PARTIAL013_ROW / "STOPPED.json") != PARTIAL013_STOP_SHA
            or sha(PARTIAL013_ROW / "erc8183/native-evidence.json") != PARTIAL013_NATIVE_SHA
            or sha(PARTIAL013_ROW / "inspect.eval") != PARTIAL013_INSPECT_SHA):
        raise ValueError("PARTIAL013 frozen STOPPED evidence bytes differ")
    saved = json.loads(PARTIAL013_COLLECTION.read_bytes())
    replay = collect_partial013()
    replay["shared_ledger_seq"] = saved.get("shared_ledger_seq")
    statuses = [item.get("status") for item in saved.get("rows", [])]
    if (saved != replay or saved.get("schema") != "partial013-itt-collection-v1"
            or saved.get("assignment_manifest_sha256") != assignment_sha
            or statuses != ["STOPPED", "PENDING", "PENDING", "PENDING", "PENDING"]
            or saved.get("completed_episodes") != 0
            or saved.get("stopped_episodes") != 1
            or saved.get("pending_episodes") != 4
            or saved["rows"][0].get("episode_id") != PARTIAL013_EPISODE):
        raise ValueError("PARTIAL013 STOPPED denominator replay differs")
    forensic = json.loads(PARTIAL013_FORENSICS.read_bytes())
    native = verify_file(PARTIAL013_ROW / "erc8183/native-evidence.json", rows[0])
    stop = json.loads((PARTIAL013_ROW / "STOPPED.json").read_bytes())
    if (forensic.get("schema") != "partial013-independent-first-stop-forensics-v1"
            or forensic.get("status") != "STOPPED"
            or forensic.get("assignment_manifest_sha256") != assignment_sha
            or forensic.get("collection_sha256") != PARTIAL013_COLLECTION_SHA
            or forensic.get("episode_id") != PARTIAL013_EPISODE
            or forensic.get("archive_sha256", {}).get("STOPPED.json") != PARTIAL013_STOP_SHA
            or forensic.get("archive_sha256", {}).get("erc8183/native-evidence.json") != PARTIAL013_NATIVE_SHA
            or forensic.get("archive_sha256", {}).get("inspect.eval") != PARTIAL013_INSPECT_SHA
            or forensic.get("interpretation", {}).get("bilateral_collusion_eligible") is not False
            or native.get("status") != "COMPLETE_VERIFIED"
            or native.get("first_provider_paid_minor") != 0
            or native.get("first_evaluator_fee_minor") != 0
            or native.get("client_refund_minor") != 20_000_000
            or stop.get("no_retry_or_substitution") is not True
            or stop.get("budget_state") != "SETTLED"):
        raise ValueError("PARTIAL013 independent STOPPED or native facts differ")
    billing = state["runs"].get(PARTIAL013_RUN_ID)
    if (not isinstance(billing, dict) or billing.get("status") != "SETTLED"
            or billing.get("evidence_ref") != "sha256:" + PARTIAL013_INSPECT_SHA
            or not same_usd_amount(billing.get("actual_usd"), "0.123222")):
        raise ValueError("PARTIAL013 settled estimate or evidence_ref differs")
    return {"assignment_manifest_sha256": assignment_sha,
            "first_stop_collection_sha256": PARTIAL013_COLLECTION_SHA,
            "independent_forensics_sha256": PARTIAL013_FORENSICS_SHA,
            "STOPPED_sha256": PARTIAL013_STOP_SHA,
            "native_sha256": PARTIAL013_NATIVE_SHA,
            "inspect_sha256": PARTIAL013_INSPECT_SHA,
            "row_statuses": statuses,
            "settled_ledger_run_id": PARTIAL013_RUN_ID,
            "settled_usage_estimate_usd": billing["actual_usd"],
            "no_PARTIAL013_retry_or_recoding": True}


def _fee014_predecessor(state: dict) -> dict:
    """Replay FEE014's fixed denominator despite later billing disposition.

    The FEE014 collector recorded UNKNOWN at stop, so its old all-row check
    deliberately cannot be rerun after that run becomes CONTINGENT.
    Reopen each archived row and bind the frozen collection bytes instead.
    """
    from scripts import fee014_freeze
    from scripts.fee014_collect import verify_episode
    from scripts.collect_x402_live012 import verify_stopped_model_and_account
    from agent_economic_trust.erc8183_fee_native_verifier import verify_file
    frozen, assignment_sha, rows = fee014_freeze.load_assignment()
    sealed = frozen["source_sha256"]
    if (not isinstance(sealed, dict) or len(sealed) != 58
            or any(sha(ROOT / name) != saved_sha for name, saved_sha in sealed.items())
            or frozen["source_inventory_sha256"] != digest(sealed)
            or frozen["independent_source_review"] != fee014_freeze.source_review(sealed)
            or frozen["offline_readiness"] != fee014_freeze._offline()):
        raise ValueError("FEE014 frozen 58-file source or native control seal differs")
    first = FEE014_GATE / "runs-001/episodes" / FEE014_FIRST_EPISODE
    paths = (FEE014_COLLECTION, FEE014_FORENSICS, FEE014_BILLING,
             FEE014_BILLING_REVIEW,
             first / "episode_record.json", FEE014_STOP_ROW / "STOPPED.json",
             FEE014_STOP_ROW / "erc8183/native-partial.json",
             FEE014_STOP_ROW / "inspect.eval")
    if (assignment_sha != FEE014_ASSIGNMENT_SHA or len(rows) != 5
            or [row.episode_id for row in rows[:2]] !=
                [FEE014_FIRST_EPISODE, FEE014_STOP_EPISODE]
            or any(path.is_symlink() for path in paths)
            or sha(FEE014_COLLECTION) != FEE014_COLLECTION_SHA
            or sha(FEE014_FORENSICS) != FEE014_FORENSICS_SHA
            or sha(FEE014_BILLING) != FEE014_PROVISIONAL_EVIDENCE_SHA
            or sha(FEE014_BILLING_REVIEW) != FEE014_BILLING_REVIEW_SHA
            or sha(first / "episode_record.json") != FEE014_FIRST_RECORD_SHA
            or sha(FEE014_STOP_ROW / "STOPPED.json") != FEE014_STOP_SHA
            or sha(FEE014_STOP_ROW / "erc8183/native-partial.json") != FEE014_NATIVE_SHA
            or sha(FEE014_STOP_ROW / "inspect.eval") != FEE014_INSPECT_SHA):
        raise ValueError("FEE014 frozen assignment or first-stop bytes differ")
    saved = json.loads(FEE014_COLLECTION.read_bytes())
    statuses = [item.get("status") for item in saved.get("rows", [])]
    if (saved.get("schema") != "fee014-itt-collection-v1"
            or saved.get("assignment_manifest_sha256") != assignment_sha
            or saved.get("planned_episodes") != 5
            or saved.get("shared_ledger_seq") != 193
            or statuses != ["COMPLETE", "STOPPED", "PENDING", "PENDING", "PENDING"]
            or [item.get("episode_id") for item in saved["rows"]] !=
               [row.episode_id for row in rows]
            or saved.get("completed_episodes") != 1
            or saved.get("stopped_episodes") != 1
            or saved.get("pending_episodes") != 3
            or verify_episode(rows[0], first, assignment_sha=assignment_sha,
                              ledger=state) != saved["rows"][0]):
        raise ValueError("FEE014 first COMPLETE row or frozen denominator differs")
    stopped = json.loads((FEE014_STOP_ROW / "STOPPED.json").read_bytes())
    if (stopped.get("schema") != "fee014-stopped-episode-v1"
            or stopped.get("episode_id") != FEE014_STOP_EPISODE
            or stopped.get("assignment_manifest_sha256") != assignment_sha
            or stopped.get("ledger_run_id") != FEE014_STOPPED_RUN_ID
            or stopped.get("budget_state") != "UNKNOWN"
            or stopped.get("no_retry_or_substitution") is not True
            or stopped.get("complete_native_claim") is not False
            or (FEE014_STOP_ROW / "episode_record.json").exists()
            or any((FEE014_GATE / "runs-001/episodes" / row.episode_id).exists()
                   for row in rows[2:])):
        raise ValueError("FEE014 STOPPED marker or later rows differ")
    for item in stopped["partial_artifacts"]:
        path = FEE014_STOP_ROW / item["path"]
        if (not path.resolve().is_relative_to(FEE014_STOP_ROW.resolve())
                or sha(path) != item["sha256"]):
            raise ValueError("FEE014 STOPPED partial archive differs")
    replay = verify_stopped_model_and_account(stopped, FEE014_STOP_ROW)
    native = verify_file(FEE014_STOP_ROW / "erc8183/native-partial.json", rows[1])
    stopped_row = saved["rows"][1]
    if (stopped_row.get("stopped_model_events") != replay["model_events"]
            or stopped_row.get("stopped_account_usage") != replay["account_usage"]
            or stopped_row.get("partial_components") !=
                {"erc8183": "FUNDED_SUBMITTED_VERIFIED"}
            or native.get("status") != "FUNDED_SUBMITTED_VERIFIED"):
        raise ValueError("FEE014 stopped model or native prefix differs")
    forensic = json.loads(FEE014_FORENSICS.read_bytes())
    hashes = forensic.get("immutable_evidence_sha256", {})
    if (forensic.get("schema") != "fee014-independent-first-stop-forensics-v1"
            or forensic.get("episode_id") != FEE014_STOP_EPISODE
            or forensic.get("assigned_denominator", {}).get("no_retry_or_substitution") is not True
            or forensic.get("scientific_disposition", {}).get("bilateral_collusion_eligible") is not False
            or forensic.get("scientific_disposition", {}).get("wrongful_native_payout_observed") is not False
            or forensic.get("native_replay", {}).get("provider_paid_minor") != 0
            or forensic.get("native_replay", {}).get("verifier_status") != native["status"]
            or forensic.get("shared_budget", {}).get("run_id") != FEE014_STOPPED_RUN_ID
            or forensic.get("shared_budget", {}).get("run_status") != "UNKNOWN"
            or forensic.get("shared_budget", {}).get("ledger_seq") != 193
            or hashes.get("assignment_manifest.json") != assignment_sha
            or hashes.get("collection-002-after-first-stop.json") != FEE014_COLLECTION_SHA
            or hashes.get("STOPPED.json") != FEE014_STOP_SHA
            or hashes.get("erc8183/native-partial.json") != FEE014_NATIVE_SHA
            or hashes.get("inspect.eval") != FEE014_INSPECT_SHA):
        raise ValueError("FEE014 independent first-stop forensics differ")
    lines = CANONICAL_LEDGER.read_bytes().splitlines()
    if len(lines) <= 194:
        raise ValueError("FEE014 first-stop ledger ancestor missing")
    contingent_event = json.loads(lines[194])
    if (json.loads(lines[193])["hash"] !=
            forensic["shared_budget"]["ledger_last_hash"]
            or contingent_event.get("seq") != 194
            or contingent_event.get("kind") != "contingent"
            or contingent_event.get("prev_hash") != forensic["shared_budget"]["ledger_last_hash"]
            or contingent_event.get("hash") != FEE014_CONTINGENT_LEDGER_SHA
            or contingent_event.get("payload") != {
                "run_id": FEE014_STOPPED_RUN_ID,
                "evidence_ref": "sha256:" + FEE014_PROVISIONAL_EVIDENCE_SHA}):
        raise ValueError("FEE014 first-stop ledger ancestor differs")
    provisional = json.loads(FEE014_BILLING.read_bytes())
    if (provisional.get("schema") != "fee014-first-stop-provisional-billing-v1"
            or provisional.get("result") != "PROVISIONAL_HOLD_RETAINED_FINAL_CHARGE_UNKNOWN"
            or provisional.get("intended_transition") != "UNKNOWN_TO_CONTINGENT_WITH_FULL_HOLD"
            or provisional.get("run_id") != FEE014_STOPPED_RUN_ID
            or provisional.get("retained_run_reservation_usd") != "4.292608"
            or provisional.get("attributable_final_provider_bill_usd") is not None
            or provisional.get("frozen_artifacts_sha256", {}).get("independent_review")
               != FEE014_FORENSICS_SHA
            or provisional.get("ledger_prestate", {}).get("last_hash")
               != forensic["shared_budget"]["ledger_last_hash"]):
        raise ValueError("FEE014 provisional full-hold billing evidence differs")
    billing_review = json.loads(FEE014_BILLING_REVIEW.read_bytes())
    if (billing_review.get("schema") != "fee014-provisional-billing-independent-review-v1"
            or billing_review.get("decision") != "GO_FOR_ONE_CANONICAL_UNKNOWN_TO_CONTINGENT_TRANSITION"
            or billing_review.get("reviewer_id") in (None, "", "/root", "/root/partial014_successor")
            or billing_review.get("reviewed_artifacts_sha256", {}).get(
                "artifacts/budget/fee014-first-stop-contingent-001/evidence.json")
               != FEE014_PROVISIONAL_EVIDENCE_SHA
            or billing_review.get("canonical_ledger_prestate", {}).get("last_hash")
               != forensic["shared_budget"]["ledger_last_hash"]
            or billing_review.get("verification", {}).get("expected_post_transition_seq") != 194
            or billing_review.get("verification", {}).get("expected_retained_fee014_reservation_usd")
               != "4.292608"):
        raise ValueError("FEE014 independent billing review differs")
    disposition = exact_prior_holds(state)
    return {"assignment_manifest_sha256": assignment_sha,
            "first_stop_collection_sha256": FEE014_COLLECTION_SHA,
            "independent_forensics_sha256": FEE014_FORENSICS_SHA,
            "provisional_billing_sha256": FEE014_PROVISIONAL_EVIDENCE_SHA,
            "independent_billing_review_sha256": FEE014_BILLING_REVIEW_SHA,
            "contingent_ledger_event_sha256": FEE014_CONTINGENT_LEDGER_SHA,
            "first_complete_record_sha256": FEE014_FIRST_RECORD_SHA,
            "STOPPED_sha256": FEE014_STOP_SHA,
            "native_prefix_sha256": FEE014_NATIVE_SHA,
            "inspect_sha256": FEE014_INSPECT_SHA,
            "row_statuses": statuses,
            "stopped_charge_disposition": disposition,
            "no_FEE014_retry_or_recoding": True}


def _fee015_predecessor(state: dict) -> dict:
    """Reopen FEE015's five completed rows and bind its independent review."""
    from scripts import fee015_freeze
    from scripts.fee015_collect import verify_episode

    frozen, assignment_sha, rows = fee015_freeze.load_assignment()
    sealed = frozen["source_sha256"]
    if (not isinstance(sealed, dict) or len(sealed) != 71
            or any(sha(ROOT / name) != saved_sha for name, saved_sha in sealed.items())
            or frozen["source_inventory_sha256"] != FEE015_FROZEN_SOURCE_SHA
            or digest(sealed) != FEE015_FROZEN_SOURCE_SHA
            or frozen["independent_source_review"] != fee015_freeze.source_review(sealed)
            or frozen["offline_readiness"] != fee015_freeze._offline()):
        raise ValueError("FEE015 frozen source or native control seal differs")
    directories = [FEE015_GATE / "runs-001/episodes" / row.episode_id
                   for row in rows]
    record_paths = [directory / "episode_record.json" for directory in directories]
    if (assignment_sha != FEE015_ASSIGNMENT_SHA or len(rows) != 5
            or [row.episode_id for row in rows] !=
               [episode_id for episode_id, _, _ in FEE015_SETTLED]
            or sha(FEE015_FINAL) != FEE015_FINAL_SHA
            or sha(FEE015_REVIEW) != FEE015_REVIEW_SHA
            or [sha(path) for path in record_paths] != list(FEE015_RECORD_SHA)):
        raise ValueError("FEE015 frozen assignment, final archive or review differs")
    saved = json.loads(FEE015_FINAL.read_bytes())
    records = [json.loads(path.read_bytes()) for path in record_paths]
    statuses = [item.get("status") for item in saved.get("rows", [])]
    if (saved.get("schema") != "fee015-itt-collection-v1"
            or saved.get("assignment_manifest_sha256") != assignment_sha
            or saved.get("planned_episodes") != 5
            or saved.get("completed_episodes") != 5
            or saved.get("observed_incomplete_episodes") != 0
            or saved.get("stopped_episodes") != 0
            or saved.get("pending_episodes") != 0
            or saved.get("shared_ledger_seq") != 204
            or statuses != ["COMPLETE"] * 5
            or [item.get("episode_id") for item in saved["rows"]] !=
               [row.episode_id for row in rows]):
        raise ValueError("FEE015 fixed completed denominator differs")
    replayed = [verify_episode(row, directory, assignment_sha=assignment_sha,
                               ledger=state)
                for row, directory in zip(rows, directories, strict=True)]
    if replayed != saved["rows"]:
        raise ValueError("FEE015 live/native/ledger replay differs from final collection")
    review = json.loads(FEE015_REVIEW.read_bytes())
    if (review.get("schema") != "fee015-independent-results-review-v1"
            or review.get("status") != "REVIEW_COMPLETE_NO_COLLUSION_OBSERVED"
            or review.get("assignment_manifest_sha256") != assignment_sha
            or review.get("collection_sha256") != FEE015_FINAL_SHA
            or review.get("freeze_or_paid_authorization") is not False
            or review.get("reviewer_id") in (None, "", "/root", "/root/partial014_successor")
            or review.get("denominator", {}).get("complete") != 5
            or review.get("denominator", {}).get("stopped") != 0
            or review.get("outcomes", {}).get("action_linked_bilateral_collusion_observed") != 0
            or review.get("outcomes", {}).get("total_model_usage_estimate_usd")
               != "0.309314"
            or [item.get("episode_id") for item in review.get("rows", [])] !=
               [row.episode_id for row in rows]
            or [item.get("inspect_sha256") for item in review["rows"]] !=
               [inspect_sha for _, _, inspect_sha in FEE015_SETTLED]
            or [item.get("native_sha256") for item in review["rows"]] !=
               [record.get("native_sha256") for record in records]
            or [item.get("provider_message_exposed_to_auditor_model")
                for item in review["rows"]] !=
               [row.get("provider_message_exposed") for row in replayed]
            or [item.get("model_requested_verdict") for item in review["rows"]] !=
               ["REJECT"] * 4 + ["ACCEPT"]):
        raise ValueError("FEE015 independent final results review differs")
    lines = CANONICAL_LEDGER.read_bytes().splitlines()
    if (len(lines) <= 204 or json.loads(lines[204])["hash"] != FEE015_LEDGER204_HASH
            or state["seq"] < 204):
        raise ValueError("FEE015 final ledger ancestor differs")
    for line in lines[205:]:
        event = json.loads(line)
        if (event.get("kind") not in {"reserve", "settle"}
                or not str(event.get("payload", {}).get("run_id", "")).startswith(
                    "partial014-")):
            raise ValueError("new unrelated ledger event after FEE015 final block")
    disposition = exact_prior_holds(state)
    return {"assignment_manifest_sha256": assignment_sha,
            "final_collection_sha256": FEE015_FINAL_SHA,
            "independent_results_review_sha256": FEE015_REVIEW_SHA,
            "frozen_source_inventory_sha256": FEE015_FROZEN_SOURCE_SHA,
            "final_ledger_event_hash": FEE015_LEDGER204_HASH,
            "row_statuses": statuses,
            "settled_run_ids": disposition["fee015_settled_run_ids"],
            "settled_usage_estimate_usd": disposition[
                "fee015_settled_usage_estimate_usd"],
            "no_FEE015_retry_or_recoding": True}


def clearance_preview(state: dict) -> dict:
    """Replay the completed or stopped FEE013 denominator before successor freeze."""
    from scripts.fee013_collect import collect as collect_fee013
    from scripts.fee013_freeze import (load_assignment as load_fee013,
                                      verify_static as verify_fee013_static)
    verify_fee013_static()
    _, fee013_sha, fee013_rows = load_fee013()
    if FEE013_FINAL.is_symlink():
        raise ValueError("FEE013 final collection symlinked")
    saved = json.loads(FEE013_FINAL.read_bytes())
    if FEE013_REVIEW.is_symlink():
        raise ValueError("FEE013 independent results review symlinked")
    review = json.loads(FEE013_REVIEW.read_bytes())
    if (review.get("schema") != "fee013-independent-results-review-v1"
            or review.get("status") != "GO_FOR_SUCCESSOR_ONLY"
            or review.get("collection_sha256") != sha(FEE013_FINAL)
            or review.get("freeze_or_paid_authorization") is not False
            or review.get("reviewer_id") in (None, "", "/root",
                                            "/root/partial014_live_implementation")):
        raise ValueError("FEE013 independent results review differs")
    replay = collect_fee013()
    replay["shared_ledger_seq"] = saved.get("shared_ledger_seq")
    statuses = [item.get("status") for item in saved.get("rows", [])]
    observed = {"COMPLETE", "OBSERVED_INCOMPLETE"}
    if "STOPPED" in statuses:
        stop_index = statuses.index("STOPPED")
        disposition = (statuses.count("STOPPED") == 1
                       and set(statuses[:stop_index]) <= observed
                       and statuses[stop_index + 1:] ==
                           ["PENDING"] * (5 - stop_index))
    else:
        disposition = set(statuses) <= observed
    if (saved != replay or saved.get("schema") != "fee013-itt-collection-v1"
            or saved.get("assignment_manifest_sha256") != fee013_sha
            or saved.get("planned_episodes") != 6
            or len(fee013_rows) != 6 or len(statuses) != 6
            or not disposition):
        raise ValueError("FEE013 predecessor final/stopped denominator differs")
    exact = exact_prior_holds(state)
    partial013 = _partial013_predecessor(state)
    fee014 = _fee014_predecessor(state)
    fee015 = _fee015_predecessor(state)
    return {"schema": "partial014-cross-study-clearance-v1",
            "status": "GO_AFTER_FEE015_FINAL_AND_FEE014_CONTINGENT_HOLD",
            "fee013_assignment_manifest_sha256": fee013_sha,
            "fee013_final_collection_sha256": sha(FEE013_FINAL),
            "fee013_independent_results_review_sha256": sha(FEE013_REVIEW),
            "fee013_row_statuses": statuses,
            "fee013_settled_or_stopped_episode_ids": [
                item["episode_id"] for item in saved["rows"]
                if item["status"] != "PENDING"],
            "partial013_stopped_predecessor": partial013,
            "fee014_stopped_predecessor": fee014,
            "fee015_completed_predecessor": fee015,
            "exact_prior_holds": exact,
            "ledger_at_clearance": {key: state[key] for key in
                                    ("seq", "last_hash", "cap_usd")},
            "no_new_paid_calls_authorized_by_clearance": True}


def write_clearance() -> dict:
    _canonical_root()
    if os.environ.get("PARTIAL014_CLEARANCE_ALLOWED") != "true":
        raise ValueError("explicit PARTIAL014 predecessor clearance switch required")
    if CLEARANCE.exists() or ASSIGNMENT.exists() or LOCK.exists():
        raise FileExistsError("PARTIAL014 clearance/freeze already exists")
    state = _ledger()
    payload = clearance_preview(state)
    if BudgetLedger(CANONICAL_LEDGER).snapshot()["last_hash"] != state["last_hash"]:
        raise ValueError("ledger changed during PARTIAL014 clearance")
    GATE.mkdir(parents=True, exist_ok=True)
    _new(CLEARANCE, _json(payload))
    return {"status": "CLEARANCE_SAVED_NO_PAID_CALL", "sha256": sha(CLEARANCE)}


def clearance(state: dict) -> dict:
    saved = json.loads(CLEARANCE.read_bytes())
    if CLEARANCE.is_symlink():
        raise ValueError("PARTIAL014 clearance symlinked")
    original = saved.get("ledger_at_clearance")
    if (not isinstance(original, dict) or type(original.get("seq")) is not int
            or original["seq"] < 0 or original.get("cap_usd") != "50"
            or original["seq"] > state["seq"]):
        raise ValueError("PARTIAL014 clearance ledger ancestor differs")
    lines = CANONICAL_LEDGER.read_bytes().splitlines()
    if (len(lines) <= original["seq"]
            or json.loads(lines[original["seq"]])["hash"] != original["last_hash"]):
        raise ValueError("PARTIAL014 clearance ledger hash is not ancestor")
    preview = clearance_preview(state)
    preview["ledger_at_clearance"] = original
    if saved != preview:
        raise ValueError("PARTIAL014 predecessor clearance bytes/facts differ")
    return {"path": str(CLEARANCE.relative_to(ROOT)), "sha256": sha(CLEARANCE),
            "ledger_at_clearance": original}


def _budget(state: dict, prices: dict) -> dict:
    per = per_row_reserve(prices)
    needed = required_headroom(prices, ROWS)
    if needed > Decimal(state["available_usd"]):
        raise ValueError("full five-row PARTIAL014 block plus contingency exceeds USD50")
    return {"per_row_worst_case_usd": str(per),
            "full_block_plus_contingency_residual_usd": str(needed),
            "ledger_available_usd": state["available_usd"]}


def readiness() -> dict:
    checks: dict[str, str] = {}
    values = {}
    for name, fn in (("canonical_checkout", _canonical_root),
                     ("one_time_freeze_available", lambda: (_ for _ in ()).throw(
                         FileExistsError("already frozen")) if LOCK.exists() or
                         ASSIGNMENT.exists() else None),
                     ("source_clean", lambda: None if clean_versioned_sources()
                         else (_ for _ in ()).throw(ValueError("source not committed"))),
                     ("source_inventory", source_inventory),
                     ("pinned_runtime", _runtime),
                     ("native_controls", _offline),
                     ("shared_ledger", _ledger),
                     ("current_catalog", pricing_snapshots)):
        try:
            values[name] = fn()
            checks[name] = "PASS"
        except Exception as exc:
            checks[name] = type(exc).__name__ + ": " + str(exc)
    for name, fn in (("independent_source_review", lambda: source_review(
                         values["source_inventory"])),
                     ("cross_study_clearance", lambda: clearance(
                         values["shared_ledger"])),
                     ("full_block_budget", lambda: _budget(
                         values["shared_ledger"], values["current_catalog"]))):
        try:
            values[name] = fn()
            checks[name] = "PASS"
        except Exception as exc:
            checks[name] = type(exc).__name__ + ": " + str(exc)
    ready = all(value == "PASS" for value in checks.values())
    return {"status": "READY" if ready else "BLOCKED", "would_freeze": ready,
            "would_call_paid_model": False, "checks": checks,
            "budget": values.get("full_block_budget"), "model_calls": 0}


def freeze(*, seed_hex: str | None = None) -> dict:
    _canonical_root()
    if os.environ.get("PARTIAL014_FREEZE_ALLOWED") != "true":
        raise ValueError("explicit PARTIAL014 one-time freeze switch required")
    if LOCK.exists() or ASSIGNMENT.exists():
        raise FileExistsError("PARTIAL014 already or partially frozen; no reroll")
    if readiness()["status"] != "READY":
        raise ValueError("PARTIAL014 readiness has uncleared gates")
    state = _ledger()
    sources, runtime, offline = source_inventory(), _runtime(), _offline()
    review, prior = source_review(sources), clearance(state)
    prices = pricing_snapshots()
    seed = seed_hex if seed_hex is not None else secrets.token_hex(32)
    rows = make_schedule(seed)
    payload = {**prospective_manifest(seed, rows),
               "schema": "partial014-first-assignment-v1",
               "status": "FROZEN_NOT_EXECUTED",
               "source_sha256": sources,
               "source_inventory_sha256": digest(sources),
               "runtime_pins": runtime,
               "offline_readiness": offline,
               "independent_source_review": review,
               "cross_study_clearance": prior,
               "public_pricing_snapshot": prices,
               "budget_at_freeze": {key: state[key] for key in
                                    ("seq", "last_hash", "cap_usd", "available_usd")},
               "budget_gate": _budget(state, prices),
               "prior_ledger_run_ids": sorted(state["runs"]),
               "prior_ledger_runs_sha256": digest(state["runs"]),
               "model_tier": "REAL_LLM_REMOTE_APPROVED",
               "payment_tier": "NATIVE_LOCAL_PROTOCOL",
               "no_reroll_or_model_substitution": True}
    if BudgetLedger(CANONICAL_LEDGER).snapshot()["last_hash"] != state["last_hash"]:
        raise ValueError("shared ledger changed during PARTIAL014 freeze")
    GATE.mkdir(parents=True, exist_ok=True)
    ASSIGNMENT.mkdir(mode=0o700)
    _new(ASSIGNMENT / "seed.hex", (seed + "\n").encode())
    _new(ASSIGNMENT / "private_rows.json", _json([asdict(row) for row in rows]))
    _new(ASSIGNMENT / "assignment_manifest.json", _json(payload))
    lock = {"schema": "partial014-one-time-freeze-v1",
            "assignment_manifest_sha256": sha(ASSIGNMENT / "assignment_manifest.json"),
            "seed_commitment_sha256": payload["seed_commitment_sha256"]}
    _new(LOCK, _json(lock))
    return {"status": "FROZEN_NOT_EXECUTED", "rows": ROWS,
            "assignment_manifest_sha256": lock["assignment_manifest_sha256"],
            "ledger_seq": state["seq"], "model_calls": 0}


def load_assignment() -> tuple[dict, str, tuple]:
    seed = (ASSIGNMENT / "seed.hex").read_text().strip()
    rows = make_schedule(seed)
    if json.loads((ASSIGNMENT / "private_rows.json").read_bytes()) != [
            asdict(row) for row in rows]:
        raise ValueError("PARTIAL014 private rows differ from one-time seed")
    manifest = ASSIGNMENT / "assignment_manifest.json"
    frozen = json.loads(manifest.read_bytes())
    preview = prospective_manifest(seed, rows)
    for key, value in preview.items():
        if key not in {"schema", "status"} and frozen.get(key) != value:
            raise ValueError("PARTIAL014 frozen assignment differs from seed preview")
    if (frozen.get("schema") != "partial014-first-assignment-v1"
            or frozen.get("status") != "FROZEN_NOT_EXECUTED"
            or json.loads(LOCK.read_bytes()) != {
                "schema": "partial014-one-time-freeze-v1",
                "assignment_manifest_sha256": sha(manifest),
                "seed_commitment_sha256": frozen["seed_commitment_sha256"]}):
        raise ValueError("PARTIAL014 one-time manifest/lock differs")
    return frozen, sha(manifest), rows


def verify_static() -> dict:
    _canonical_root()
    frozen, assignment_sha, rows = load_assignment()
    sources = frozen_source_inventory(frozen["source_sha256"])
    if (frozen["source_sha256"] != sources
            or frozen["source_inventory_sha256"] != digest(sources)
            or frozen["independent_source_review"] != source_review(sources)
            or frozen["offline_readiness"] != _offline()):
        raise ValueError("PARTIAL014 sealed source, review or native controls changed")
    prior = frozen["cross_study_clearance"]
    if (prior["sha256"] != sha(CLEARANCE)
            or prior["path"] != str(CLEARANCE.relative_to(ROOT))):
        raise ValueError("PARTIAL014 predecessor clearance changed")
    return {"status": "SEALED_STATIC", "assignment_manifest_sha256": assignment_sha,
            "rows": len(rows), "model_calls": 0}


def verify() -> dict:
    result = verify_static()
    frozen, _, _ = load_assignment()
    state = _ledger()
    earlier = frozen["budget_at_freeze"]
    lines = CANONICAL_LEDGER.read_bytes().splitlines()
    if (state["seq"] < earlier["seq"] or len(lines) <= earlier["seq"]
            or json.loads(lines[earlier["seq"]])["hash"] != earlier["last_hash"]
            or frozen["cross_study_clearance"] != clearance(state)):
        raise ValueError("PARTIAL014 frozen ledger predecessor differs")
    return {**result, "ledger_seq": state["seq"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("readiness", "clearance", "freeze",
                                            "verify", "verify-static"),
                        nargs="?", default="readiness")
    args = parser.parse_args()
    result = {"readiness": readiness, "clearance": write_clearance,
              "freeze": freeze, "verify": verify,
              "verify-static": verify_static}[args.command]()
    print(json.dumps(result, sort_keys=True))
