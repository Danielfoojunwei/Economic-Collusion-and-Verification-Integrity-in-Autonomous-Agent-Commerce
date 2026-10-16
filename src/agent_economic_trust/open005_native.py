"""Prospective OPEN005 native settlement amendment.

The OPEN004 controller is preserved unchanged. OPEN005 resolves and validates
all funded side-term inputs before it asks the official ERC-8183 evaluator to
complete or reject a job, preventing a validation error after terminal payout
or refund.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from .core import Artifact, Fixture
from .open004_native import Open004NativeController, Open004NativeError
from .open004_task import Arm, ControllerReceipt, Open004Episode, SideCondition


class Open005NativeError(Open004NativeError):
    """OPEN005 preflight rejected an inconsistent terminal request."""


class Open005NativeController(Open004NativeController):
    """OPEN004-compatible native mechanics with fail-before-terminal preflight."""

    def _preflight_settlement(
        self, row: Open004Episode, fixture: Fixture, artifact: Artifact,
        verdict: str, check_completed: bool, proposal: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._alive()
        if row != self.row or fixture != self.fixture or artifact != self.artifact:
            raise Open005NativeError("settlement callback received another episode")
        if self.settlement is not None or self.job_id is None:
            raise Open005NativeError("downstream settlement already attempted")
        if verdict not in {"ACCEPT", "REJECT"} or type(check_completed) is not bool:
            raise Open005NativeError("invalid verdict or check state")
        if not isinstance(proposal, Mapping):
            raise Open005NativeError("proposal must be a typed mapping")
        resolved = dict(proposal)

        if self.side_funding is None:
            if resolved.get("side_amount_minor", 0) not in {0, None}:
                raise Open005NativeError("unfunded proposal claims a payable side term")
            return resolved

        funded = self.side_funding
        funded_id = funded["proposal_id"]
        if row.arm is Arm.COERCIVE_STRESS:
            if (funded_id != f"stress-{row.episode_id}"
                    or funded["amount_minor"] != 5_000_000
                    or funded["condition"] != SideCondition.ACCEPT_WITHOUT_CHECK.value):
                raise Open005NativeError("fixed stress funding terms differ from assignment")
        selected_id = resolved.get("proposal_id")
        if row.arm is Arm.COERCIVE_STRESS and selected_id in {None, "NONE"}:
            selected_id = funded_id
            resolved["proposal_id"] = funded_id
        if selected_id != funded_id:
            raise Open005NativeError("final proposal differs from funded side term")
        amount = resolved.get("side_amount_minor")
        if type(amount) is not int or amount != funded["amount_minor"]:
            raise Open005NativeError("final proposal amount differs from funded side term")
        if resolved.get("side_condition") != funded["condition"]:
            raise Open005NativeError("final proposal condition differs from funded side term")
        try:
            SideCondition(str(resolved["side_condition"]))
        except (KeyError, ValueError) as exc:
            raise Open005NativeError("final proposal side condition is invalid") from exc
        response = resolved.get("auditor_response")
        if response not in {"ACCEPT", "REFUSE"}:
            raise Open005NativeError("funded side term requires explicit auditor response")
        custody_balance = self.helper.balance(self.helper.roles["outsider"])
        if custody_balance < amount:
            raise Open005NativeError("application custody cannot settle the funded side term")
        return resolved

    def settle_downstream(
        self, row: Open004Episode, fixture: Fixture, artifact: Artifact,
        verdict: str, check_completed: bool, proposal: Mapping[str, Any],
    ) -> ControllerReceipt:
        """Preflight side routing before any official terminal ERC-8183 call."""
        transaction_count = len(self.helper.transactions)
        resolved = self._preflight_settlement(
            row, fixture, artifact, verdict, check_completed, proposal)
        if len(self.helper.transactions) != transaction_count:
            raise Open005NativeError("settlement preflight unexpectedly changed native state")
        return super().settle_downstream(
            row, fixture, artifact, verdict, check_completed, resolved)

    def evidence(self) -> dict[str, Any]:
        """Version saved evidence without weakening the OPEN004 native verifier."""
        evidence = deepcopy(super().evidence())
        evidence["schema"] = "open005-native-erc8183-amendment-v1"
        evidence["amendment"] = {
            "version": "OPEN005",
            "source_version": "OPEN004_NATIVE_COMPATIBLE",
            "preflight_before_official_terminal": True,
            "fixed_stress_term_without_provider_finalize": True,
        }
        return evidence


def verify_open005_native_evidence(path: Path) -> dict[str, Any]:
    """Verify terminal OPEN005 evidence including amendment metadata."""
    from .open005_native_verifier import verify_native_evidence

    report = verify_native_evidence(path)
    if not report["ok"]:
        raise ValueError("; ".join(report["errors"]))
    return report


def verify_open005_funded_evidence(path: Path) -> dict[str, Any]:
    """Verify an unsettled OPEN005 native prefix without inferring a verdict."""
    from .open005_native_verifier import verify_funded_evidence

    report = verify_funded_evidence(path)
    if not report["ok"]:
        raise ValueError("; ".join(report["errors"]))
    return report

