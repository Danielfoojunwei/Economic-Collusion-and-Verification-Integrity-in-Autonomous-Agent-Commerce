#!/usr/bin/env python3
"""Read-only FEE015 role-swap readiness and explicit one-time assignment freeze.

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

from agent_economic_trust.fee015_budget import (  # noqa: E402
    FEE014_HOLD_USD, FEE014_STOP_RUN_ID, exact_prior_holds, same_usd_amount)
from agent_economic_trust.fee015_plan import (  # noqa: E402
    CANONICAL_LEDGER, ROWS, canonical, digest, make_schedule, per_row_reserve,
    prospective_manifest, required_headroom)
from agent_economic_trust.mpp005_plan import canonical_project_root  # noqa: E402
from agent_economic_trust.mpp008_pricing import pricing_snapshots  # noqa: E402
from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402

GATE = ROOT / "artifacts/gates/ERC8183_FEE015"
ASSIGNMENT = GATE / "assignment-001"
LOCK = GATE / "first-freeze.lock.json"
CLEARANCE = GATE / "cross-study-clearance-001.json"
REVIEW = ROOT / "artifacts/prospective/ERC8183_FEE015/source-review-001.json"
OFFLINE = ROOT / "artifacts/prospective/ERC8183_FEE015/offline-native-001"
FEE013_GATE = ROOT / "artifacts/gates/ERC8183_FEE013"
FEE013_REVIEW = FEE013_GATE / "independent-results-review-final.json"
FEE013_FINAL_COLLECTION_SHA = "2c83c30933cc585fc0bf83cd469a52d3ddc741bbab9dd17c75e0204189a1b9eb"
FEE013_REVIEW_SHA = "421e9f1019b51aad69d8e2c05927219331d8ee110633e8ec3f3f9f7310dc6aed"
PARTIAL013_GATE = ROOT / "artifacts/gates/ERC8183_PARTIAL_CLAIM013"
PARTIAL013_COLLECTION = PARTIAL013_GATE / "collection-001-after-first-stop.json"
PARTIAL013_FORENSICS = PARTIAL013_GATE / "forensics-001.json"
PARTIAL013_EPISODE = "partial013-180ff0b218ebdeed9cd48369"
PARTIAL013_RUN = PARTIAL013_GATE / "runs-001/episodes" / PARTIAL013_EPISODE
PARTIAL013_STOP = PARTIAL013_RUN / "STOPPED.json"
PARTIAL013_UNVERIFIED = PARTIAL013_RUN / "unverified_episode_record.json"
PARTIAL013_INSPECT = PARTIAL013_RUN / "inspect.eval"
PARTIAL013_NATIVE = PARTIAL013_RUN / "erc8183/native-evidence.json"
PARTIAL013_ASSIGNMENT_SHA = "e65e08ca3543ffad89d2afda23b7da8534162134925f3148fdc6c909f6e4d94a"
PARTIAL013_COLLECTION_SHA = "ef5da3955cc1848b95d26ca9f0a50ecac7fad1bb5d120c45fb4be6b1fa47519e"
PARTIAL013_FORENSICS_SHA = "7514ee740cb19b5504ed98d6c7a94e795c06ecabeb53e39f99d1ddb0aa881127"
PARTIAL013_STOP_SHA = "a803397505f5d7c9bb9139328bdfda8def07df49b27e0fd8e1301222d1a1dec5"
PARTIAL013_UNVERIFIED_SHA = "98f24466d75f9034c4b7771cd438b9f660a72cdd22cd231def4cbabeb1be09d9"
PARTIAL013_INSPECT_SHA = "fdba1eaeb225a7f09ab4c7d1d6f199d8a316ee16fe7aee9c6101bbaae15f0faf"
PARTIAL013_NATIVE_SHA = "fb3dd3f731fb3dfb220458b85cb0633a02e832ef4b7b86db310ceb71986525cd"
FEE014_GATE = ROOT / "artifacts/gates/ERC8183_FEE014"
FEE014_COLLECTION = FEE014_GATE / "collection-002-after-first-stop.json"
FEE014_FORENSICS = FEE014_GATE / "forensics-first-stop-001/report.json"
FEE014_EPISODE = "fee014-deb758472e05bb8622e9a1d6"
FEE014_RUN = FEE014_GATE / "runs-001/episodes" / FEE014_EPISODE
FEE014_STOP = FEE014_RUN / "STOPPED.json"
FEE014_INSPECT = FEE014_RUN / "inspect.eval"
FEE014_NATIVE = FEE014_RUN / "erc8183/native-partial.json"
FEE014_ASSIGNMENT_SHA = "d6409ff93bcbd1332aba4ad90b19953c045e9a3136383ea6fa30fe76ece3bfed"
FEE014_COLLECTION_SHA = "e929867f0e327bba854be8a53d8949ee097a1677adda4e7eb96f98d9ce38444f"
FEE014_FORENSICS_SHA = "3ab4ad292c0021124bc396c70400731100e866aa4749c667c2a9c1850b8aaa38"
FEE014_STOP_SHA = "f65fae3085a8b7cfc26da2eeb3945a982f93cdb4a770601fc3fac6c833051864"
FEE014_INSPECT_SHA = "a7970238ee8f78c3a41ef0c8fae836638f10986fb1cb2ad92e9f3eb97faa2838"
FEE014_NATIVE_SHA = "db2930e0d8240973de07f96dde9799cd23a19838d65b819c699be06384c656f8"
FEE014_CONTINGENT_EVIDENCE = ROOT / "artifacts/budget/fee014-first-stop-contingent-001/evidence.json"
FEE014_CONTINGENT_EVIDENCE_SHA = "22ca35d7dabb6d8ab87ecb2410c2f2f84a1ce22cc48eb18a7f703aa60c08d155"
FEE014_CONTINGENT_REVIEW = ROOT / "artifacts/budget/fee014-first-stop-contingent-001/independent-review.json"
FEE014_CONTINGENT_REVIEW_SHA = "a4b11d2c7181d76138827b50f318b82f8e2fcde3f368eb42928a11c017c2ec0a"
FEE014_CONTINGENT_LEDGER_HASH = "74ee7d2e4feab7734a88e9730fc29963702018cbe6f94895a4e90d78129532f1"

DEPENDENCIES = (
    "AGENTS.md", "UPSTREAM_PINNED.json",
    "docs/PROSPECTIVE_FEE_ROLE_SWAP_REPLICATION_2026-10-15.md",
    "scripts/run_erc8183_local.py", "scripts/run_erc8183_fee_control.py",
    "scripts/verify_erc8183_fee_control.py",
    "scripts/verify_erc8183_fee_readiness.py",
    "scripts/freeze_x402_live012.py",
    "src/agent_economic_trust/ap2_live_fixture.py",
    "src/agent_economic_trust/open004_task.py",
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
    "scripts/fee013_collect.py",
    "scripts/fee013_freeze.py",
    "scripts/verify_fee013_offline.py",
    "src/agent_economic_trust/fee013_budget.py",
    "src/agent_economic_trust/fee013_offline.py",
    "src/agent_economic_trust/fee013_plan.py",
    "src/agent_economic_trust/fee013_remote.py",
    "src/agent_economic_trust/fee013_task.py",
    "src/agent_economic_trust/fee013_boundary.py",
    "src/agent_economic_trust/fee012_offline.py",
    "src/agent_economic_trust/fee012_plan.py",
    "scripts/partial_claim_collect.py",
    "scripts/partial_claim_freeze.py",
    "src/agent_economic_trust/partial_claim_boundary.py",
    "src/agent_economic_trust/partial_claim_budget.py",
    "src/agent_economic_trust/partial_claim_native.py",
    "src/agent_economic_trust/partial_claim_native_verifier.py",
    "src/agent_economic_trust/partial_claim_offline.py",
    "src/agent_economic_trust/partial_claim_plan.py",
    "src/agent_economic_trust/partial_claim_remote.py",
    "src/agent_economic_trust/partial_claim_task.py",
    "scripts/fee014_collect.py", "scripts/fee014_freeze.py",
    "scripts/verify_fee014_offline.py", "scripts/run_fee014.py",
    "src/agent_economic_trust/fee014_budget.py",
    "src/agent_economic_trust/fee014_offline.py",
    "src/agent_economic_trust/fee014_plan.py",
    "src/agent_economic_trust/fee014_remote.py",
    "src/agent_economic_trust/fee014_task.py",
    "src/agent_economic_trust/fee014_boundary.py",
)


def sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("FEE015 sealed evidence missing or symlinked")
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
        raise ValueError("FEE015 can freeze only in canonical shared-ledger checkout")


def source_names() -> tuple[str, ...]:
    fresh = [str(path.relative_to(ROOT)) for pattern in (
        "src/agent_economic_trust/fee015*.py", "scripts/*fee015*.py",
        "tests/test_fee015*.py", "docs/*FEE015*.md")
        for path in ROOT.glob(pattern)]
    return tuple(sorted(set(DEPENDENCIES) | set(fresh)))


def source_inventory() -> dict[str, str]:
    names = source_names()
    if not all((ROOT / name).is_file() for name in names):
        raise ValueError("FEE015 source closure file missing")
    return {name: sha(ROOT / name) for name in names}


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
    if (REVIEW.is_symlink() or review.get("schema") != "fee015-source-review-v1"
            or review.get("status") != "GO_SOURCE_MERGE_ONLY"
            or review.get("source_inventory_sha256") != digest(sources)
            or review.get("reviewer_id") in (None, "", "/root/fee015_successor",
                                               "/root/fee015_runtime",
                                               "/root/fee015_implementer",
                                               "/root/role_swap_live_implementation")
            or review.get("freeze_or_paid_authorization") is not False):
        raise ValueError("independent FEE015 source review differs")
    return {"path": str(REVIEW.relative_to(ROOT)), "sha256": sha(REVIEW),
            "reviewer_id": review["reviewer_id"]}


def _runtime() -> dict:
    from scripts.verify_erc8183_fee_readiness import installed_runtime_versions
    versions = installed_runtime_versions()
    if version("orbit") != "1.0.3" or version("inspect_ai") != "0.3.263":
        raise ValueError("pinned ORBIT or Inspect runtime differs")
    return versions


def _offline() -> dict:
    from scripts.verify_fee015_offline import verify
    report = verify(OFFLINE)
    if report.get("status") != "PASS" or report.get("paid_model_calls") != 0:
        raise ValueError("FEE015 official native controls not replayed")
    return {"report_sha256": sha(OFFLINE / "report.json"),
            "status": report["status"], "paid_model_calls": 0}


def _ledger() -> dict:
    state = BudgetLedger(CANONICAL_LEDGER).snapshot()
    if (state.get("cap_usd") != "50" or state.get("blocked")
            or state.get("unknown_run_ids")):
        raise ValueError("FEE015 USD50 ledger is blocked")
    exact_prior_holds(state)
    return state


def _fee013_terminal_collection() -> tuple[Path, dict]:
    """Find one archived terminal predecessor denominator; never select a partial result."""
    paths = sorted(FEE013_GATE.glob("collection-*.json"))
    final = []
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError("FEE013 collection archive is symlinked or missing")
        saved = json.loads(path.read_bytes())
        if saved.get("schema") != "fee013-itt-collection-v1":
            continue
        if saved.get("planned_episodes") != 6 or len(saved.get("rows", [])) != 6:
            raise ValueError("FEE013 assigned denominator differs")
        complete = saved.get("completed_episodes", 0)
        stopped = saved.get("stopped_episodes", 0)
        pending = saved.get("pending_episodes", 0)
        incomplete = saved.get("observed_incomplete_episodes", 0)
        if complete + stopped + pending + incomplete != 6:
            raise ValueError("FEE013 collection counts differ")
        if (complete + incomplete == 6 and stopped == pending == 0
                or stopped == 1 and pending == 5 - complete - incomplete):
            final.append((path, saved))
    if len(final) != 1:
        raise ValueError("exactly one terminal FEE013 collection required")
    return final[0]


def _partial013_stopped_clearance(state: dict) -> dict:
    """Bind the intervening five-row technical stop and replay its native refund."""
    from agent_economic_trust.partial_claim_native_verifier import verify_file
    from scripts.partial_claim_collect import collect as collect_partial
    from scripts.partial_claim_freeze import load_assignment, verify_static

    paths = ((PARTIAL013_COLLECTION, PARTIAL013_COLLECTION_SHA),
             (PARTIAL013_FORENSICS, PARTIAL013_FORENSICS_SHA),
             (PARTIAL013_STOP, PARTIAL013_STOP_SHA),
             (PARTIAL013_UNVERIFIED, PARTIAL013_UNVERIFIED_SHA),
             (PARTIAL013_INSPECT, PARTIAL013_INSPECT_SHA),
             (PARTIAL013_NATIVE, PARTIAL013_NATIVE_SHA))
    if any(sha(path) != expected for path, expected in paths):
        raise ValueError("PARTIAL013 immutable first-stop archive differs")
    verify_static()
    frozen, assignment_sha, rows = load_assignment()
    if (assignment_sha != PARTIAL013_ASSIGNMENT_SHA
            or len(rows) != 5 or rows[0].episode_id != PARTIAL013_EPISODE
            or rows[0].truth != "bad" or rows[0].fee_term != "NATIVE_CONTINGENT"
            or rows[0].contact != "NO_CONTACT"):
        raise ValueError("PARTIAL013 frozen assignment or first cell differs")
    saved = json.loads(PARTIAL013_COLLECTION.read_bytes())
    replay = collect_partial()
    replay["shared_ledger_seq"] = saved.get("shared_ledger_seq")
    if (saved != replay or saved.get("schema") != "partial013-itt-collection-v1"
            or saved.get("study") != frozen["study"]
            or saved.get("assignment_manifest_sha256") != assignment_sha
            or saved.get("planned_episodes") != 5
            or saved.get("completed_episodes") != 0
            or saved.get("stopped_episodes") != 1
            or saved.get("pending_episodes") != 4
            or saved.get("observed_incomplete_episodes") != 0
            or [item.get("status") for item in saved.get("rows", [])]
               != ["STOPPED", "PENDING", "PENDING", "PENDING", "PENDING"]
            or [item.get("episode_id") for item in saved["rows"]]
               != [row.episode_id for row in rows]):
        raise ValueError("PARTIAL013 STOPPED denominator or independent replay differs")
    stop = json.loads(PARTIAL013_STOP.read_bytes())
    unverified = json.loads(PARTIAL013_UNVERIFIED.read_bytes())
    forensic = json.loads(PARTIAL013_FORENSICS.read_bytes())
    native = verify_file(PARTIAL013_NATIVE, rows[0])
    run_id = "partial013-" + assignment_sha[:12] + "-" + PARTIAL013_EPISODE
    run = state["runs"].get(run_id)
    if (stop.get("schema") != "partial013-stopped-episode-v1"
            or stop.get("episode_id") != PARTIAL013_EPISODE
            or stop.get("assignment_manifest_sha256") != assignment_sha
            or stop.get("budget_state") != "SETTLED"
            or stop.get("ledger_status_at_stop") != "SETTLED"
            or stop.get("ledger_run_id") != run_id
            or stop.get("no_retry_or_substitution") is not True
            or stop.get("complete_native_claim") is not False
            or unverified.get("schema") != "partial013-paid-episode-v1"
            or unverified.get("episode_id") != PARTIAL013_EPISODE
            or unverified.get("assignment_manifest_sha256") != assignment_sha
            or unverified.get("ledger_run_id") != run_id
            or unverified.get("inspect_sha256") != PARTIAL013_INSPECT_SHA
            or unverified.get("native_sha256") != PARTIAL013_NATIVE_SHA
            or unverified.get("native_path") != "erc8183/native-evidence.json"
            or not isinstance(run, dict) or run.get("status") != "SETTLED"
            or run.get("metadata", {}).get("assignment_sha") != assignment_sha
            or run.get("metadata", {}).get("episode_id") != PARTIAL013_EPISODE
            or run.get("evidence_ref") != "sha256:" + PARTIAL013_INSPECT_SHA
            or not same_usd_amount(run.get("actual_usd"),
                                   unverified.get("model_cost_usd"))
            or not same_usd_amount(run.get("actual_usd"), "0.123222")
            or set(ident for ident in state["runs"] if ident.startswith("partial013-"))
               != {run_id}):
        raise ValueError("PARTIAL013 technical stop or shared ledger differs")
    if (native.get("status") != "COMPLETE_VERIFIED"
            or native.get("terminal_verdict") != "REJECT"
            or native.get("first_provider_paid_minor") != 0
            or native.get("first_evaluator_fee_minor") != 0
            or native.get("final_provider_paid_minor") != 0
            or native.get("final_evaluator_fee_minor") != 0
            or native.get("client_refund_minor") != 20_000_000
            or native.get("cumulative_client_outlay_minor") != 0):
        raise ValueError("PARTIAL013 first-stop native refund or payout differs")
    archived = forensic.get("archive_sha256", {})
    if (forensic.get("schema") != "partial013-independent-first-stop-forensics-v1"
            or forensic.get("status") != "STOPPED"
            or forensic.get("assignment_manifest_sha256") != assignment_sha
            or forensic.get("collection_path") != str(PARTIAL013_COLLECTION.relative_to(ROOT))
            or forensic.get("collection_sha256") != PARTIAL013_COLLECTION_SHA
            or forensic.get("episode_id") != PARTIAL013_EPISODE
            or forensic.get("assigned_denominator") != {
                "planned": 5, "complete": 0, "stopped": 1, "pending": 4,
                "no_retry_or_substitution": True}
            or archived.get("STOPPED.json") != PARTIAL013_STOP_SHA
            or archived.get("unverified_episode_record.json") != PARTIAL013_UNVERIFIED_SHA
            or archived.get("inspect.eval") != PARTIAL013_INSPECT_SHA
            or archived.get("erc8183/native-evidence.json") != PARTIAL013_NATIVE_SHA
            or forensic.get("independent_replay", {}).get("failed_tool_events") != 1
            or forensic.get("independent_replay", {}).get("failed_tool", {}).get("function")
               != "buy_early_buyer_check"
            or forensic.get("native_receipt_replay", {}).get("verifier_status")
               != native["status"]
            or forensic.get("interpretation", {}).get("bilateral_collusion_observed")
               is not False
            or forensic.get("shared_budget", {}).get("run_id") != run_id
            or forensic.get("shared_budget", {}).get("run_status") != "SETTLED"
            or not same_usd_amount(forensic.get("shared_budget", {}).get(
                "settled_usage_estimate_usd"), run["actual_usd"])):
        raise ValueError("PARTIAL013 independent first-stop forensics differs")
    return {"assignment_manifest_sha256": assignment_sha,
            "collection_sha256": PARTIAL013_COLLECTION_SHA,
            "forensics_sha256": PARTIAL013_FORENSICS_SHA,
            "stopped_sha256": PARTIAL013_STOP_SHA,
            "inspect_sha256": PARTIAL013_INSPECT_SHA,
            "native_sha256": PARTIAL013_NATIVE_SHA,
            "ledger_run_id": run_id,
            "ledger_actual_usage_estimate_usd": run["actual_usd"],
            "native_status": native["status"],
            "native_terminal_verdict": native["terminal_verdict"],
            "native_client_refund_minor": native["client_refund_minor"],
            "native_provider_gain_minor": 0,
            "completed_episodes": 0, "stopped_episodes": 1,
            "pending_episodes": 4}


def _fee014_stopped_clearance(state: dict) -> dict:
    """Bind the distinct predecessor's immutable denominator and failed call."""
    from inspect_ai.log import read_eval_log
    from agent_economic_trust.erc8183_fee_native_verifier import verify_file
    from scripts.fee014_collect import verify_episode
    from scripts.fee014_freeze import load_assignment

    archives = ((FEE014_COLLECTION, FEE014_COLLECTION_SHA),
                (FEE014_FORENSICS, FEE014_FORENSICS_SHA),
                (FEE014_STOP, FEE014_STOP_SHA),
                (FEE014_INSPECT, FEE014_INSPECT_SHA),
                (FEE014_NATIVE, FEE014_NATIVE_SHA),
                (FEE014_CONTINGENT_EVIDENCE, FEE014_CONTINGENT_EVIDENCE_SHA),
                (FEE014_CONTINGENT_REVIEW, FEE014_CONTINGENT_REVIEW_SHA))
    if any(sha(path) != expected for path, expected in archives):
        raise ValueError("FEE014 immutable first-stop archive differs")
    frozen, assignment_sha, rows = load_assignment()
    sealed_sources = frozen.get("source_sha256")
    source_review = frozen.get("independent_source_review")
    if (not isinstance(sealed_sources, dict)
            or len(sealed_sources) != 58
            or any(sha(ROOT / name) != expected
                   for name, expected in sealed_sources.items())
            or frozen.get("source_inventory_sha256") != digest(sealed_sources)
            or not isinstance(source_review, dict)
            or source_review.get("path") !=
                "artifacts/prospective/ERC8183_FEE014/source-review-001.json"
            or source_review.get("sha256") != sha(ROOT / source_review["path"])
            or json.loads((ROOT / source_review["path"]).read_bytes()).get(
                "source_inventory_sha256") != frozen["source_inventory_sha256"]):
        raise ValueError("FEE014 original 58-file sealed source inventory changed")
    saved = json.loads(FEE014_COLLECTION.read_bytes())
    forensic = json.loads(FEE014_FORENSICS.read_bytes())
    billing_evidence = json.loads(FEE014_CONTINGENT_EVIDENCE.read_bytes())
    billing_review = json.loads(FEE014_CONTINGENT_REVIEW.read_bytes())
    stop = json.loads(FEE014_STOP.read_bytes())
    run = state["runs"].get(FEE014_STOP_RUN_ID)
    native = verify_file(FEE014_NATIVE, rows[1])
    log = read_eval_log(str(FEE014_INSPECT), resolve_attachments=True)
    events = [(i, e) for i, e in enumerate(log.samples[0].events)
              if e.event == "model"]
    failure = [(i, e) for i, e in events if e.error]
    first = FEE014_GATE / "runs-001/episodes" / rows[0].episode_id
    if (assignment_sha != FEE014_ASSIGNMENT_SHA
            or frozen["study"] != "erc8183-native-evaluator-fee-role-swap-live-014"
            or len(rows) != 5 or rows[1].episode_id != FEE014_EPISODE
            or (rows[1].truth, rows[1].fee_term, rows[1].contact)
               != ("bad", "NATIVE_CONTINGENT", "NO_CONTACT")
            or saved.get("schema") != "fee014-itt-collection-v1"
            or saved.get("assignment_manifest_sha256") != assignment_sha
            or [item.get("status") for item in saved.get("rows", [])]
               != ["COMPLETE", "STOPPED", "PENDING", "PENDING", "PENDING"]
            or [item.get("episode_id") for item in saved["rows"]]
               != [row.episode_id for row in rows]
            or any((FEE014_GATE / "runs-001/episodes" / row.episode_id).exists()
                   for row in rows[2:])
            or saved["rows"][0] != verify_episode(
                rows[0], first, assignment_sha=assignment_sha, ledger=state)
            or stop.get("schema") != "fee014-stopped-episode-v1"
            or stop.get("episode_id") != FEE014_EPISODE
            or stop.get("assignment_manifest_sha256") != assignment_sha
            or stop.get("budget_state") != "UNKNOWN"
            or stop.get("no_retry_or_substitution") is not True
            or stop.get("complete_native_claim") is not False
            or stop.get("ledger_run_id") != FEE014_STOP_RUN_ID
            or native.get("status") != "FUNDED_SUBMITTED_VERIFIED"
            or native.get("checked") is not True
            or native.get("native_terminal_claim") is not False
            or log.status != "error" or len(log.samples or []) != 1
            or len(events) != 5 or len(failure) != 1
            or failure[0][0] != 82
            or getattr(failure[0][1].input[-1], "role", None) != "assistant"
            or "does not support assistant message prefill" not in
                str(failure[0][1].error)
            or forensic.get("schema") != "fee014-independent-first-stop-forensics-v1"
            or forensic.get("reviewer_id") in (None, "", "/root/fee015_successor")
            or forensic.get("assigned_denominator") != {
                "planned": 5, "complete": 1, "stopped": 1,
                "pending": 3, "row_status": "STOPPED",
                "no_retry_or_substitution": True}
            or forensic.get("immutable_evidence_sha256", {}).get(
                "collection-002-after-first-stop.json") != FEE014_COLLECTION_SHA
            or forensic.get("immutable_evidence_sha256", {}).get(
                "inspect.eval") != FEE014_INSPECT_SHA
            or forensic.get("native_replay", {}).get("terminal_verdict") is not None
            or forensic.get("scientific_disposition", {}).get(
                "bilateral_collusion_eligible") is not False
            or not isinstance(run, dict) or run.get("status") != "CONTINGENT"
            or Decimal(run.get("reserved_usd", "-1")) != FEE014_HOLD_USD
            or run.get("evidence_ref") != "sha256:" + FEE014_CONTINGENT_EVIDENCE_SHA
            or run.get("contingent_evidence_ref") != "sha256:" + FEE014_CONTINGENT_EVIDENCE_SHA
            or run.get("metadata", {}).get("assignment_sha") != assignment_sha
            or run.get("metadata", {}).get("episode_id") != FEE014_EPISODE
            or billing_evidence.get("schema") != "fee014-first-stop-provisional-billing-v1"
            or billing_evidence.get("run_id") != FEE014_STOP_RUN_ID
            or billing_evidence.get("attributable_final_provider_bill_usd") is not None
            or billing_evidence.get("retained_run_reservation_usd") != str(FEE014_HOLD_USD)
            or billing_review.get("schema") != "fee014-provisional-billing-independent-review-v1"
            or billing_review.get("decision") != "GO_FOR_ONE_CANONICAL_UNKNOWN_TO_CONTINGENT_TRANSITION"
            or billing_review.get("reviewed_artifacts_sha256", {}).get(
                str(FEE014_CONTINGENT_EVIDENCE.relative_to(ROOT)))
               != FEE014_CONTINGENT_EVIDENCE_SHA
            or billing_review.get("verification", {}).get("expected_post_transition_seq") != 194):
        raise ValueError("FEE014 first-stop forensic, terminal status or hold differs")
    at_stop = forensic["shared_budget"]
    lines = CANONICAL_LEDGER.read_bytes().splitlines()
    if (at_stop.get("ledger_seq") != 193
            or json.loads(lines[193])["hash"] != at_stop.get("ledger_last_hash")
            or len(lines) <= 194
            or json.loads(lines[194])["hash"] != FEE014_CONTINGENT_LEDGER_HASH
            or state["seq"] < 194
            or at_stop.get("run_status") != "UNKNOWN"):
        raise ValueError("FEE014 forensic ledger snapshot is not an ancestor")
    return {"assignment_manifest_sha256": assignment_sha,
            "collection_sha256": FEE014_COLLECTION_SHA,
            "forensics_sha256": FEE014_FORENSICS_SHA,
            "stop_sha256": FEE014_STOP_SHA,
            "inspect_sha256": FEE014_INSPECT_SHA,
            "native_sha256": FEE014_NATIVE_SHA,
            "contingent_evidence_sha256": FEE014_CONTINGENT_EVIDENCE_SHA,
            "contingent_independent_review_sha256": FEE014_CONTINGENT_REVIEW_SHA,
            "contingent_ledger_ancestor_hash": FEE014_CONTINGENT_LEDGER_HASH,
            "ledger_run_id": FEE014_STOP_RUN_ID,
            "full_contingent_reservation_usd": str(FEE014_HOLD_USD),
            "native_status": native["status"],
            "completed_episodes": 1, "stopped_episodes": 1,
            "pending_episodes": 3}


def clearance_preview(state: dict) -> dict:
    """Replay FEE013, PARTIAL013, and the intervening FEE014 stop."""
    from agent_economic_trust.erc8183_fee_native_verifier import verify_file
    from scripts.fee013_collect import collect as collect_fee013
    from scripts.fee013_freeze import load_assignment, verify_static

    verify_static()
    frozen, fee013_sha, fee013_rows = load_assignment()
    path, saved = _fee013_terminal_collection()
    if (path.name != "collection-006-final.json"
            or sha(path) != FEE013_FINAL_COLLECTION_SHA
            or sha(FEE013_REVIEW) != FEE013_REVIEW_SHA):
        raise ValueError("FEE013 final archive or independent review hash differs")
    review = json.loads(FEE013_REVIEW.read_bytes())
    if (review.get("schema") != "fee013-independent-results-review-v1"
            or review.get("status") != "GO_FOR_SUCCESSOR_ONLY"
            or review.get("assignment_manifest_sha256") != fee013_sha
            or review.get("collection_path") != str(path.relative_to(ROOT))
            or review.get("collection_sha256") != sha(path)
            or review.get("denominator", {}).get("assigned") != 6
            or review.get("denominator", {}).get("complete") != 6
            or review.get("denominator", {}).get("stopped") != 0
            or review.get("freeze_or_paid_authorization") is not False):
        raise ValueError("FEE013 independent final review or archive differs")
    replay = collect_fee013()
    replay["shared_ledger_seq"] = saved.get("shared_ledger_seq")
    if (saved != replay
            or saved.get("assignment_manifest_sha256") != fee013_sha
            or saved.get("study") != frozen["study"]
            or [item["episode_id"] for item in saved["rows"]]
               != [row.episode_id for row in fee013_rows]):
        raise ValueError("FEE013 terminal collection fails independent replay")
    stopped_receipts = {}
    for row, result in zip(fee013_rows, saved["rows"]):
        if result["status"] != "STOPPED":
            continue
        directory = FEE013_GATE / "runs-001/episodes" / row.episode_id
        stop = directory / "STOPPED.json"
        candidates = [directory / "erc8183" / name
                      for name in ("native-evidence.json", "native-partial.json")
                      if (directory / "erc8183" / name).is_file()]
        if len(candidates) != 1:
            raise ValueError("FEE013 stopped row needs one native receipt")
        native = verify_file(candidates[0], row)
        if native["status"] not in {"COMPLETE_VERIFIED", "FUNDED_SUBMITTED_VERIFIED"}:
            raise ValueError("FEE013 stopped native receipt unverified")
        stopped_receipts[row.episode_id] = {
            "stop_sha256": sha(stop),
            "native_path": str(candidates[0].relative_to(ROOT)),
            "native_sha256": sha(candidates[0]),
            "native_status": native["status"],
            "ledger_run_id": json.loads(stop.read_bytes())["ledger_run_id"],
        }
    partial = _partial013_stopped_clearance(state)
    fee014 = _fee014_stopped_clearance(state)
    exact = exact_prior_holds(state)
    return {"schema": "fee015-cross-study-clearance-v3",
            "status": "GO_AFTER_FEE013_PARTIAL013_AND_FEE014_STOP",
            "fee013_assignment_sha256": fee013_sha,
            "fee013_collection_path": str(path.relative_to(ROOT)),
            "fee013_collection_sha256": sha(path),
            "fee013_independent_review_sha256": sha(FEE013_REVIEW),
            "fee013_completed_episodes": saved["completed_episodes"],
            "fee013_stopped_episodes": saved["stopped_episodes"],
            "fee013_pending_episodes": saved["pending_episodes"],
            "fee013_stopped_receipts": stopped_receipts,
            "partial013_first_stop": partial,
            "fee014_first_stop": fee014,
            "exact_prior_holds": exact,
            "ledger_at_clearance": {key: state[key] for key in
                                    ("seq", "last_hash", "cap_usd")},
            "no_new_paid_calls_authorized_by_clearance": True}


def write_clearance() -> dict:
    _canonical_root()
    if os.environ.get("FEE015_CLEARANCE_ALLOWED") != "true":
        raise ValueError("explicit FEE015 predecessor clearance switch required")
    if CLEARANCE.exists() or ASSIGNMENT.exists() or LOCK.exists():
        raise FileExistsError("FEE015 clearance/freeze already exists")
    state = _ledger()
    payload = clearance_preview(state)
    if BudgetLedger(CANONICAL_LEDGER).snapshot()["last_hash"] != state["last_hash"]:
        raise ValueError("ledger changed during FEE015 clearance")
    GATE.mkdir(parents=True, exist_ok=True)
    _new(CLEARANCE, _json(payload))
    return {"status": "CLEARANCE_SAVED_NO_PAID_CALL", "sha256": sha(CLEARANCE)}


def clearance(state: dict) -> dict:
    saved = json.loads(CLEARANCE.read_bytes())
    if CLEARANCE.is_symlink():
        raise ValueError("FEE015 clearance symlinked")
    original = saved.get("ledger_at_clearance")
    if (not isinstance(original, dict) or type(original.get("seq")) is not int
            or original["seq"] < 0 or original.get("cap_usd") != "50"
            or original["seq"] > state["seq"]):
        raise ValueError("FEE015 clearance ledger ancestor differs")
    lines = CANONICAL_LEDGER.read_bytes().splitlines()
    if (len(lines) <= original["seq"]
            or json.loads(lines[original["seq"]])["hash"] != original["last_hash"]):
        raise ValueError("FEE015 clearance ledger hash is not ancestor")
    preview = clearance_preview(state)
    preview["ledger_at_clearance"] = original
    if saved != preview:
        raise ValueError("FEE015 predecessor clearance bytes/facts differ")
    return {"path": str(CLEARANCE.relative_to(ROOT)), "sha256": sha(CLEARANCE),
            "ledger_at_clearance": original}


def _budget(state: dict, prices: dict) -> dict:
    per = per_row_reserve(prices)
    needed = required_headroom(prices, ROWS)
    if needed > Decimal(state["available_usd"]):
        raise ValueError("full five-row FEE015 block plus contingency exceeds USD50")
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
    if os.environ.get("FEE015_FREEZE_ALLOWED") != "true":
        raise ValueError("explicit FEE015 one-time freeze switch required")
    if LOCK.exists() or ASSIGNMENT.exists():
        raise FileExistsError("FEE015 already or partially frozen; no reroll")
    if readiness()["status"] != "READY":
        raise ValueError("FEE015 readiness has uncleared gates")
    state = _ledger()
    sources, runtime, offline = source_inventory(), _runtime(), _offline()
    review, prior = source_review(sources), clearance(state)
    prices = pricing_snapshots()
    seed = seed_hex if seed_hex is not None else secrets.token_hex(32)
    rows = make_schedule(seed)
    payload = {**prospective_manifest(seed, rows),
               "schema": "fee015-first-assignment-v1",
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
        raise ValueError("shared ledger changed during FEE015 freeze")
    GATE.mkdir(parents=True, exist_ok=True)
    ASSIGNMENT.mkdir(mode=0o700)
    _new(ASSIGNMENT / "seed.hex", (seed + "\n").encode())
    _new(ASSIGNMENT / "private_rows.json", _json([asdict(row) for row in rows]))
    _new(ASSIGNMENT / "assignment_manifest.json", _json(payload))
    lock = {"schema": "fee015-one-time-freeze-v1",
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
        raise ValueError("FEE015 private rows differ from one-time seed")
    manifest = ASSIGNMENT / "assignment_manifest.json"
    frozen = json.loads(manifest.read_bytes())
    preview = prospective_manifest(seed, rows)
    for key, value in preview.items():
        if key not in {"schema", "status"} and frozen.get(key) != value:
            raise ValueError("FEE015 frozen assignment differs from seed preview")
    if (frozen.get("schema") != "fee015-first-assignment-v1"
            or frozen.get("status") != "FROZEN_NOT_EXECUTED"
            or json.loads(LOCK.read_bytes()) != {
                "schema": "fee015-one-time-freeze-v1",
                "assignment_manifest_sha256": sha(manifest),
                "seed_commitment_sha256": frozen["seed_commitment_sha256"]}):
        raise ValueError("FEE015 one-time manifest/lock differs")
    return frozen, sha(manifest), rows


def verify_static() -> dict:
    _canonical_root()
    frozen, assignment_sha, rows = load_assignment()
    sealed = frozen.get("source_sha256")
    if not isinstance(sealed, dict) or not sealed:
        raise ValueError("FEE015 sealed source inventory missing")
    # The one-time freeze locks an explicit set. Future forensic/billing files
    # must not make a completed run unverifiable merely by matching a glob.
    sources = {name: sha(ROOT / name) for name in sealed}
    if (frozen["source_sha256"] != sources
            or frozen["source_inventory_sha256"] != digest(sources)
            or frozen["independent_source_review"] != source_review(sources)
            or frozen["offline_readiness"] != _offline()):
        raise ValueError("FEE015 sealed source, review or native controls changed")
    prior = frozen["cross_study_clearance"]
    if (prior["sha256"] != sha(CLEARANCE)
            or prior["path"] != str(CLEARANCE.relative_to(ROOT))):
        raise ValueError("FEE015 predecessor clearance changed")
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
        raise ValueError("FEE015 frozen ledger predecessor differs")
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
