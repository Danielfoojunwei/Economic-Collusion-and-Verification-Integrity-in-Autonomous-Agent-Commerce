#!/usr/bin/env python3
"""Read-only PRESSURE016 gates and a guarded one-time future assignment freeze.

The source preview deliberately has no frozen assignment. A paid run requires
PARTIAL014 final collection and independent review, this study's independent
source review, a separate canonical cross-study clearance, fresh full-block
USD50 headroom, and the explicit one-time freeze switch.
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

from agent_economic_trust.mpp005_plan import canonical_project_root  # noqa: E402
from agent_economic_trust.mpp008_pricing import pricing_snapshots  # noqa: E402
from agent_economic_trust.partial014_budget import exact_prior_holds  # noqa: E402
from agent_economic_trust.partial014_plan import per_row_reserve  # noqa: E402
from agent_economic_trust.pressure016_plan import (  # noqa: E402
    CANONICAL_LEDGER, CELLS, NATIVE_CONTINGENT, ROWS, SOL, SONNET, digest,
    make_schedule, prospective_manifest, required_headroom)
from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402
from scripts.partial014_freeze import (  # noqa: E402
    source_names as partial014_source_names)

GATE = ROOT / "artifacts/gates/ERC8183_PRESSURE016"
ASSIGNMENT = GATE / "assignment-001"
LOCK = GATE / "first-freeze.lock.json"
CLEARANCE = GATE / "cross-study-clearance-001.json"
REVIEW = ROOT / "artifacts/prospective/ERC8183_PRESSURE016/source-review-001.json"
PARTIAL014_GATE = ROOT / "artifacts/gates/ERC8183_PARTIAL_CLAIM014"
PARTIAL014_REVIEW = PARTIAL014_GATE / "independent-results-review-final.json"
PARTIAL014_REVIEW_SHA = "a06747a5ac8ac8c64488cd059352b4e9d5cefcf92c07ee4e088d020f208dbcd5"
PARTIAL014_REVIEW_STATUS = (
    "REVIEW_COMPLETE_TWO_UNSUCCESSFUL_UNILATERAL_SOLICITATIONS_NO_BILATERAL_COLLUSION")
OFFLINE = ROOT / "artifacts/prospective/ERC8183_PRESSURE016/offline-native-001"
PARTIAL014_OFFLINE = ROOT / "artifacts/prospective/ERC8183_PARTIAL_CLAIM014/offline-native-001"
XHIGH017_GATE = ROOT / "artifacts/gates/ERC8183_XHIGH017"
XHIGH017_FIRST_STOP = XHIGH017_GATE / "independent-first-stop-forensics-001.json"
XHIGH017_FIRST_STOP_SHA = "66b0c983ebc587380fcaaad8ce8f16a4f9b169684981385b3df0512751780e17"
XHIGH017_ASSIGNMENT_SHA = "a0f79e6ba7de1c1b0bee28e39e9d70165405f325d9a52a9c0b2f432708b2237b"
XHIGH017_COLLECTION_SHA = "eefd7c61b9b8667a3923a8979c78226e8433488f9a032e537b11f418633e95ec"
XHIGH017_RUN_ID = "xhigh017-a0f79e6ba7de-xhigh017-0a63961c0d306890326609f6"
XHIGH017_FULL_HOLD_USD = Decimal("4.718592")
XHIGH017_BILLING = ROOT / "artifacts/budget/xhigh017-first-stop-contingent-001"
XHIGH017_BILLING_EVIDENCE = XHIGH017_BILLING / "evidence.json"
XHIGH017_BILLING_EVIDENCE_SHA = "53bdf0afe52a99f0ee18ab48772fac41b1a7054cb3b8f34386d392205c9ca009"
XHIGH017_BILLING_REVIEW = XHIGH017_BILLING / "independent-review.json"
XHIGH017_BILLING_REVIEW_SHA = "d68a3672042052c7c28eb000538d831a7f1e6fb757b2b0800c44bcc66ee09bd2"
OWN_SOURCE = (
    "src/agent_economic_trust/pressure016_plan.py",
    "src/agent_economic_trust/pressure016_task.py",
    "src/agent_economic_trust/pressure016_boundary.py",
    "src/agent_economic_trust/pressure016_offline.py",
    "src/agent_economic_trust/pressure016_remote.py",
    "scripts/pressure016_collect.py",
    "scripts/pressure016_freeze.py",
    "scripts/run_pressure016.py",
    "tests/test_pressure016_source.py",
    "docs/PROSPECTIVE_ERC8183_PRESSURE016_DESIGN.md",
)


def sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"PRESSURE016 sealed evidence missing or symlinked: {path}")
    return sha256(path.read_bytes()).hexdigest()


def _json(value: object) -> bytes:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"


def _new(path: Path, payload: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _canonical_root() -> None:
    if ROOT.resolve() != canonical_project_root().resolve():
        raise ValueError("PRESSURE016 freeze requires canonical shared-ledger checkout")


def source_names() -> tuple[str, ...]:
    return tuple(sorted(set(partial014_source_names()) | set(OWN_SOURCE)))


def source_inventory() -> dict[str, str]:
    return {name: sha(ROOT / name) for name in source_names()}


def frozen_source_inventory(sealed: dict[str, str]) -> dict[str, str]:
    """Use exactly the sealed path set even when later studies add files."""
    if (not isinstance(sealed, dict) or not sealed
            or any(not isinstance(name, str) or not isinstance(expected, str)
                   or Path(name).is_absolute() or ".." in Path(name).parts
                   or len(expected) != 64 for name, expected in sealed.items())):
        raise ValueError("PRESSURE016 frozen source inventory malformed")
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
    saved = json.loads(REVIEW.read_bytes())
    if (REVIEW.is_symlink()
            or saved.get("schema") != "pressure016-live-source-review-v1"
            or saved.get("status") != "GO_SOURCE_MERGE_ONLY"
            or saved.get("source_inventory_sha256") != digest(sources)
            or saved.get("reviewer_id") in (None, "", "/root", "/root/pressure016_source")
            or saved.get("freeze_or_paid_authorization") is not False):
        raise ValueError("PRESSURE016 independent source review differs")
    return {"path": str(REVIEW.relative_to(ROOT)), "sha256": sha(REVIEW),
            "reviewer_id": saved["reviewer_id"]}


def _runtime() -> dict:
    from scripts.verify_erc8183_fee_readiness import installed_runtime_versions
    if version("orbit") != "1.0.3" or version("inspect_ai") != "0.3.263":
        raise ValueError("pinned ORBIT or Inspect runtime differs")
    return installed_runtime_versions()


def _offline() -> dict:
    from agent_economic_trust.partial014_offline import verify as verify_partial014
    from agent_economic_trust.pressure016_offline import verify as verify_pressure016
    prior = verify_partial014(PARTIAL014_OFFLINE)
    result = verify_pressure016(OFFLINE)
    if (prior.get("status") != "PASS" or prior.get("paid_model_calls") != 0
            or prior.get("scripted_native_cases_reverified") != 11
            or prior.get("tamper_negatives_reverified") != 19
            or result.get("status") != "PASS" or result.get("paid_model_calls") != 0
            or result.get("scripted_native_cases_reverified") != 4
            or result.get("scripted_bad_early_approval_controls") != 2
            or result.get("tamper_negatives_reverified") != 4):
        raise ValueError("PRESSURE016 official native positive/negative controls differ")
    return {"path": str((OFFLINE / "report.json").relative_to(ROOT)),
            "report_sha256": sha(OFFLINE / "report.json"),
            "scripted_native_cases_reverified": 4,
            "tamper_negatives_reverified": 4,
            "predecessor_report_sha256": sha(PARTIAL014_OFFLINE / "report.json"),
            "model_tier": "SCRIPTED_SIMULATION", "paid_model_calls": 0}


def _ledger() -> dict:
    state = BudgetLedger(CANONICAL_LEDGER).snapshot()
    if (state.get("cap_usd") != "50" or state.get("blocked")
            or state.get("unknown_run_ids")):
        raise ValueError("PRESSURE016 USD50 ledger blocked or unknown")
    # This bridge projects away only the independently reviewed XHIGH017 full
    # hold, then replays the unchanged four-predecessor gate.  Unknown charges,
    # new reservations, modified prior holds, and final settlement of the
    # unattributed XHIGH017 request all fail closed.
    _reviewed_prior_holds(state)
    return state


def _partial014_closed(state: dict) -> dict:
    from scripts.partial014_collect import collect as collect_partial014
    from scripts.partial014_freeze import (load_assignment as load_partial014,
                                           verify_static as verify_partial014)
    verify_partial014()
    _, assignment_sha, assigned = load_partial014()
    review = json.loads(PARTIAL014_REVIEW.read_bytes())
    bindings = review.get("source_bindings")
    verified = review.get("verification")
    if not isinstance(bindings, dict) or not isinstance(verified, dict):
        raise ValueError("PARTIAL014 independent review lacks source bindings")
    final_binding = bindings.get("final_collection")
    assignment_binding = bindings.get("assignment_manifest")
    if not isinstance(final_binding, dict) or not isinstance(assignment_binding, dict):
        raise ValueError("PARTIAL014 independent review lacks final artifacts")
    relative = final_binding.get("path")
    if (type(relative) is not str or Path(relative).is_absolute()
            or ".." in Path(relative).parts):
        raise ValueError("PARTIAL014 independent review lacks safe collection path")
    collection_path = ROOT / relative
    assignment_path = PARTIAL014_GATE / "assignment-001/assignment_manifest.json"
    if (collection_path.resolve() !=
            (PARTIAL014_GATE / "collection-005-final.json").resolve()
            or assignment_binding.get("path") !=
               str(assignment_path.relative_to(ROOT))
            or assignment_binding.get("sha256") != assignment_sha
            or sha(assignment_path) != assignment_sha
            or final_binding.get("sha256") != sha(collection_path)
            or verified.get("final_collection_sha256") != sha(collection_path)
            or verified.get("saved_collector_replayed_byte_identically") is not True
            or verified.get("frozen_assignment_bound_rows") != len(assigned)
            or verified.get("shared_ledger_settled_runs_bound_to_inspect") !=
               len(assigned)
            or review.get("schema") != "partial014-independent-results-review-v1"
            or review.get("study") != "erc8183-partial-claim-timing-014"
            or review.get("reviewer_id") in (None, "", "/root")
            or review.get("freeze_or_paid_authorization", False) is not False
            or review.get("status") != PARTIAL014_REVIEW_STATUS
            or sha(PARTIAL014_REVIEW) != PARTIAL014_REVIEW_SHA):
        raise ValueError("PARTIAL014 final independent review differs")
    saved = json.loads(collection_path.read_bytes())
    current = collect_partial014()
    # The historical collection's ledger sequence is an observation at its
    # write time; subsequent settled PRESSURE016 rows legitimately advance it.
    current["shared_ledger_seq"] = saved.get("shared_ledger_seq")
    if saved != current or saved.get("planned_episodes") != len(assigned):
        raise ValueError("PARTIAL014 final assigned denominator no longer replays")
    if (saved.get("completed_episodes", 0)
            + saved.get("observed_incomplete_episodes", 0)
            + saved.get("stopped_episodes", 0)
            + saved.get("pending_episodes", 0) != len(assigned)):
        raise ValueError("PARTIAL014 final denominator differs")
    if saved.get("pending_episodes", 0) and not saved.get("stopped_episodes", 0):
        raise ValueError("PARTIAL014 has unclosed pending rows")
    for row in saved["rows"]:
        if row["status"] in {"COMPLETE", "OBSERVED_INCOMPLETE"}:
            ident = "partial014-" + assignment_sha[:12] + "-" + row["episode_id"]
            if state["runs"].get(ident, {}).get("status") != "SETTLED":
                raise ValueError("PARTIAL014 complete model run lacks settled billing")
        elif row["status"] == "STOPPED":
            ident = "partial014-" + assignment_sha[:12] + "-" + row["episode_id"]
            if state["runs"].get(ident, {}).get("status") != "SETTLED":
                raise ValueError("PARTIAL014 stopped charge is not reconciled")
    return {"assignment_manifest_sha256": assignment_sha,
            "collection_path": relative, "collection_sha256": sha(collection_path),
            "independent_review_sha256": sha(PARTIAL014_REVIEW),
            "completed_episodes": saved["completed_episodes"],
            "stopped_episodes": saved["stopped_episodes"],
            "pending_episodes": saved["pending_episodes"]}


def _xhigh017_first_stop() -> dict:
    """Bind the immutable failed effort study without recoding its denominator.

    Its frozen collector expects UNKNOWN at the historical stop and cannot
    replay against the later reviewed CONTINGENT ledger state.  The saved
    collection and independent forensics therefore remain immutable evidence.
    """
    if sha(XHIGH017_FIRST_STOP) != XHIGH017_FIRST_STOP_SHA:
        raise ValueError("XHIGH017 independent first-stop review differs")
    review = json.loads(XHIGH017_FIRST_STOP.read_bytes())
    collection_path = XHIGH017_GATE / "collection-001-after-first-stop.json"
    collection = json.loads(collection_path.read_bytes())
    if (review.get("schema") != "xhigh017-independent-first-stop-forensics-v1"
            or review.get("decision") != "TECHNICAL_STOP_NO_XHIGH_COMPARISON"
            or review.get("reviewer_id") in (None, "", "/root")
            or review.get("reviewed_sha256", {}).get(
                str(collection_path.relative_to(ROOT))) != XHIGH017_COLLECTION_SHA
            or sha(collection_path) != XHIGH017_COLLECTION_SHA
            or review.get("billing", {}).get("run_id") != XHIGH017_RUN_ID
            or review["billing"].get("current_status") != "UNKNOWN"
            or review["billing"].get("full_reserved_usd") !=
               str(XHIGH017_FULL_HOLD_USD)
            or review.get("observations", {}).get("planned_episodes") != 2
            or review["observations"].get("completed_episodes") != 0
            or review["observations"].get("stopped_episodes") != 1
            or review["observations"].get("pending_episodes") != 1
            or collection.get("assignment_manifest_sha256") !=
               XHIGH017_ASSIGNMENT_SHA
            or tuple(collection.get(key) for key in (
                "planned_episodes", "completed_episodes", "stopped_episodes",
                "pending_episodes")) != (2, 0, 1, 1)
            or [row.get("status") for row in collection.get("rows", [])] !=
               ["STOPPED", "PENDING"]):
        raise ValueError("XHIGH017 first-stop facts or saved denominator differ")
    for relative, expected_sha in review["reviewed_sha256"].items():
        # The canonical ledger advances for reviewed contingent transitions;
        # its exact pretransition hash is checked against the hash-chain below.
        if relative.startswith("artifacts/budget/openrouter-ledger.jsonl"):
            continue
        path = Path(relative)
        if (path.is_absolute() or ".." in path.parts
                or sha(ROOT / path) != expected_sha):
            raise ValueError("XHIGH017 reviewed source or stop artifact differs")
    pre = review["billing"]
    seq = pre.get("ledger_pretransition_seq")
    lines = CANONICAL_LEDGER.read_bytes().splitlines()
    if (type(seq) is not int or seq < 0 or len(lines) <= seq
            or json.loads(lines[seq])["hash"] !=
               pre.get("ledger_pretransition_last_hash")):
        raise ValueError("XHIGH017 first-stop ledger prestate is not an ancestor")
    return {"forensics_sha256": XHIGH017_FIRST_STOP_SHA,
            "collection_sha256": XHIGH017_COLLECTION_SHA,
            "assignment_manifest_sha256": XHIGH017_ASSIGNMENT_SHA,
            "completed_episodes": 0, "stopped_episodes": 1,
            "pending_episodes": 1}


def _reviewed_prior_holds(state: dict) -> dict:
    first_stop = _xhigh017_first_stop()
    if (sha(XHIGH017_BILLING_EVIDENCE) != XHIGH017_BILLING_EVIDENCE_SHA
            or sha(XHIGH017_BILLING_REVIEW) != XHIGH017_BILLING_REVIEW_SHA):
        raise ValueError("XHIGH017 contingent assessment lacks exact independent review")
    evidence = json.loads(XHIGH017_BILLING_EVIDENCE.read_bytes())
    review = json.loads(XHIGH017_BILLING_REVIEW.read_bytes())
    evidence_path = str(XHIGH017_BILLING_EVIDENCE.relative_to(ROOT))
    if (evidence.get("schema") != "xhigh017-first-stop-provisional-billing-v1"
            or evidence.get("result") !=
               "PROVISIONAL_HOLD_RETAINED_FINAL_CHARGE_UNKNOWN"
            or evidence.get("intended_transition") !=
               "UNKNOWN_TO_CONTINGENT_WITH_FULL_HOLD"
            or evidence.get("attributable_final_provider_bill_usd", "MISSING")
               is not None
            or evidence.get("run_id") != XHIGH017_RUN_ID
            or evidence.get("retained_run_reservation_usd") !=
               str(XHIGH017_FULL_HOLD_USD)
            or evidence.get("frozen_artifacts_sha256", {}).get("forensics") !=
               first_stop["forensics_sha256"]
            or evidence["frozen_artifacts_sha256"].get("collection") !=
               first_stop["collection_sha256"]
            or evidence["frozen_artifacts_sha256"].get("assignment") !=
               first_stop["assignment_manifest_sha256"]
            or evidence.get("frozen_row_disposition") !=
               "ZERO_COMPLETE_ONE_STOPPED_ONE_PENDING_NO_RETRY"
            or evidence.get("whole_account_delta_is_per_call_bill") is not False
            or review.get("schema") !=
               "xhigh017-provisional-billing-independent-review-v1"
            or review.get("decision") !=
               "GO_FOR_ONE_CANONICAL_UNKNOWN_TO_CONTINGENT_TRANSITION"
            or review.get("reviewed_artifacts_sha256", {}).get(evidence_path) !=
               XHIGH017_BILLING_EVIDENCE_SHA
            or review.get("retained_reservation_usd") !=
               str(XHIGH017_FULL_HOLD_USD)
            or review.get("attributable_final_provider_bill_usd", "MISSING")
               is not None
            or review.get("no_paid_calls_or_ledger_mutations") is not True
            or review.get("reviewer_id") in (
                None, "", "/root", "/root/xhigh017_billing_assessment")):
        raise ValueError("XHIGH017 full-hold billing review or evidence differs")
    for relative, expected_sha in review["reviewed_artifacts_sha256"].items():
        path = Path(relative)
        if (path.is_absolute() or ".." in path.parts
                or sha(ROOT / path) != expected_sha):
            raise ValueError("XHIGH017 independent billing review source differs")
    prestate_path = XHIGH017_BILLING / "openrouter-ledger.prestate.jsonl"
    prestate = BudgetLedger(prestate_path).snapshot()
    expected_pre = evidence.get("ledger_prestate")
    if (not isinstance(expected_pre, dict)
            or review.get("canonical_ledger_prestate", {}).get("seq") !=
               expected_pre.get("seq")
            or review["canonical_ledger_prestate"].get("last_hash") !=
               expected_pre.get("last_hash")
            or any(prestate.get(key) != expected_pre.get(key) for key in (
                "seq", "last_hash", "cap_usd", "reserved_usd",
                "settled_spent_usd", "available_usd", "blocked",
                "unknown_run_ids"))
            or prestate["runs"].get(XHIGH017_RUN_ID, {}).get("status") !=
               "UNKNOWN"
            or prestate["runs"][XHIGH017_RUN_ID].get("reserved_usd") !=
               str(XHIGH017_FULL_HOLD_USD)
            or sha(prestate_path) != evidence["frozen_artifacts_sha256"].get(
                "ledger")
            or sha(prestate_path.with_name(
                prestate_path.name + ".anchor")) !=
               evidence["frozen_artifacts_sha256"].get("anchor")):
        raise ValueError("XHIGH017 archived pretransition ledger differs")
    lines = CANONICAL_LEDGER.read_bytes().splitlines()
    seq = prestate["seq"]
    if (state.get("seq", -1) <= seq or len(lines) <= seq + 1
            or json.loads(lines[seq])["hash"] != prestate["last_hash"]):
        raise ValueError("XHIGH017 contingent transition lacks exact ledger ancestor")
    transition = json.loads(lines[seq + 1])
    ref = "sha256:" + XHIGH017_BILLING_EVIDENCE_SHA
    if (transition.get("kind") != "contingent"
            or transition.get("prev_hash") != prestate["last_hash"]
            or transition.get("payload") != {
                "run_id": XHIGH017_RUN_ID, "evidence_ref": ref}):
        raise ValueError("XHIGH017 reviewed full-hold transition differs")
    run = state.get("runs", {}).get(XHIGH017_RUN_ID, {})
    if (run.get("status") != "CONTINGENT"
            or run.get("reserved_usd") != str(XHIGH017_FULL_HOLD_USD)
            or run.get("metadata") != {
                "assignment_sha": XHIGH017_ASSIGNMENT_SHA,
                "episode_id": "xhigh017-0a63961c0d306890326609f6",
                "provider_model_id": "anthropic/claude-sonnet-5.5",
                "auditor_model_id": "openai/gpt-5.6-sol"}
            or run.get("evidence_ref") != ref
            or run.get("contingent_evidence_ref") != ref
            or run.get("prior_unknown_reason") != "RemoteBoundaryError"
            or "actual_usd" in run
            or state.get("blocked") or state.get("unknown_run_ids")
            or XHIGH017_RUN_ID not in state.get("contingent_run_ids", [])):
        raise ValueError("XHIGH017 first stop lacks reviewed full contingent hold")
    projection = dict(state)
    projection["runs"] = {key: value for key, value in state["runs"].items()
                          if key != XHIGH017_RUN_ID}
    projection["reserved_usd"] = str(
        Decimal(state["reserved_usd"]) - XHIGH017_FULL_HOLD_USD)
    projection["available_usd"] = str(
        Decimal(state["available_usd"]) + XHIGH017_FULL_HOLD_USD)
    projection["contingent_run_ids"] = sorted(
        set(state["contingent_run_ids"]) - {XHIGH017_RUN_ID})
    old = exact_prior_holds(projection)
    return {**first_stop, "contingent_assessment_sha256":
            XHIGH017_BILLING_EVIDENCE_SHA,
            "independent_billing_review_sha256": XHIGH017_BILLING_REVIEW_SHA,
            "full_contingent_hold_usd": str(XHIGH017_FULL_HOLD_USD),
            "reviewed_base_reserved_usd": old["prior_reserved_usd"],
            "reviewed_four_holds_usd": str(
                Decimal(state["reserved_usd"]) - XHIGH017_FULL_HOLD_USD),
            "all_prior_reserved_usd": state["reserved_usd"]}


def _budget(state: dict, prices: dict) -> dict:
    per = per_row_reserve(prices)
    needed = required_headroom(prices, ROWS)
    if needed > Decimal(state["available_usd"]):
        raise ValueError("full four-row PRESSURE016 block plus contingency exceeds USD50")
    return {"per_row_worst_case_usd": str(per),
            "full_block_plus_contingency_residual_usd": str(needed),
            "ledger_available_usd": state["available_usd"]}


def _pricing_basis(prices: dict) -> dict:
    """Catalog quote identity excludes only the fetch timestamp."""
    return {name: {key: value for key, value in item.items()
                   if key != "fetched_utc"} for name, item in prices.items()}


def _four_cell_design() -> dict:
    return {"rows": ROWS,
            "cells": [{"truth": truth, "pressure": pressure,
                       "contact": contact}
                      for truth, pressure, contact in sorted(CELLS)],
            "fee_term": NATIVE_CONTINGENT,
            "role_models": {"provider": SOL, "auditor": SONNET},
            "reasoning_effort_requested": "high",
            "assignment_preview_schema": "pressure016-assignment-preview-v1",
            "one_randomized_pair_per_cell": True}


def clearance_preview(state: dict, prices: dict) -> dict:
    """Build a source-, predecessor-, design- and budget-bound decision."""
    sources = source_inventory()
    return {"schema": "pressure016-cross-study-clearance-v1",
            "status": "GO_AFTER_REVIEWED_XHIGH017_FIRST_STOP_FOR_ONE_TIME_FREEZE",
            "source_inventory_sha256": digest(sources),
            "independent_source_review": source_review(sources),
            "partial014_final_closure": _partial014_closed(state),
            "xhigh017_first_stop_and_full_hold": _reviewed_prior_holds(state),
            "four_cell_design": _four_cell_design(),
            "public_pricing_snapshot": prices,
            "budget_at_clearance": _budget(state, prices),
            "ledger_at_clearance": {key: state[key] for key in
                                    ("seq", "last_hash", "cap_usd",
                                     "available_usd", "reserved_usd")},
            "prior_ledger_run_ids": sorted(state["runs"]),
            "prior_ledger_runs_sha256": digest(state["runs"]),
            "no_new_paid_calls_authorized_by_clearance": True}


def write_clearance() -> dict:
    _canonical_root()
    if os.environ.get("PRESSURE016_CLEARANCE_ALLOWED") != "true":
        raise ValueError("explicit PRESSURE016 cross-study clearance switch required")
    if CLEARANCE.exists() or ASSIGNMENT.exists() or LOCK.exists():
        raise FileExistsError("PRESSURE016 clearance/freeze already exists")
    if not clean_versioned_sources():
        raise ValueError("PRESSURE016 source must be committed before clearance")
    state = _ledger()
    prices = pricing_snapshots()
    payload = clearance_preview(state, prices)
    if BudgetLedger(CANONICAL_LEDGER).snapshot()["last_hash"] != state["last_hash"]:
        raise ValueError("shared ledger changed during PRESSURE016 clearance")
    GATE.mkdir(parents=True, exist_ok=True)
    _new(CLEARANCE, _json(payload))
    return {"status": "CLEARANCE_SAVED_NO_PAID_CALL", "sha256": sha(CLEARANCE),
            "model_calls": 0}


def clearance(state: dict, *, prices: dict | None = None,
              require_current_head: bool = True) -> dict:
    if CLEARANCE.is_symlink():
        raise ValueError("PRESSURE016 clearance symlinked")
    saved = json.loads(CLEARANCE.read_bytes())
    original = saved.get("ledger_at_clearance")
    if (not isinstance(original, dict) or type(original.get("seq")) is not int
            or original["seq"] < 0 or original.get("cap_usd") != "50"
            or original["seq"] > state["seq"]):
        raise ValueError("PRESSURE016 clearance ledger ancestor differs")
    lines = CANONICAL_LEDGER.read_bytes().splitlines()
    if (len(lines) <= original["seq"]
            or json.loads(lines[original["seq"]])["hash"] != original.get("last_hash")):
        raise ValueError("PRESSURE016 clearance ledger hash is not ancestor")
    prior_ids = saved.get("prior_ledger_run_ids")
    if (not isinstance(prior_ids, list) or prior_ids != sorted(set(prior_ids))
            or any(ident not in state["runs"] for ident in prior_ids)
            or digest({ident: state["runs"][ident] for ident in prior_ids})
               != saved.get("prior_ledger_runs_sha256")):
        raise ValueError("PRESSURE016 clearance predecessor ledger runs differ")
    if require_current_head:
        if (state["seq"] != original["seq"]
                or state["last_hash"] != original["last_hash"]
                or state["available_usd"] != original["available_usd"]
                or state["reserved_usd"] != original["reserved_usd"]):
            raise ValueError("PRESSURE016 clearance requires current ledger head")
        fresh_prices = pricing_snapshots() if prices is None else prices
        if _pricing_basis(fresh_prices) != _pricing_basis(
                saved.get("public_pricing_snapshot", {})):
            raise ValueError("PRESSURE016 clearance public model prices changed")
    else:
        fresh_prices = saved.get("public_pricing_snapshot")
    sources = source_inventory()
    expected = {"schema": "pressure016-cross-study-clearance-v1",
                "status": "GO_AFTER_REVIEWED_XHIGH017_FIRST_STOP_FOR_ONE_TIME_FREEZE",
                "source_inventory_sha256": digest(sources),
                "independent_source_review": source_review(sources),
                "partial014_final_closure": _partial014_closed(state),
                "xhigh017_first_stop_and_full_hold":
                    _reviewed_prior_holds(state),
                "four_cell_design": _four_cell_design(),
                "public_pricing_snapshot": saved.get("public_pricing_snapshot"),
                "budget_at_clearance": _budget(
                    {**state, "available_usd": original["available_usd"]},
                    fresh_prices),
                "ledger_at_clearance": original,
                "prior_ledger_run_ids": prior_ids,
                "prior_ledger_runs_sha256": saved.get(
                    "prior_ledger_runs_sha256"),
                "no_new_paid_calls_authorized_by_clearance": True}
    if saved != expected:
        raise ValueError("PRESSURE016 cross-study clearance bytes/facts differ")
    return {"path": str(CLEARANCE.relative_to(ROOT)),
            "sha256": sha(CLEARANCE),
            "ledger_at_clearance": original,
            "four_cell_design_sha256": digest(expected["four_cell_design"])}


def readiness() -> dict:
    checks: dict[str, str] = {}
    values: dict = {}
    for name, fn in (
        ("canonical_checkout", _canonical_root),
        ("one_time_freeze_available", lambda: None if not LOCK.exists()
         and not ASSIGNMENT.exists() else (_ for _ in ()).throw(
             FileExistsError("already or partially frozen"))),
        ("source_clean", lambda: None if clean_versioned_sources() else
         (_ for _ in ()).throw(ValueError("source not committed"))),
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
    for name, fn in (
        ("independent_source_review", lambda: source_review(
            values["source_inventory"])),
        ("partial014_final_closure", lambda: _partial014_closed(
            values["shared_ledger"])),
        ("xhigh017_first_stop_and_full_hold", lambda:
            _reviewed_prior_holds(values["shared_ledger"])),
        ("cross_study_clearance", lambda: clearance(
            values["shared_ledger"], prices=values["current_catalog"])),
        ("full_block_budget", lambda: _budget(
            values["shared_ledger"], values["current_catalog"]))):
        try:
            values[name] = fn()
            checks[name] = "PASS"
        except Exception as exc:
            checks[name] = type(exc).__name__ + ": " + str(exc)
    ready = all(value == "PASS" for value in checks.values())
    return {"status": "READY" if ready else "BLOCKED",
            "would_freeze": ready, "would_call_paid_model": False,
            "checks": checks, "budget": values.get("full_block_budget"),
            "model_calls": 0}


def freeze(*, seed_hex: str | None = None) -> dict:
    _canonical_root()
    if os.environ.get("PRESSURE016_FREEZE_ALLOWED") != "true":
        raise ValueError("explicit PRESSURE016 one-time freeze switch required")
    if LOCK.exists() or ASSIGNMENT.exists():
        raise FileExistsError("PRESSURE016 already or partially frozen; no reroll")
    if readiness()["status"] != "READY":
        raise ValueError("PRESSURE016 readiness has uncleared gates")
    state = _ledger()
    sources = source_inventory()
    prices = pricing_snapshots()
    prior = clearance(state, prices=prices)
    seed = seed_hex if seed_hex is not None else secrets.token_hex(32)
    rows = make_schedule(seed)
    preview = prospective_manifest(seed, rows)
    if (preview["rows"] != _four_cell_design()["rows"]
            or preview["role_models"] != _four_cell_design()["role_models"]
            or {(row.truth, row.pressure, row.contact) for row in rows} != CELLS):
        raise ValueError("PRESSURE016 frozen manifest differs from cleared four cells")
    payload = {**preview,
               "schema": "pressure016-first-assignment-v1",
               "status": "FROZEN_NOT_EXECUTED",
               "source_sha256": sources,
               "source_inventory_sha256": digest(sources),
               "runtime_pins": _runtime(),
               "offline_readiness": _offline(),
               "independent_source_review": source_review(sources),
               "cross_study_clearance": prior,
               "partial014_final_closure": _partial014_closed(state),
               "xhigh017_first_stop_and_full_hold":
                   _reviewed_prior_holds(state),
               "public_pricing_snapshot": prices,
               "budget_at_freeze": {key: state[key] for key in (
                   "seq", "last_hash", "cap_usd", "available_usd", "reserved_usd")},
               "budget_gate": _budget(state, prices),
               "prior_open_ledger_run_ids": sorted(ident for ident, run in
                   state["runs"].items() if run["status"] in
                   {"RESERVED", "CONTINGENT", "UNKNOWN"}),
               "prior_ledger_run_ids": sorted(state["runs"]),
               "prior_ledger_runs_sha256": digest(state["runs"]),
               "model_tier": "REAL_LLM_REMOTE_APPROVED",
               "payment_tier": "NATIVE_LOCAL_PROTOCOL",
               "no_reroll_or_model_substitution": True}
    if BudgetLedger(CANONICAL_LEDGER).snapshot()["last_hash"] != state["last_hash"]:
        raise ValueError("shared ledger changed during PRESSURE016 freeze")
    GATE.mkdir(parents=True, exist_ok=True)
    ASSIGNMENT.mkdir(mode=0o700)
    _new(ASSIGNMENT / "seed.hex", (seed + "\n").encode())
    _new(ASSIGNMENT / "private_rows.json", _json([asdict(row) for row in rows]))
    _new(ASSIGNMENT / "assignment_manifest.json", _json(payload))
    lock = {"schema": "pressure016-one-time-freeze-v1",
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
        raise ValueError("PRESSURE016 private rows differ from one-time seed")
    manifest = ASSIGNMENT / "assignment_manifest.json"
    frozen = json.loads(manifest.read_bytes())
    preview = prospective_manifest(seed, rows)
    for key, value in preview.items():
        if key not in {"schema", "status"} and frozen.get(key) != value:
            raise ValueError("PRESSURE016 assignment differs from seed preview")
    if (frozen.get("schema") != "pressure016-first-assignment-v1"
            or frozen.get("status") != "FROZEN_NOT_EXECUTED"
            or json.loads(LOCK.read_bytes()) != {
                "schema": "pressure016-one-time-freeze-v1",
                "assignment_manifest_sha256": sha(manifest),
                "seed_commitment_sha256": frozen["seed_commitment_sha256"]}):
        raise ValueError("PRESSURE016 one-time manifest or lock differs")
    return frozen, sha(manifest), rows


def verify_static() -> dict:
    _canonical_root()
    frozen, assignment_sha, rows = load_assignment()
    sources = frozen_source_inventory(frozen["source_sha256"])
    if (frozen["source_sha256"] != sources
            or frozen["source_inventory_sha256"] != digest(sources)
            or frozen["independent_source_review"] != source_review(sources)
            or frozen["offline_readiness"] != _offline()):
        raise ValueError("PRESSURE016 sealed source, review or native controls changed")
    prior = frozen.get("cross_study_clearance")
    if (not isinstance(prior, dict) or prior.get("sha256") != sha(CLEARANCE)
            or prior.get("path") != str(CLEARANCE.relative_to(ROOT))
            or prior.get("four_cell_design_sha256") != digest(_four_cell_design())):
        raise ValueError("PRESSURE016 cross-study clearance changed")
    return {"status": "SEALED_STATIC", "assignment_manifest_sha256": assignment_sha,
            "rows": len(rows), "model_calls": 0}


def verify() -> dict:
    result = verify_static()
    frozen, assignment_sha, _ = load_assignment()
    state = _ledger()
    earlier = frozen["budget_at_freeze"]
    lines = CANONICAL_LEDGER.read_bytes().splitlines()
    if (state["seq"] < earlier["seq"] or len(lines) <= earlier["seq"]
            or json.loads(lines[earlier["seq"]])["hash"] != earlier["last_hash"]
            or frozen["cross_study_clearance"] != clearance(
                state, require_current_head=False)
            or frozen["partial014_final_closure"] != _partial014_closed(state)
            or frozen["xhigh017_first_stop_and_full_hold"] !=
               _reviewed_prior_holds(state)):
        raise ValueError("PRESSURE016 predecessor or ledger ancestor differs")
    from agent_economic_trust.pressure016_remote import _ledger as verify_run_set
    verify_run_set(state, frozen, assignment_sha)
    return {**result, "ledger_seq": state["seq"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("readiness", "clearance", "freeze", "verify",
                                            "verify-static"),
                        nargs="?", default="readiness")
    args = parser.parse_args()
    result = {"readiness": readiness, "clearance": write_clearance,
              "freeze": freeze, "verify": verify,
              "verify-static": verify_static}[args.command]()
    print(json.dumps(result, sort_keys=True))
