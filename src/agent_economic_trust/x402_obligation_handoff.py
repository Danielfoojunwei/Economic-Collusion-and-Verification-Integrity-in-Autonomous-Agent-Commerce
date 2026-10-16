"""Application handoff from a verified local x402 purchase to an invoice job.

This module cannot certify invoice quality.  The strict policy checks that the
*paid body* belongs to the target obligation.  The permissive policy is an
explicit positive control for an application that treats paid access as enough
authority to act on an auditor's ACCEPT request.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from .x402_invoice_adapter import (
    PUBLIC_TASK_ID, PermissivePaidBodyAdapter, StrictInvoiceReportAdapter,
)
from .x402_invoice_verifier import verify_purchase


PERMISSIVE = "PERMISSIVE_PAID_BODY"
STRICT = "STRICT_TASK_OBLIGATION_DIGEST"


@dataclass(frozen=True)
class Handoff:
    policy: str
    source_obligation_id: str
    target_obligation_id: str
    source_report_digest: str
    target_report_digest: str
    payment_transaction_hash: str
    payment_amount_minor: int
    target_binding_valid: bool
    target_binding_reason: str
    requested_verdict: str
    dispatched_verdict: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def assess_paid_report(*, purchase_dir: Path, target_obligation_id: str,
                       target_report_digest: str, requested_verdict: str,
                       policy: str) -> Handoff:
    """Replay source payment evidence before allowing a target dispatch.

    The x402 verifier reads the original native transaction, HTTP exchange and
    served body.  This call does not make another payment or consult an invoice
    oracle.  A strict target binding can therefore still pass for a BAD report.
    """
    if policy not in {PERMISSIVE, STRICT} or requested_verdict not in {"ACCEPT", "REJECT"}:
        raise ValueError("unsupported handoff policy or verdict")
    if (not isinstance(target_obligation_id, str) or not target_obligation_id
            or not isinstance(target_report_digest, str) or len(target_report_digest) != 64
            or any(char not in "0123456789abcdef" for char in target_report_digest)):
        raise ValueError("target obligation or report digest differs")
    verified = verify_purchase(Path(purchase_dir))
    if not (verified.status == "PASS" and verified.protocol_charge_valid
            and verified.application_binding_valid):
        raise ValueError("source x402 payment or its own application binding is invalid")
    body = json.loads((Path(purchase_dir) / "resource-body.json").read_text())
    if (body["application_binding"]["obligation_id"] != verified.obligation_id
            or body["report_digest"] != verified.report_digest):
        raise ValueError("source report differs from independent x402 verification")
    expected = {"task_id": PUBLIC_TASK_ID,
                "obligation_id": target_obligation_id,
                "expected_report_digest": target_report_digest}
    strict_binding = StrictInvoiceReportAdapter().assess(body, expected)
    selected = (strict_binding if policy == STRICT else
                PermissivePaidBodyAdapter().assess(body, expected))
    dispatch = ("ACCEPT" if requested_verdict == "ACCEPT" and selected.accepted
                else "REJECT")
    return Handoff(
        policy=policy, source_obligation_id=verified.obligation_id,
        target_obligation_id=target_obligation_id,
        source_report_digest=verified.report_digest,
        target_report_digest=target_report_digest,
        payment_transaction_hash=verified.transaction_hash,
        payment_amount_minor=verified.amount_minor_units,
        target_binding_valid=strict_binding.accepted,
        target_binding_reason=strict_binding.reason,
        requested_verdict=requested_verdict, dispatched_verdict=dispatch,
    )
