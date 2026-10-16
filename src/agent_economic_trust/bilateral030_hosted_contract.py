"""Pure, hard-closed contract for a future BILATERAL030 hosted runner.

These checks bind a source proposal to the exact private assignment and show
whether a *read-only* ledger snapshot could cover the proposed block. They do
not freeze an assignment, reserve money, inspect a model request, attest a
local chain, or authorize execution. Caller-supplied reviews are never proof.
"""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Mapping, Sequence

from .bilateral030_orchestration import validate_preflight_report
from .bilateral030_plan import (
    ROWS, STUDY, Bilateral030Row, canonical, make_schedule,
    prospective_manifest, required_headroom,
)


class HostedContractError(ValueError):
    """A structural precondition for the prospective block differs."""


def exact_private_assignment(
    proposal: Mapping[str, Any], identity_seed_hex: str,
    assignment_seed_hex: str,
) -> tuple[Bilateral030Row, ...]:
    """Recompute all 30 assignments and bind them to a public HOLD proposal.

    The seeds are never returned in a report. This does not prove that they
    were randomly generated, privately stored, or frozen before observation.
    """
    if identity_seed_hex == assignment_seed_hex:
        raise HostedContractError("identity and assignment seeds must differ")
    try:
        validate_preflight_report(dict(proposal))
        rows = make_schedule(identity_seed_hex, assignment_seed_hex)
        expected = prospective_manifest(
            identity_seed_hex, rows, assignment_seed_hex)
        seal = proposal["proposal_seal"]
        if (proposal["public_assignment_preview"] != expected
                or seal["private_rows_sha256"] != sha256(canonical(
                    [asdict(row) for row in rows])).hexdigest()
                or seal["public_rows_sha256"] != sha256(canonical(
                    expected["public_rows"])).hexdigest()
                or seal["execution_order_sha256"] != sha256(canonical(
                    expected["execution_order"])).hexdigest()
                or proposal["planned_rows"] != ROWS
                or seal["study"] != STUDY):
            raise HostedContractError("private assignment differs from proposal")
    except (KeyError, TypeError, ValueError) as exc:
        raise HostedContractError("assignment/proposal binding failed") from exc
    return rows


def preview_block_reserve(
    rows: tuple[Bilateral030Row, ...],
    fresh_catalog_candidate: Mapping[str, Mapping[str, Any]],
    ledger_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Calculate a worst-case reserve and blockers from supplied data.

    This is arithmetic and shape checking, not proof of a fresh catalog or
    live ledger. A paid successor must fetch and pin provider prices, reserve
    the entire block atomically on the canonical ledger, and recheck the head.
    """
    try:
        required = required_headroom(fresh_catalog_candidate, rows)
        cap = Decimal(str(ledger_snapshot["cap_usd"]))
        available = Decimal(str(ledger_snapshot["available_usd"]))
        unknown = ledger_snapshot["unknown_run_ids"]
        contingent = ledger_snapshot["contingent_run_ids"]
        blocked = ledger_snapshot["blocked"]
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise HostedContractError("catalog or ledger snapshot is malformed") from exc
    if (not cap.is_finite() or not available.is_finite() or available < 0
            or type(unknown) is not list or type(contingent) is not list
            or type(blocked) is not bool):
        raise HostedContractError("catalog or ledger snapshot is malformed")
    reasons = ["SOURCE_ONLY_NO_ATOMIC_BLOCK_RESERVATION",
               "FRESH_PROVIDER_CATALOG_PROVENANCE_UNVERIFIED"]
    if cap != Decimal("50"):
        reasons.append("LEDGER_CAP_NOT_AUTHORIZED_USD50")
    if blocked or unknown or contingent:
        reasons.append("PRIOR_BILLING_OR_SHARED_LEDGER_BLOCKED")
    if available < required:
        reasons.append("FULL_BLOCK_HEADROOM_INSUFFICIENT")
    return {
        "schema": "bilateral030-hosted-reserve-preview-v1",
        "status": "HOLD_SOURCE_ONLY",
        "permission_to_reserve_or_call": False,
        "planned_rows": ROWS,
        "required_full_block_usd": str(required),
        "snapshot_available_usd": str(available),
        "unreserved_shortfall_usd": str(max(required - available, Decimal(0))),
        "hold_reasons": reasons,
    }


def structural_block_reservation(
    proposal: Mapping[str, Any], rows: tuple[Bilateral030Row, ...],
    fresh_catalog_candidate: Mapping[str, Mapping[str, Any]],
    ledger_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare a claimed single-block reservation with the exact proposal.

    Only a hash-chain-verified snapshot read from the canonical ledger while
    holding the execution lock could be authoritative. This pure check cannot
    supply that provenance and therefore never permits a hosted request.
    """
    try:
        validate_preflight_report(dict(proposal))
        required = required_headroom(fresh_catalog_candidate, rows)
        seal = proposal["proposal_seal"]
        if seal["private_rows_sha256"] != sha256(canonical(
                [asdict(row) for row in rows])).hexdigest():
            raise HostedContractError("reservation assignment differs")
        run_id = "bilateral030-block-" + proposal["proposal_sha256"][:12]
        run = ledger_snapshot["runs"].get(run_id)
        if ledger_snapshot["cap_usd"] != "50":
            raise HostedContractError("ledger cap is not authorized USD 50")
        # A fully committed cap can set the ledger's generic `blocked` flag.
        # That is valid if this block owns the reserve; outstanding UNKNOWN
        # and CONTINGENT prior runs still prevent starting the block.
        if (ledger_snapshot["unknown_run_ids"] or
                ledger_snapshot["contingent_run_ids"] or
                ledger_snapshot.get("over_cap") is True):
            raise HostedContractError("shared ledger or prior billing is blocked")
        expected_metadata = {
            "study": STUDY,
            "planned_rows": ROWS,
            "proposal_sha256": proposal["proposal_sha256"],
            "private_rows_sha256": seal["private_rows_sha256"],
            "source_snapshot_sha256": seal["source_snapshot_sha256"],
        }
        claimed_reserve = Decimal(str(run.get("reserved_usd"))) if isinstance(
            run, Mapping) else Decimal(0)
        if (not proposal["source_inventory"]["local_source_inventory_clean"]
                or not isinstance(run, Mapping)
                or run.get("status") != "RESERVED"
                or run.get("metadata") != expected_metadata
                or not claimed_reserve.is_finite()
                or claimed_reserve < required):
            raise HostedContractError("full-block reservation claim differs")
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise HostedContractError("full-block reservation claim differs") from exc
    return {
        "schema": "bilateral030-hosted-reservation-shape-v1",
        "status": "HOLD_SOURCE_ONLY_UNAUTHENTICATED_SNAPSHOT",
        "permission_to_call_model": False,
        "claimed_run_id": run_id,
        "required_full_block_usd": str(required),
        "reason": "Ledger, fresh catalog, freeze and execution lock need independent review",
    }


def structural_row_progress(
    assigned_episode_ids: Sequence[str],
    journal: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Check no replacement, retry, or continuation after an unresolved stop.

    Journal digests are *claims*. This function does not read raw Inspect logs,
    native receipts, provider bills or a live ledger, and never returns a run
    permit. A paid successor must independently verify every referenced byte.
    """
    if (len(assigned_episode_ids) != ROWS
            or len(set(assigned_episode_ids)) != ROWS
            or len(journal) != ROWS):
        raise HostedContractError("exact thirty-row assigned denominator required")
    seen_pending = False
    complete = stopped = 0
    for index, (episode, item) in enumerate(zip(assigned_episode_ids, journal)):
        if (not isinstance(item, Mapping)
                or set(item) != {"episode_id", "status", "attempts",
                                    "outcome", "trace_review_sha256",
                                    "native_review_sha256", "billing_review_sha256",
                                    "billing_state", "stop_scope",
                                    "stop_review_sha256", "fresh_context_sha256"}
                or item["episode_id"] != episode):
            raise HostedContractError("journal replaces or reorders an assigned row")
        status = item["status"]
        attempts = item["attempts"]
        if type(attempts) is not int or attempts not in {0, 1}:
            raise HostedContractError("row retried or attempt count malformed")
        if status == "PENDING":
            if (attempts != 0 or any(item[key] is not None for key in (
                    "outcome", "trace_review_sha256", "native_review_sha256",
                    "billing_review_sha256", "billing_state", "stop_scope",
                    "stop_review_sha256", "fresh_context_sha256"))):
                raise HostedContractError("pending row contains claimed execution")
            seen_pending = True
            continue
        if seen_pending or status not in {"COMPLETE_CLAIM", "STOPPED"} or attempts != 1:
            raise HostedContractError("noncontiguous execution or invalid row state")
        if status == "COMPLETE_CLAIM":
            if (type(item["outcome"]) is not bool
                    or not all(_digest(item[key]) for key in (
                        "trace_review_sha256", "native_review_sha256",
                        "billing_review_sha256"))
                    or item["billing_state"] != "ATTRIBUTABLE"
                    or item["stop_scope"] is not None
                    or item["stop_review_sha256"] is not None
                    or item["fresh_context_sha256"] is not None):
                raise HostedContractError("complete claim lacks review or attributable bill")
            complete += 1
        else:
            if (item["outcome"] is not None
                    or any(item[key] is not None for key in (
                        "trace_review_sha256", "native_review_sha256",
                        "billing_review_sha256"))
                    or item["stop_scope"] not in {"ROW_LOCAL", "GLOBAL_HOLD"}
                    or not _digest(item["stop_review_sha256"])
                    or item["billing_state"] not in {
                        "ATTRIBUTABLE", "BOUNDED_WORST_CASE_HELD", "UNKNOWN"}):
                raise HostedContractError("STOPPED must retain missing outcome and stop review")
            stopped += 1
            if (index + 1 < ROWS and isinstance(journal[index + 1], Mapping)
                    and journal[index + 1].get("status") != "PENDING"):
                if (item["stop_scope"] != "ROW_LOCAL"
                        or item["billing_state"] == "UNKNOWN"
                        or not _digest(item["fresh_context_sha256"])):
                    raise HostedContractError("continuation after unresolved STOPPED row")
    return {
        "schema": "bilateral030-hosted-journal-shape-v1",
        "status": "HOLD_SOURCE_ONLY_STRUCTURAL_CLAIMS",
        "permission_to_advance_or_call": False,
        "assigned_rows": ROWS,
        "complete_claims_unverified": complete,
        "stopped_missing_outcome": stopped,
        "pending": ROWS - complete - stopped,
        "next_unattempted_index": complete + stopped if complete + stopped < ROWS else None,
    }


def _digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value)
