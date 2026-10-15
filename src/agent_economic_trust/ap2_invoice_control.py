"""Local adapter decision controls at the AP2 purchase/invoice quality boundary."""

from __future__ import annotations

from .core import OracleStatus


def dispatch_invoice_verdict(*, requested_verdict: str, ap2_purchase_authorized: bool,
                             oracle_status: OracleStatus | None, strict: bool) -> str:
    """Return a scripted application verdict; AP2 is never an invoice oracle.

    The permissive branch deliberately demonstrates the application error:
    treating valid purchase authorization as sufficient evidence for an ACCEPT
    request. The strict branch requires the independent invoice oracle.
    """
    if requested_verdict not in {"ACCEPT", "REJECT"}:
        raise ValueError("invalid scripted verdict")
    if not ap2_purchase_authorized:
        raise ValueError("AP2 audit-service purchase authorization was not verified")
    if not strict:
        return requested_verdict
    if oracle_status is OracleStatus.PASS:
        return requested_verdict
    if oracle_status is OracleStatus.FAIL:
        return "REJECT"
    raise ValueError("strict invoice guard requires conclusive independent oracle")
