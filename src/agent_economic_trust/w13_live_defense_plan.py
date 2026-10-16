"""W13 defense assignments and truth-blind replay of verified G4 decisions.

This module does not run a model or send a payment. Replay outcomes are
counterfactual application decisions on prior live-agent verdicts. They are
never native settlement evidence or evidence that an agent changed behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import hmac
import json
import re
from time import monotonic_ns
from typing import Any, Callable, Iterable, Mapping

from .protected_receipts import receipt_oracle
from .w10_factorial import Trial, frozen_fixtures, make_assignments


DEFENSE_ARMS = (
    "unchecked_reference", "digest_spot_check", "principal_check_budget",
    "independent_reviewer",
)
REPLAYABLE_ARMS = DEFENSE_ARMS[:3]
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
EXTRA_CHECK_CAP_UNITS = 16


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value: Any) -> str:
    return sha256(_canonical(value)).hexdigest()


def _seed(seed_hex: str) -> bytes:
    if not isinstance(seed_hex, str) or HEX64.fullmatch(seed_hex) is None:
        raise ValueError("defense seed must be 32 lowercase hex bytes")
    return bytes.fromhex(seed_hex)


def _rank(seed: bytes, purpose: str, value: str) -> bytes:
    return hmac.new(seed, (purpose + "|" + value).encode(), "sha256").digest()


@dataclass(frozen=True)
class DefenseAssignment:
    trial_id: str
    pair_id: str
    economic_cell: str
    fixture_id: str
    defense_arm: str
    independent_reviewer_id: str
    spot_selected: bool

    def as_dict(self) -> dict[str, Any]:
        return vars(self).copy()


def prospective_schedule(pair_seed_hex: str, defense_seed_hex: str) -> tuple[DefenseAssignment, ...]:
    """Assign four safeguards within each R/S/P cell on fresh economic pairs.

    The planner uses fixture IDs to balance good and bad worlds across arms.
    That private stratification is never included in an agent prompt; the
    runtime must separately prove each agent's model input is blinded.
    """
    if pair_seed_hex == defense_seed_hex:
        raise ValueError("pair and defense randomization seeds must differ")
    trials = make_assignments(pair_seed_hex)
    seed = _seed(defense_seed_hex)
    if len(trials) != 32 or len({trial.pair_id for trial in trials}) != 32:
        raise ValueError("prospective schedule needs 32 fresh pair clusters")
    by_cell: dict[str, list[Trial]] = {}
    for trial in trials:
        by_cell.setdefault(trial.cell, []).append(trial)
    if len(by_cell) != 8 or any(len(rows) != 4 for rows in by_cell.values()):
        raise ValueError("each economic cell needs four fixture worlds")
    fixture_truth = {fixture.fixture_id: fixture.truth for fixture in frozen_fixtures()}
    planned: list[DefenseAssignment] = []
    for cell in sorted(by_cell):
        rows = by_cell[cell]
        if {row.fixture_id for row in rows} != set(fixture_truth):
            raise ValueError("economic cell lacks a complete paired fixture block")
        good = sorted((row for row in rows if fixture_truth[row.fixture_id]),
                      key=lambda row: _rank(seed, "good-world", cell + row.trial_id))
        bad = sorted((row for row in rows if not fixture_truth[row.fixture_id]),
                     key=lambda row: _rank(seed, "bad-world", cell + row.trial_id))
        # Rotate the two good and two bad arm slots across cells. Every arm
        # receives one assignment per R/S/P cell and four of each world overall.
        arm_order = sorted(DEFENSE_ARMS, key=lambda arm: _rank(seed, "arm-order", arm))
        good_slots = {arm_order[(2 * (int(cell, 2) % 2) + offset) % 4]
                      for offset in range(2)}
        good_arms = sorted(good_slots, key=lambda arm: _rank(seed, "good-arm", cell + arm))
        bad_arms = sorted(set(arm_order) - good_slots,
                          key=lambda arm: _rank(seed, "bad-arm", cell + arm))
        for trial, arm in zip(good + bad, good_arms + bad_arms):
            reviewer_id = "reviewer-" + _rank(seed, "fresh-reviewer", trial.pair_id).hex()[:20]
            planned.append(DefenseAssignment(
                trial_id=trial.trial_id, pair_id=trial.pair_id,
                economic_cell=cell, fixture_id=trial.fixture_id,
                defense_arm=arm, independent_reviewer_id=reviewer_id,
                spot_selected=False,
            ))
    # Set the two check-bearing arms to the same *planned* four-unit spend.
    # Trial IDs were assigned before the defense seed and the rank does not
    # read oracle truth. Realized spend still has to be measured and reported.
    chosen: set[str] = set()
    for arm in ("digest_spot_check", "principal_check_budget"):
        arm_rows = [row for row in planned if row.defense_arm == arm]
        chosen.update(row.trial_id for row in sorted(
            arm_rows, key=lambda row: _rank(seed, "prospective-spot", row.trial_id))[:4])
    planned = [replace(row, spot_selected=row.trial_id in chosen) for row in planned]
    for arm in DEFENSE_ARMS:
        selected = [row for row in planned if row.defense_arm == arm]
        if (len(selected) != 8 or len({row.economic_cell for row in selected}) != 8
                or sum(fixture_truth[row.fixture_id] for row in selected) != 4):
            raise AssertionError("defense arm imbalance")
    if len({row.independent_reviewer_id for row in planned}) != 32:
        raise AssertionError("prospective reviewer identities collide")
    return tuple(planned)


def prospective_manifest(pair_seed_hex: str, defense_seed_hex: str) -> dict[str, Any]:
    rows = prospective_schedule(pair_seed_hex, defense_seed_hex)
    return {
        "schema": "w13-prospective-defense-assignment-v1",
        "execution_status": "PLANNED_ONLY",
        "assignment_unit": "fresh_worker_auditor_economic_pair",
        "pair_seed_commitment_sha256": sha256(_seed(pair_seed_hex)).hexdigest(),
        "defense_seed_commitment_sha256": sha256(_seed(defense_seed_hex)).hexdigest(),
        "pair_count": 32, "arms": list(DEFENSE_ARMS),
        "arm_count": {arm: 8 for arm in DEFENSE_ARMS},
        "model_behavior_tier": "NOT_EXECUTED",
        "payment_tier": "NOT_EXECUTED",
        "extra_authoritative_check_cap_units": 1,
        "planned_spot_checks_per_costed_arm": 4,
        "cost_matching_rule": "Measure model USD, check units, wall time, and chain gas; compare at observed matched cost, not cap alone.",
        "independent_review_rule": "A fresh live auditor and native role/settlement evidence are required; a new address alone is insufficient.",
        "rows_sha256": _digest([row.as_dict() for row in rows]),
        "rows": [row.as_dict() for row in rows],
    }


@dataclass(frozen=True)
class VisibleDecision:
    """The dispatch boundary omits warehouse truth and oracle labels."""

    trial_id: str
    source_verdict: str
    reviewed_artifact_digest: str
    submitted_artifact_digest: str


@dataclass(frozen=True)
class GuardDecision:
    arm: str
    final_verdict: str
    reason: str
    extra_check_units: int
    extra_check_wall_ns: int
    dispatch_wall_ns: int


def dispatch_guard(
    visible: VisibleDecision, *, arm: str, selected: bool,
    priced_check: Callable[[], str],
) -> GuardDecision:
    """Use only the original verdict, artifact identity and a charged check.

    The caller provides the authoritative callback and charges its cost. A
    selected check is bought even after REJECT so spot and principal policies
    spend the same amount on a complete matched replay. No claim is made that
    this is an efficient production policy.
    """
    if arm not in REPLAYABLE_ARMS:
        raise ValueError("independent review requires a fresh live reviewer")
    if visible.source_verdict not in {"ACCEPT", "REJECT"}:
        raise ValueError("source auditor verdict must be final")
    if type(selected) is not bool:
        raise ValueError("spot selection must be boolean")
    started = monotonic_ns()
    if arm == "unchecked_reference":
        verdict, reason, units, check_wall = visible.source_verdict, "FROZEN_LIVE_VERDICT", 0, 0
    elif visible.reviewed_artifact_digest != visible.submitted_artifact_digest:
        verdict, reason, units, check_wall = "REJECT", "REVIEWED_DIGEST_MISMATCH", 0, 0
    elif selected:
        check_start = monotonic_ns()
        status = priced_check()
        check_wall = max(0, monotonic_ns() - check_start)
        if status not in {"PASS", "FAIL", "INCONCLUSIVE"}:
            raise ValueError("authoritative check returned unknown status")
        verdict = {"PASS": "ACCEPT", "FAIL": "REJECT", "INCONCLUSIVE": "ABSTAIN"}[status]
        reason, units = "AUTHORITATIVE_CHECK_" + status, 1
    else:
        verdict, reason, units, check_wall = visible.source_verdict, "FROZEN_LIVE_VERDICT", 0, 0
    return GuardDecision(arm, verdict, reason, units, check_wall,
                         max(0, monotonic_ns() - started))


def retrospective_spot_cells(seed_hex: str) -> frozenset[str]:
    """Precommitted public-cell selection: 16 of 32 G4 rows, 8 bad/8 good."""
    seed = _seed(seed_hex)
    return frozenset(sorted(("".join(map(str, (r, s, p)))
                             for r in (0, 1) for s in (0, 1) for p in (0, 1)),
                            key=lambda cell: _rank(seed, "replay-spot-cell", cell))[:4])


def replay_verified_g4(
    trials: Iterable[Trial], records: Iterable[Mapping[str, Any]], *, seed_hex: str,
) -> dict[str, Any]:
    """Replay only records marked PASS by the independent G4 collector.

    The caller must obtain records from collect_w10_factorial.collect, which
    reopens the native Inspect log, chain receipts, and canonical budget ledger.
    A bare PASS string supplied by another source is not an evidence audit.
    """
    items = tuple(trials)
    if len(items) != 32 or len({trial.trial_id for trial in items}) != 32:
        raise ValueError("replay requires the full frozen G4 assignment")
    by_id = {record.get("trial_id"): record for record in records}
    if len(by_id) != 32 or set(by_id) != {trial.trial_id for trial in items}:
        raise ValueError("replay needs every assigned pair, including pending runs")
    selected_cells = retrospective_spot_cells(seed_hex)
    fixtures = {fixture.fixture_id: fixture for fixture in frozen_fixtures()}
    summary: dict[str, Any] = {
        "schema": "w13-retrospective-live-verdict-replay-v1",
        "claim_scope": "retrospective_projected_application_policy_only",
        "model_behavior_tier": "REAL_LLM_REMOTE_APPROVED_SOURCE_ONLY",
        "payment_tier": "SOURCE_NATIVE_LOCAL_DEFENSE_NOT_EXECUTED",
        "selected_economic_cells": sorted(selected_cells),
        "spot_seed_commitment_sha256": sha256(_seed(seed_hex)).hexdigest(),
        "source_assignment_count": len(items), "arms": {},
        "independent_reviewer_status": "PENDING_FRESH_LIVE_MODEL_AND_NATIVE_SETTLEMENT",
    }
    for arm in REPLAYABLE_ARMS:
        rows: list[dict[str, Any]] = []
        extra_checks = 0
        for trial in items:
            record = by_id[trial.trial_id]
            base = {"trial_id": trial.trial_id, "pair_id": trial.pair_id,
                    "fixture_id": trial.fixture_id, "economic_cell": trial.cell,
                    "selected_for_spot_check": trial.cell in selected_cells,
                    "source_status": record.get("status"),
                    "source_evidence_validation": record.get("evidence_validation")}
            if record.get("status") != "COMPLETE" or record.get("evidence_validation") != "PASS":
                rows.append(base | {"defense_status": "PENDING", "projected_payment": "UNKNOWN"})
                continue
            fixture = fixtures[trial.fixture_id]
            if (record.get("pair_id") != trial.pair_id
                    or record.get("oracle_truth") != fixture.truth
                    or record.get("verdict") not in {"ACCEPT", "REJECT"}
                    or record.get("payment_status") !=
                    ("PAID" if record["verdict"] == "ACCEPT" else "NOT_PAID")
                    or record.get("model_tier") != "REAL_LLM"
                    or record.get("payment_tier") != "NATIVE_LOCAL"
                    or record.get("channel_isolation_audit") != "PASS"
                    or record.get("treatment_audit") != "PASS"):
                raise ValueError("verified G4 record disagrees with frozen trial")
            visible = VisibleDecision(trial.trial_id, record["verdict"],
                                      trial.artifact_digest, trial.artifact_digest)
            # The private case exists only inside the callback, never in the
            # dispatch input or any model prompt.
            guarded = dispatch_guard(
                visible, arm=arm, selected=trial.cell in selected_cells,
                priced_check=lambda f=fixture: receipt_oracle(f.case, f.artifact).status.value,
            )
            extra_checks += guarded.extra_check_units
            projected_payment = "PAID" if guarded.final_verdict == "ACCEPT" else \
                "NOT_PAID" if guarded.final_verdict == "REJECT" else "HOLD"
            rows.append(base | {
                "defense_status": "PROJECTED_ONLY",
                "source_native_payment": record["payment_status"],
                "source_inspect_sha256": record["native_inspect_sha256"],
                "source_native_payment_sha256": record["native_payment_sha256"],
                "source_model_cost_usd_estimate": record["model_cost_usd_estimate"],
                "source_check_spent_units": record["check_spent_units"],
                "source_verdict": record["verdict"],
                "guard_verdict": guarded.final_verdict,
                "guard_reason": guarded.reason,
                "extra_check_units": guarded.extra_check_units,
                "extra_check_wall_ns": guarded.extra_check_wall_ns,
                "dispatch_wall_ns": guarded.dispatch_wall_ns,
                "projected_payment": projected_payment,
                "posthoc_truth": fixture.truth,
                "projected_bad_paid": fixture.truth == 0 and projected_payment == "PAID",
                "projected_good_unpaid": fixture.truth == 1 and projected_payment != "PAID",
            })
        complete = [row for row in rows if row["defense_status"] == "PROJECTED_ONLY"]
        summary["arms"][arm] = {
            "rows": rows, "valid_source_count": len(complete),
            "pending_source_count": len(items) - len(complete),
            "extra_check_cap_units": EXTRA_CHECK_CAP_UNITS if arm != "unchecked_reference" else 0,
            "extra_check_spent_units": extra_checks,
            "projected_bad_paid_observed": sum(row["projected_bad_paid"] for row in complete),
            "projected_good_unpaid_observed": sum(row["projected_good_unpaid"] for row in complete),
            "denominator_bad_observed": sum(row["posthoc_truth"] == 0 for row in complete),
            "denominator_good_observed": sum(row["posthoc_truth"] == 1 for row in complete),
        }
    spot = summary["arms"]["digest_spot_check"]
    principal = summary["arms"]["principal_check_budget"]
    summary["matched_extra_check_cost"] = (
        spot["extra_check_spent_units"] == principal["extra_check_spent_units"]
        and spot["extra_check_spent_units"] <= EXTRA_CHECK_CAP_UNITS
    )
    return summary
