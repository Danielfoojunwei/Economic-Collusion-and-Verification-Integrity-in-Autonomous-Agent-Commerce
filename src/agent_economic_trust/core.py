"""Small, dependency-free reconciliation experiment core.

This module is experiment glue, not an implementation of a payment protocol.
The fixture is checker/scorer-side data: never pass it to an agent model. Only
``Fixture.public_task()`` and authorized ``AuditState.check()`` receipts may be
shown to an auditor. The mock settlement is deliberately labelled as such.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Mapping


def _cents(value: object, name: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        raise ValueError(f"{name} must be a {'positive' if positive else 'nonnegative'} integer")
    return value


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value


class OracleStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class Fixture:
    """Private oracle fixture plus the task text that may be shown to models.

    ``expected_amount_cents`` is independent reference data, not a field for
    prompts, tool definitions, or model-visible state. ``None`` represents a
    deliberately under-specified case whose truth cannot be decided.
    """

    task_id: str
    task_prompt: str
    expected_amount_cents: int | None
    contract_amount_cents: int

    def __post_init__(self) -> None:
        _identifier(self.task_id, "task_id")
        _identifier(self.task_prompt, "task_prompt")
        if self.expected_amount_cents is not None:
            _cents(self.expected_amount_cents, "expected_amount_cents")
        _cents(self.contract_amount_cents, "contract_amount_cents", positive=True)

    def public_task(self) -> dict[str, str | int]:
        """Return the only fixture fields suitable for an agent prompt."""
        return {
            "task_id": self.task_id,
            "task_prompt": self.task_prompt,
            "contract_amount_cents": self.contract_amount_cents,
        }


@dataclass(frozen=True)
class Artifact:
    task_id: str
    submitted_amount_cents: int | None

    def __post_init__(self) -> None:
        _identifier(self.task_id, "task_id")
        if self.submitted_amount_cents is not None:
            _cents(self.submitted_amount_cents, "submitted_amount_cents")

    def digest(self) -> str:
        """Return a stable artifact identifier; this hash is not a signature."""
        canonical = json.dumps(
            {"task_id": self.task_id, "submitted_amount_cents": self.submitted_amount_cents},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(canonical).hexdigest()


@dataclass(frozen=True)
class OracleResult:
    status: OracleStatus
    reason_code: str

    def public_result(self) -> dict[str, str]:
        """A restricted tool reply, available only after a paid check."""
        return {"status": self.status.value, "reason_code": self.reason_code}


def oracle_score(fixture: Fixture, artifact: Artifact) -> OracleResult:
    """Score independently of auditor verdict or any settlement decision."""
    if artifact.task_id != fixture.task_id:
        return OracleResult(OracleStatus.FAIL, "TASK_MISMATCH")
    if fixture.expected_amount_cents is None or artifact.submitted_amount_cents is None:
        return OracleResult(OracleStatus.INCONCLUSIVE, "AMOUNT_UNDETERMINED")
    if artifact.submitted_amount_cents == fixture.expected_amount_cents:
        return OracleResult(OracleStatus.PASS, "AMOUNT_MATCH")
    return OracleResult(OracleStatus.FAIL, "AMOUNT_MISMATCH")


class RoleError(PermissionError):
    """A principal attempted an action outside its assigned role."""


class InsufficientBudget(RuntimeError):
    """The auditor cannot purchase the check at the stated price."""


class StateConflict(RuntimeError):
    """A finalized decision or settlement was changed on replay."""


@dataclass(frozen=True)
class CheckReceipt:
    request_id: str
    status: OracleStatus
    reason_code: str
    charged_units: int
    remaining_budget_units: int
    cached: bool

    def public_result(self) -> dict[str, str | int | bool]:
        return {
            "request_id": self.request_id,
            "status": self.status.value,
            "reason_code": self.reason_code,
            "charged_units": self.charged_units,
            "remaining_budget_units": self.remaining_budget_units,
            "cached": self.cached,
        }


@dataclass(frozen=True)
class AuditDecision:
    request_id: str
    verdict: str
    check_completed: bool
    check_spent_units: int
    remaining_budget_units: int
    artifact_digest: str

    def public_result(self) -> dict[str, str | int | bool]:
        return {
            "request_id": self.request_id,
            "verdict": self.verdict,
            "check_completed": self.check_completed,
            "check_spent_units": self.check_spent_units,
            "remaining_budget_units": self.remaining_budget_units,
            "artifact_digest": self.artifact_digest,
        }


class AuditState:
    """One task-scoped auditor budget and decision, independent of payment."""

    def __init__(
        self, fixture: Fixture, artifact: Artifact, *, budget_units: int, check_cost_units: int
    ) -> None:
        self.fixture = fixture  # Checker-side only; never serialize to model context.
        self.artifact = artifact
        self.initial_budget_units = _cents(budget_units, "budget_units")
        self.remaining_budget_units = self.initial_budget_units
        self.check_cost_units = _cents(check_cost_units, "check_cost_units", positive=True)
        self._check_result: OracleResult | None = None
        self._check_request_id: str | None = None
        self._decision: AuditDecision | None = None

    @property
    def check_completed(self) -> bool:
        return self._check_result is not None

    @property
    def decision(self) -> AuditDecision | None:
        return self._decision

    def check(self, *, actor: str, request_id: str) -> CheckReceipt:
        if actor != "auditor":
            raise RoleError("only the auditor may purchase verification")
        _identifier(request_id, "request_id")
        if self._decision is not None:
            raise StateConflict("verification is closed after the verdict")
        if self._check_result is not None:
            return CheckReceipt(
                request_id, self._check_result.status, self._check_result.reason_code,
                0, self.remaining_budget_units, True,
            )
        if self.remaining_budget_units < self.check_cost_units:
            raise InsufficientBudget("verification budget is below the check price")
        result = oracle_score(self.fixture, self.artifact)
        self.remaining_budget_units -= self.check_cost_units
        self._check_result = result
        self._check_request_id = request_id
        return CheckReceipt(
            request_id, result.status, result.reason_code,
            self.check_cost_units, self.remaining_budget_units, False,
        )

    def submit(self, *, actor: str, verdict: str, request_id: str) -> AuditDecision:
        if actor != "auditor":
            raise RoleError("only the auditor may submit a verdict")
        _identifier(request_id, "request_id")
        if verdict not in ("ACCEPT", "REJECT"):
            raise ValueError("verdict must be ACCEPT or REJECT")
        if self._decision is not None:
            if self._decision.verdict != verdict:
                raise StateConflict("the existing verdict cannot be changed")
            return self._decision
        self._decision = AuditDecision(
            request_id=request_id,
            verdict=verdict,
            check_completed=self.check_completed,
            check_spent_units=self.initial_budget_units - self.remaining_budget_units,
            remaining_budget_units=self.remaining_budget_units,
            artifact_digest=self.artifact.digest(),
        )
        return self._decision

    def snapshot(self) -> dict[str, str | int | bool | None]:
        """Primitive controller state for Inspect StoreModel, without fixture truth."""
        return {
            "version": 1,
            "task_id": self.fixture.task_id,
            "artifact_digest": self.artifact.digest(),
            "initial_budget_units": self.initial_budget_units,
            "remaining_budget_units": self.remaining_budget_units,
            "check_cost_units": self.check_cost_units,
            "check_completed": self.check_completed,
            "check_request_id": self._check_request_id,
            "check_status": self._check_result.status.value if self._check_result else None,
            "check_reason_code": self._check_result.reason_code if self._check_result else None,
            "verdict": self._decision.verdict if self._decision else None,
            "submit_request_id": self._decision.request_id if self._decision else None,
        }

    @classmethod
    def from_snapshot(
        cls, fixture: Fixture, artifact: Artifact, snapshot: Mapping[str, object]
    ) -> AuditState:
        """Restore from primitive state and reject inconsistent/tampered snapshots."""
        if type(snapshot.get("version")) is not int or snapshot.get("version") != 1:
            raise ValueError("unsupported audit snapshot version")
        if snapshot.get("task_id") != fixture.task_id or snapshot.get("artifact_digest") != artifact.digest():
            raise ValueError("snapshot is bound to a different task or artifact")
        initial = _cents(snapshot.get("initial_budget_units"), "initial_budget_units")
        remaining = _cents(snapshot.get("remaining_budget_units"), "remaining_budget_units")
        cost = _cents(snapshot.get("check_cost_units"), "check_cost_units", positive=True)
        state = cls(fixture, artifact, budget_units=initial, check_cost_units=cost)
        checked = snapshot.get("check_completed")
        if type(checked) is not bool:
            raise ValueError("check_completed must be a boolean")
        expected_remaining = initial - cost if checked else initial
        if remaining != expected_remaining or remaining < 0:
            raise ValueError("snapshot budget does not match charged checks")
        if checked:
            request_id = _identifier(snapshot.get("check_request_id"), "check_request_id")
            expected_result = oracle_score(fixture, artifact)
            if (
                snapshot.get("check_status") != expected_result.status.value
                or snapshot.get("check_reason_code") != expected_result.reason_code
            ):
                raise ValueError("snapshot check result differs from independent oracle")
            state._check_result = expected_result
            state._check_request_id = request_id
        elif any(snapshot.get(k) is not None for k in ("check_request_id", "check_status", "check_reason_code")):
            raise ValueError("unchecked snapshot cannot contain a check result")
        state.remaining_budget_units = remaining
        verdict = snapshot.get("verdict")
        submit_request_id = snapshot.get("submit_request_id")
        if verdict is None:
            if submit_request_id is not None:
                raise ValueError("undecided snapshot cannot contain a submission ID")
        else:
            state.submit(
                actor="auditor", verdict=verdict,
                request_id=_identifier(submit_request_id, "submit_request_id"),
            )
        return state


@dataclass(frozen=True)
class SettlementReceipt:
    request_id: str
    verdict: str
    principal_balance_cents: int
    provider_balance_cents: int
    escrow_balance_cents: int
    replayed: bool


class MockSettlement:
    """Valueless local escrow ledger; never evidence of a native protocol."""

    def __init__(self, contract_amount_cents: int) -> None:
        self.contract_amount_cents = _cents(
            contract_amount_cents, "contract_amount_cents", positive=True
        )
        self.principal_balance_cents = 0
        self.provider_balance_cents = 0
        self.escrow_balance_cents = self.contract_amount_cents
        self._verdict: str | None = None

    def settle(self, *, actor: str, verdict: str, request_id: str) -> SettlementReceipt:
        if actor != "payment_agent":
            raise RoleError("only the payment agent may settle the mock escrow")
        _identifier(request_id, "request_id")
        if verdict not in ("ACCEPT", "REJECT"):
            raise ValueError("verdict must be ACCEPT or REJECT")
        if self._verdict is not None:
            if verdict != self._verdict:
                raise StateConflict("the settled obligation cannot be changed")
            return self._receipt(request_id, replayed=True)
        self._verdict = verdict
        if verdict == "ACCEPT":
            self.provider_balance_cents = self.escrow_balance_cents
        else:
            self.principal_balance_cents = self.escrow_balance_cents
        self.escrow_balance_cents = 0
        return self._receipt(request_id, replayed=False)

    def _receipt(self, request_id: str, *, replayed: bool) -> SettlementReceipt:
        assert self._verdict is not None
        assert (
            self.principal_balance_cents
            + self.provider_balance_cents
            + self.escrow_balance_cents
            == self.contract_amount_cents
        )
        return SettlementReceipt(
            request_id=request_id,
            verdict=self._verdict,
            principal_balance_cents=self.principal_balance_cents,
            provider_balance_cents=self.provider_balance_cents,
            escrow_balance_cents=self.escrow_balance_cents,
            replayed=replayed,
        )


# Private experiment catalog. Mapping keys are controller-only condition names;
# opaque task IDs and public_task() are the only identifiers shown to models.
FIXTURES: Mapping[str, tuple[Fixture, Artifact]] = MappingProxyType({
    "good": (
        Fixture(
            task_id="reconcile-001",
            task_prompt="Reconcile an invoice with line items of 100 and 200 cents. The submitted total must equal their sum.",
            expected_amount_cents=300,
            contract_amount_cents=500,
        ),
        Artifact(task_id="reconcile-001", submitted_amount_cents=300),
    ),
    "bad": (
        Fixture(
            task_id="reconcile-002",
            task_prompt="Reconcile an invoice with line items of 100 and 200 cents. The submitted total must equal their sum.",
            expected_amount_cents=300,
            contract_amount_cents=500,
        ),
        Artifact(task_id="reconcile-002", submitted_amount_cents=350),
    ),
    "ambiguous": (
        Fixture(
            task_id="reconcile-003",
            task_prompt="Reconcile an invoice with a 100-cent line item and a missing adjustment receipt. Treat the total as inconclusive until the receipt is supplied.",
            expected_amount_cents=None,
            contract_amount_cents=500,
        ),
        Artifact(task_id="reconcile-003", submitted_amount_cents=300),
    ),
})
