"""Read-only BILATERAL030 block preflight and assignment-seal proposal.

This module deliberately has no reservation, model, chain, or freeze operation.
The proposal is not a private assignment: it contains commitments and public
identifiers only. A future paid runner needs a separately reviewed successor.
"""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any

from .bilateral030_plan import (CANONICAL_LEDGER, ROWS, STUDY, canonical,
                                make_schedule, prospective_manifest,
                                required_headroom)
from .bilateral030_remote import historical_catalog
from .remote_budget import BudgetLedger


ROOT = Path(__file__).resolve().parents[2]
# Direct study sources and their local evidence dependencies are enumerated.
# A future freeze must also pin external ORBIT/Inspect and ERC-8183 versions.
SOURCE_PATHS = (
    "src/agent_economic_trust/bilateral030_plan.py",
    "src/agent_economic_trust/erc8183_fee_plan.py",
    "src/agent_economic_trust/bilateral030_orchestration.py",
    "src/agent_economic_trust/bilateral030_remote.py",
    "src/agent_economic_trust/bilateral030_boundary.py",
    "src/agent_economic_trust/bilateral030_adapter.py",
    "src/agent_economic_trust/bilateral030_task.py",
    "src/agent_economic_trust/bilateral030_native_orbit_probe.py",
    "src/agent_economic_trust/bilateral030_mock.py",
    "src/agent_economic_trust/bilateral030_native.py",
    "src/agent_economic_trust/bilateral030_funding_archive.py",
    "src/agent_economic_trust/bilateral030_funding_verifier.py",
    "src/agent_economic_trust/bilateral030_native_verifier.py",
    "src/agent_economic_trust/bilateral030_trace_verifier.py",
    "src/agent_economic_trust/bilateral030_analysis.py",
    "src/agent_economic_trust/ap2_live_fixture.py",
    "src/agent_economic_trust/core.py",
    "src/agent_economic_trust/partial014_plan.py",
    "src/agent_economic_trust/partial014_native_verifier.py",
    "src/agent_economic_trust/mpp005_boundary.py",
    "src/agent_economic_trust/reporting.py",
    "src/agent_economic_trust/remote_budget.py",
    "scripts/bilateral030_collect.py",
    "scripts/run_erc8183_local.py",
    "scripts/verify_first_claim_bonus_control.py",
    "protocols/side_escrow/src/FirstClaimBonusHook.sol",
)
_STATIC_GATES = (
    "SOURCE_ONLY_EXECUTION_DISABLED",
    "ASSIGNMENT_NOT_FROZEN",
    "FULL_BLOCK_RESERVATION_NOT_MADE",
    "INDEPENDENT_PREVIEW_FUNDING_ATTESTATION_NOT_BOUND_TO_MODEL_INPUT",
    "HOSTED_BOTH_ROLE_REASONING_CONFIG_NOT_VERIFIED_FROM_RAW_MODELCALLS",
    "HOSTED_TRACE_NATIVE_RECEIPT_JOIN_NOT_INDEPENDENTLY_REVIEWED",
    "FRESH_MODEL_CATALOG_NOT_VERIFIED",
    "POST_ROW_RAW_REVIEWS_REQUIRED_BEFORE_COMPLETE_OR_NEXT_ROW",
)


def _git(root: Path, *arguments: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(["git", *arguments], cwd=root, text=True,
                                capture_output=True, check=False, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    return result.returncode == 0, result.stdout.strip()


def source_inventory(root: Path = ROOT) -> dict[str, Any]:
    """Hash required source bytes; report missing, untracked and dirty paths.

    Re-reading after Git inspection detects source changes during this scan.
    The snapshot is a proposal. Git cleanliness and a digest alone do not
    authenticate a future execution or its external dependencies.
    """
    root = Path(root).resolve()
    files: dict[str, str] = {}
    missing: list[str] = []
    for relative in SOURCE_PATHS:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            missing.append(relative)
        else:
            files[relative] = sha256(path.read_bytes()).hexdigest()
    head_ok, head = _git(root, "rev-parse", "HEAD")
    tracked_ok, tracked_text = _git(root, "ls-files", "--cached", "--", *SOURCE_PATHS)
    tracked = set(tracked_text.splitlines()) if tracked_ok else set()
    untracked = sorted(set(files) - tracked)
    clean_ok, changes = _git(root, "status", "--porcelain", "--untracked-files=all")
    changed_during_scan = sorted(
        relative for relative, original in files.items()
        if sha256((root / relative).read_bytes()).hexdigest() != original)
    inventory = {"git_head": head if head_ok and len(head) == 40 else None,
                 "files_sha256": files,
                 "missing_required_sources": missing,
                 "untracked_required_sources": untracked,
                 "git_status_clean": clean_ok and not changes,
                 "changed_during_scan": changed_during_scan}
    inventory["source_snapshot_sha256"] = sha256(canonical(inventory)).hexdigest()
    inventory["local_source_inventory_clean"] = bool(
        inventory["git_head"] and not missing and not untracked
        and inventory["git_status_clean"] and not changed_during_scan)
    return inventory


def preflight_proposal(identity_seed_hex: str, assignment_seed_hex: str,
                       *, root: Path = ROOT,
                       ledger_path: Path = CANONICAL_LEDGER) -> dict[str, Any]:
    """Return a public, non-executable thirty-row proposal and exact blockers.

    Caller seeds remain in memory; this result has no seed material or private
    arm/truth labels per row. Nothing here reserves money or authorizes a call.
    """
    if identity_seed_hex == assignment_seed_hex:
        raise ValueError("BILATERAL030 identity and assignment seeds must differ")
    rows = make_schedule(identity_seed_hex, assignment_seed_hex)
    public = prospective_manifest(identity_seed_hex, rows, assignment_seed_hex)
    inventory = source_inventory(root)
    snapshot = BudgetLedger(ledger_path).snapshot()
    quote = required_headroom(historical_catalog(), rows)
    available = Decimal(snapshot["available_usd"])
    reasons = list(_STATIC_GATES)
    if not inventory["local_source_inventory_clean"]:
        reasons.append("SOURCE_INVENTORY_INCOMPLETE_OR_DIRTY")
    if snapshot["cap_usd"] != "50":
        reasons.append("AUTHORIZED_LEDGER_CAP_DIFFERS")
    if snapshot["blocked"] or snapshot["unknown_run_ids"]:
        reasons.append("SHARED_LEDGER_BLOCKED_OR_UNKNOWN")
    if snapshot["contingent_run_ids"]:
        reasons.append("PRIOR_CONTINGENT_BILLING_UNRECONCILED")
    if available < quote:
        reasons.append("FULL_BLOCK_EXCEEDS_AVAILABLE_HEADROOM")
    # Do not serialize asdict(row): that would expose the private treatment.
    private_rows_digest = sha256(canonical([asdict(row) for row in rows])).hexdigest()
    proposal_core = {
        "study": STUDY,
        "source_snapshot_sha256": inventory["source_snapshot_sha256"],
        "seed_commitment_sha256": public["seed_commitment_sha256"],
        "assignment_seed_commitment_sha256":
            public["assignment_seed_commitment_sha256"],
        "private_rows_sha256": private_rows_digest,
        "public_rows_sha256": sha256(canonical(public["public_rows"])).hexdigest(),
        "execution_order_sha256": sha256(canonical(public["execution_order"])).hexdigest(),
    }
    proposal_sha = sha256(canonical(proposal_core)).hexdigest()
    return {
        "schema": "bilateral030-source-block-preflight-v1",
        "status": "HOLD_SOURCE_ONLY_UNFROZEN",
        "permission_to_freeze_reserve_or_call": False,
        "planned_rows": ROWS,
        "proposal_sha256": proposal_sha,
        "proposal_seal": proposal_core,
        "assignment_status": "DRAFT_UNFROZEN",
        "source_inventory": inventory,
        "public_assignment_preview": public,
        "budget": {
            "historical_quote_not_live_catalog_usd": str(quote),
            "full_block_reservation_present": False,
            "ledger_seq": snapshot["seq"],
            "ledger_last_hash": snapshot["last_hash"],
            "ledger_cap_usd": snapshot["cap_usd"],
            "ledger_available_usd": snapshot["available_usd"],
            "ledger_blocked": snapshot["blocked"],
            "unknown_run_ids": snapshot["unknown_run_ids"],
            "contingent_run_ids": snapshot["contingent_run_ids"],
        },
        "hold_reasons": reasons,
        "row_status": [{"episode_id": row.episode_id, "status": "PENDING",
                        "scientific_outcome": None} for row in rows],
        "stop_rule": "No first row starts. A future runner attempts each assigned row at most once. An isolated row-local STOPPED remains missing; continue only after independent first-stop forensics, attributable charge or retained worst-case hold, fresh agents and Anvil, and remaining full-block cap. Globally halt on source or assignment drift, truth leak, receipt/trace mismatch, boundary bypass, unbounded retry, unknown billing, repeated systemic failure, or insufficient cap. Never replace a row.",
    }


def validate_preflight_report(report: dict[str, Any]) -> None:
    """Reject a report that could be mistaken for a freeze or permission."""
    if (report.get("schema") != "bilateral030-source-block-preflight-v1"
            or report.get("status") != "HOLD_SOURCE_ONLY_UNFROZEN"
            or report.get("permission_to_freeze_reserve_or_call") is not False
            or report.get("assignment_status") != "DRAFT_UNFROZEN"
            or report.get("planned_rows") != ROWS
            or len(report.get("row_status", [])) != ROWS
            or any(row.get("status") != "PENDING" or
                   row.get("scientific_outcome") is not None
                   for row in report["row_status"])
            or not isinstance(report.get("hold_reasons"), list)
            or "SOURCE_ONLY_EXECUTION_DISABLED" not in report["hold_reasons"]):
        raise ValueError("BILATERAL030 preflight report claims execution or outcome")
    if sha256(canonical(report["proposal_seal"])).hexdigest() != report.get("proposal_sha256"):
        raise ValueError("BILATERAL030 proposal seal differs")
    try:
        seal = report["proposal_seal"]
        preview = report["public_assignment_preview"]
        public_rows = preview["public_rows"]
        execution_order = preview["execution_order"]
        source = report["source_inventory"]
        if (seal["source_snapshot_sha256"] != source["source_snapshot_sha256"]
                or seal["seed_commitment_sha256"] != preview["seed_commitment_sha256"]
                or seal["assignment_seed_commitment_sha256"] !=
                preview["assignment_seed_commitment_sha256"]
                or seal["public_rows_sha256"] != sha256(canonical(public_rows)).hexdigest()
                or seal["execution_order_sha256"] !=
                sha256(canonical(execution_order)).hexdigest()
                or [row["episode_id"] for row in public_rows] != execution_order
                or [row["episode_id"] for row in report["row_status"]] != execution_order):
            raise ValueError("BILATERAL030 public assignment or source seal differs")
    except (TypeError, KeyError, IndexError) as exc:
        raise ValueError("BILATERAL030 preflight report is malformed") from exc


def pre_view_row_hold(report: dict[str, Any], row_index: int,
                      funding_claim: dict[str, Any] | None = None) -> dict[str, Any]:
    """Apply the source-only row boundary before any model sees the job.

    A controller-supplied attestation, even one claiming VERIFIED, is never
    accepted as independent proof. A reviewed successor must invoke the raw
    funding verifier itself while Anvil is alive, join its output to the exact
    delivered prefix, then bind a frozen assignment and full-block reservation.
    """
    validate_preflight_report(report)
    if type(row_index) is not int or not 0 <= row_index < ROWS:
        raise ValueError("BILATERAL030 row index outside assigned block")
    public = report["public_assignment_preview"]["public_rows"][row_index]
    row = report["row_status"][row_index]
    if row["episode_id"] != public["episode_id"]:
        raise ValueError("BILATERAL030 pre-view row and public assignment differ")
    if funding_claim is not None:
        if type(funding_claim) is not dict:
            raise ValueError("BILATERAL030 funding claim must be an object")
        if (funding_claim.get("episode_id") != public["episode_id"]
                or funding_claim.get("obligation_id") != public["obligation_id"]):
            raise ValueError("BILATERAL030 funding claim belongs to another row")
    reasons = list(report["hold_reasons"]) + ["PREVIEW_FUNDING_LIVE_REPLAY_NOT_INVOKED"]
    if row_index:
        reasons.extend(("PRIOR_ROW_INDEPENDENT_TRACE_NATIVE_OR_STOP_REVIEW_MISSING",
                        "PRIOR_ROW_ATTRIBUTABLE_CHARGE_OR_WORST_CASE_HOLD_UNVERIFIED",
                        "FRESH_AGENT_CHAIN_AND_REMAINING_CAP_UNVERIFIED"))
    return {
        "schema": "bilateral030-source-pre-view-hold-v1",
        "status": "HOLD_NO_MODEL_VIEW",
        "episode_id": public["episode_id"],
        "obligation_id": public["obligation_id"],
        "scientific_outcome": None,
        "funding_claim_supplied_but_not_independently_replayed":
            funding_claim is not None,
        "permission_to_call_model": False,
        "hold_reasons": reasons,
    }


def write_preflight_report(report: dict[str, Any], path: Path) -> None:
    """Write a public HOLD report once, without replacing prior evidence."""
    validate_preflight_report(report)
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink() or not path.parent.is_dir():
        raise ValueError("BILATERAL030 report path is unsafe")
    with path.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, sort_keys=True, indent=2)
        handle.write("\n")
