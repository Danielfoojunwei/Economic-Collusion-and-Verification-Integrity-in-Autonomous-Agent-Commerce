"""W13 local application-policy controls for protected receipt submissions.

These are deterministic *post-decision* dispatch controls over authored ACCEPT
verdicts. They do not measure how a live auditor responds to a changed budget
or reviewer assignment. Hidden warehouse truth is accessible only through the
priced check closure and through outcome scoring after a decision is frozen.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
from time import monotonic_ns
from typing import Any, Callable, Iterable

from .protected_receipts import ReceiptArtifact, ReceiptCase, receipt_oracle
from .w10_factorial import FrozenFixture, frozen_fixtures


CHECK_COST_UNITS = 1
MATCHED_CHECK_CAP_UNITS = 2
SPOT_SEED_HEX = "a1304b3294dc6e1b6cc5c7633227398ec1f979a03aa783404938420d2a4cbad1"
COSTED_CANDIDATES = (
    "spot_check", "principal_budget", "independent_assignment",
)
POLICIES = ("unchecked_baseline", *COSTED_CANDIDATES)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _hash(value: Any) -> str:
    return sha256(_canonical(value)).hexdigest()


@dataclass(frozen=True)
class VisibleSubmission:
    """Only facts available before an authoritative warehouse check."""

    task_id: str
    public_task_sha256: str
    provider_evidence_digest: str
    reviewed_artifact_digest: str
    submitted_artifact_digest: str
    accepted_count: int
    claimed_amount_minor: int


def visible_submission(fixture: FrozenFixture,
                       *, submitted_digest: str | None = None) -> VisibleSubmission:
    return VisibleSubmission(
        task_id=fixture.case.task_id,
        public_task_sha256=_hash(fixture.case.public_task()),
        provider_evidence_digest=fixture.case.provider_digest(),
        reviewed_artifact_digest=fixture.artifact.digest(),
        submitted_artifact_digest=(fixture.artifact.digest() if submitted_digest is None
                                   else submitted_digest),
        accepted_count=fixture.artifact.accepted_count,
        claimed_amount_minor=fixture.artifact.claimed_amount_minor,
    )


def spot_plan(fixtures: Iterable[FrozenFixture], *, cap_units: int = MATCHED_CHECK_CAP_UNITS,
              seed_hex: str = SPOT_SEED_HEX) -> frozenset[str]:
    """Select a whole public-task pair without reading its private world label.

    This narrow calibration has exactly two task domains with two hidden worlds
    each. One public task is selected, so both counterfactual worlds get checked
    and the three costed policies spend exactly two units apiece.
    """
    items = tuple(fixtures)
    if len(items) != 4 or type(cap_units) is not int or cap_units != 2:
        raise ValueError("this matched control requires four worlds and two check units")
    try:
        seed = bytes.fromhex(seed_hex)
    except (TypeError, ValueError) as exc:
        raise ValueError("spot seed must be 32 hex bytes") from exc
    if len(seed) != 32 or len(seed_hex) != 64:
        raise ValueError("spot seed must be 32 hex bytes")
    groups: dict[str, int] = {}
    for fixture in items:
        key = _hash(fixture.case.public_task())
        groups[key] = groups.get(key, 0) + 1
    if sorted(groups.values()) != [2, 2]:
        raise ValueError("expected two paired public-task worlds")
    selected = min(groups, key=lambda key: hmac.new(seed, key.encode("ascii"), "sha256").digest())
    return frozenset({selected})


class CheckBudgetExhausted(RuntimeError):
    pass


@dataclass(frozen=True)
class CheckResult:
    status: str
    reason_code: str
    charged_units: int
    wall_ns: int


class PricedCheckLedger:
    """Application-level check allowance, not a native token transfer."""

    def __init__(self, owner: str, *, cap_units: int = MATCHED_CHECK_CAP_UNITS):
        if owner not in {"auditor", "principal"} or type(cap_units) is not int or cap_units < 0:
            raise ValueError("invalid application check allowance")
        self.owner = owner
        self.cap_units = cap_units
        self.spent_units = 0
        self.calls = 0
        self.total_wall_ns = 0

    def check(self, case: ReceiptCase, artifact: ReceiptArtifact) -> CheckResult:
        if self.spent_units + CHECK_COST_UNITS > self.cap_units:
            raise CheckBudgetExhausted("authoritative check budget exhausted")
        started = monotonic_ns()
        result = receipt_oracle(case, artifact)
        wall_ns = max(0, monotonic_ns() - started)
        self.spent_units += CHECK_COST_UNITS
        self.calls += 1
        self.total_wall_ns += wall_ns
        return CheckResult(result.status.value, result.reason_code, CHECK_COST_UNITS, wall_ns)


@dataclass(frozen=True)
class DispatchDecision:
    policy: str
    frozen_auditor_verdict: str
    reviewer_role: str
    verdict: str
    reason: str
    dispatch_intent: str
    digest_bound: bool
    selected_for_check: bool
    check_status: str | None
    check_charged_units: int
    check_wall_ns: int
    application_wall_ns: int

    def as_dict(self) -> dict[str, Any]:
        return vars(self).copy()


def dispatch_decision(
    visible: VisibleSubmission, *, policy: str,
    selected_for_check: bool, check: Callable[[], CheckResult],
    eligible_reviewers: tuple[str, ...] = ("default_evaluator", "independent_evaluator"),
) -> DispatchDecision:
    """Decide from visible fields and a priced check callback, never private truth."""
    if policy not in POLICIES:
        raise ValueError("unknown candidate policy")
    started = monotonic_ns()
    if policy == "independent_assignment":
        if "independent_evaluator" not in eligible_reviewers:
            reviewer = "NONE"
            verdict, reason = "ABSTAIN", "NO_ELIGIBLE_INDEPENDENT_REVIEWER"
        else:
            reviewer = "independent_evaluator"
            verdict, reason = "ACCEPT", "FROZEN_UNCHECKED_ACCEPT"
    else:
        reviewer = "default_evaluator"
        verdict, reason = "ACCEPT", "FROZEN_UNCHECKED_ACCEPT"
    bound = visible.reviewed_artifact_digest == visible.submitted_artifact_digest
    checked: CheckResult | None = None
    if policy != "unchecked_baseline" and verdict != "ABSTAIN":
        if not bound:
            verdict, reason = "REJECT", "REVIEWED_DIGEST_MISMATCH"
        elif selected_for_check:
            try:
                checked = check()
            except CheckBudgetExhausted:
                verdict, reason = "ABSTAIN", "CHECK_BUDGET_EXHAUSTED"
            else:
                verdict = {"PASS": "ACCEPT", "FAIL": "REJECT",
                           "INCONCLUSIVE": "ABSTAIN"}[checked.status]
                reason = "AUTHORITATIVE_CHECK_" + checked.status
    return DispatchDecision(
        policy=policy, frozen_auditor_verdict="ACCEPT",
        reviewer_role=reviewer, verdict=verdict, reason=reason,
        dispatch_intent={"ACCEPT": "COMPLETE", "REJECT": "REJECT",
                         "ABSTAIN": "HOLD"}[verdict],
        digest_bound=bound, selected_for_check=selected_for_check,
        check_status=checked.status if checked else None,
        check_charged_units=checked.charged_units if checked else 0,
        check_wall_ns=checked.wall_ns if checked else 0,
        application_wall_ns=max(0, monotonic_ns() - started),
    )


def evaluate_policy(policy: str, *, fixtures: Iterable[FrozenFixture] | None = None,
                    seed_hex: str = SPOT_SEED_HEX) -> dict[str, Any]:
    """Offline intent/cost replay. No settlement is executed by this function."""
    items = tuple(fixtures if fixtures is not None else frozen_fixtures())
    selected = spot_plan(items, seed_hex=seed_hex)
    if policy not in POLICIES:
        raise ValueError("unknown candidate policy")
    owner = "principal" if policy == "principal_budget" else "auditor"
    ledger = PricedCheckLedger(owner)
    rows: list[dict[str, Any]] = []
    for fixture in items:
        visible = visible_submission(fixture)
        choice = visible.public_task_sha256 in selected
        decision = dispatch_decision(
            visible, policy=policy,
            selected_for_check=choice if policy != "unchecked_baseline" else False,
            check=lambda f=fixture: ledger.check(f.case, f.artifact),
        )
        rows.append({
            **decision.as_dict(), "fixture_id": fixture.fixture_id,
            "domain": fixture.domain,
            "public_task_sha256": visible.public_task_sha256,
            "artifact_digest": visible.submitted_artifact_digest,
            "oracle_truth_for_posthoc_scoring": fixture.truth,
            "projected_wrongful_payment": fixture.truth == 0 and decision.dispatch_intent == "COMPLETE",
            "projected_honest_nonpayment": fixture.truth == 1 and decision.dispatch_intent != "COMPLETE",
        })
    return {
        "policy": policy,
        "model_behavior_tier": "SCRIPTED_SIMULATION",
        "payment_tier": "NOT_EXECUTED",
        "selection_seed_hex": seed_hex,
        "selected_public_task_sha256": sorted(selected),
        "check_cap_units": ledger.cap_units,
        "check_owner": ledger.owner,
        "check_spent_units": ledger.spent_units,
        "check_calls": ledger.calls,
        "check_wall_ns": ledger.total_wall_ns,
        "application_wall_ns": sum(row["application_wall_ns"] for row in rows),
        "projected_wrongful_payment_count": sum(row["projected_wrongful_payment"] for row in rows),
        "projected_honest_nonpayment_count": sum(row["projected_honest_nonpayment"] for row in rows),
        "rows": rows,
    }


def ideal_oracle_upper_bound(fixtures: Iterable[FrozenFixture] | None = None) -> dict[str, Any]:
    """Diagnostic only: reads hidden truth and has no measured check cost."""
    items = tuple(fixtures if fixtures is not None else frozen_fixtures())
    return {
        "label": "APPLICATION_IDEAL_ORACLE_UPPER_BOUND_NOT_PRACTICAL",
        "check_cost_measured": False,
        "rows": [{"fixture_id": item.fixture_id, "verdict":
                  "ACCEPT" if item.truth else "REJECT"} for item in items],
    }
