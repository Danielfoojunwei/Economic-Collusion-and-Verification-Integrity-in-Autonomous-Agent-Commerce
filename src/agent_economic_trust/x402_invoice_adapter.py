"""Bounded model-facing adapter for native-local x402 invoice-report access.

The controller exposes a quote and one explicit ``buy_report`` action.  It does
not expose a wallet, signer, mnemonic, arbitrary URL, or arbitrary recipient.
The pinned W08 runner owns the disposable signer and local chain.  Raw protocol
evidence stays in the controller evidence directory; the returned receipt is a
small typed view suitable for an agent tool result.

This adapter charges for HTTP access.  Report correctness and downstream
invoice approval remain separate application decisions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping

from .core import Artifact, FIXTURES


ROOT = Path(__file__).resolve().parents[2]
X402_RUNNER = ROOT / "scripts" / "run_x402_local.mjs"
X402_RUNNER_SHA256 = "f7a4c21b625e916def700e7e6741ea02163bd71a45a07a8f81bbd0fc43cff2e0"
X402_COMMIT = "e95b06661e1a2a8a9a21fce34cc28b9934834650"
SERVICE_ID = "invoice-report-access/v1"
NATIVE_AMOUNT_MINOR = 1000
NATIVE_ASSET_LABEL = "valueless local Research Test USD"
# Anvil account index 3 under the mnemonic held by the pinned runner.
NATIVE_SELLER = "0x90f79bf6eb2c4f870365e785982e1f101e93b906"


class PurchaseRefused(ValueError):
    """The requested action is outside the frozen quote, role, or bounds."""


class NativePurchaseFailed(RuntimeError):
    """The native-local runner failed after a valid purchase intent."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    if len(value) > 160:
        raise ValueError(f"{name} exceeds 160 characters")
    return value


@dataclass(frozen=True)
class InvoiceAccessQuote:
    quote_id: str
    service_id: str
    amount_minor_units: int
    asset: str
    recipient: str
    task_id: str
    task_prompt: str
    obligation_id: str
    expected_report_digest: str
    transaction_tier: str = "NATIVE_LOCAL_PROTOCOL"

    def public_result(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ReportDocument:
    task_id: str
    submitted_amount_cents: int | None
    digest: str

    def public_result(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ReportPurchaseReceipt:
    """Safe model-facing evidence; raw authorization material is omitted."""

    request_id: str
    quote_id: str
    service_id: str
    amount_minor_units: int
    recipient: str
    transaction_hash: str
    transfer_log_index: int
    protocol_paid: bool
    application_binding_valid: bool
    application_binding_reason: str
    report: ReportDocument
    receipt_id: str
    transaction_tier: str = "NATIVE_LOCAL_PROTOCOL"

    def public_result(self) -> dict[str, object]:
        value = asdict(self)
        # The absence of these fields is a deliberate model boundary.
        assert not ({"signature", "authorization", "mnemonic", "private_key"} & value.keys())
        return value


@dataclass(frozen=True)
class ApplicationBinding:
    accepted: bool
    reason: str


class StrictInvoiceReportAdapter:
    """Require the paid body to match the frozen task, obligation, and digest."""

    name = "STRICT_TASK_OBLIGATION_DIGEST"

    def assess(self, body: Mapping[str, Any], expected: Mapping[str, Any]) -> ApplicationBinding:
        binding = body.get("application_binding")
        report = body.get("report")
        if not isinstance(binding, Mapping) or not isinstance(report, Mapping):
            return ApplicationBinding(False, "MALFORMED_REPORT_BODY")
        if report.get("task_id") != expected["task_id"]:
            return ApplicationBinding(False, "TASK_MISMATCH")
        if binding.get("task_id") != expected["task_id"]:
            return ApplicationBinding(False, "BOUND_TASK_MISMATCH")
        if binding.get("obligation_id") != expected["obligation_id"]:
            return ApplicationBinding(False, "OBLIGATION_MISMATCH")
        observed_digest = canonical_sha256({
            "task_id": report.get("task_id"),
            "submitted_amount_cents": report.get("submitted_amount_cents"),
        })
        if observed_digest != expected["expected_report_digest"]:
            return ApplicationBinding(False, "REPORT_DIGEST_MISMATCH")
        if body.get("report_digest") != observed_digest:
            return ApplicationBinding(False, "BODY_DIGEST_MISMATCH")
        expected_binding = canonical_sha256({
            "task_id": expected["task_id"],
            "obligation_id": expected["obligation_id"],
            "report_digest": expected["expected_report_digest"],
        })
        if binding.get("binding_sha256") != expected_binding:
            return ApplicationBinding(False, "BINDING_DIGEST_MISMATCH")
        return ApplicationBinding(True, "EXACT_BINDING_MATCH")


class PermissivePaidBodyAdapter:
    """Positive control that treats any paid report-shaped body as usable."""

    name = "PERMISSIVE_X402_PAID_BODY_POSITIVE_CONTROL"

    def assess(self, body: Mapping[str, Any], expected: Mapping[str, Any]) -> ApplicationBinding:
        del expected
        report = body.get("report")
        if isinstance(report, Mapping) and "task_id" in report and "submitted_amount_cents" in report:
            return ApplicationBinding(True, "PAID_BODY_ACCEPTED_WITHOUT_BINDING")
        return ApplicationBinding(False, "MALFORMED_REPORT_BODY")


def build_resource_body(*, artifact: Artifact, obligation_id: str) -> dict[str, object]:
    report = {
        "task_id": artifact.task_id,
        "submitted_amount_cents": artifact.submitted_amount_cents,
    }
    report_digest = artifact.digest()
    binding = {
        "task_id": artifact.task_id,
        "obligation_id": obligation_id,
        "report_digest": report_digest,
    }
    return {
        "schema_version": 1,
        "resource_type": "invoice_audit_report",
        "service_id": SERVICE_ID,
        "report": report,
        "report_digest": report_digest,
        "application_binding": {
            **binding,
            "binding_sha256": canonical_sha256(binding),
        },
    }


class InvoiceX402Controller:
    """One assignment-scoped x402 access controller.

    ``case`` and ``served_case`` are controller-only fixture selectors.  The
    latter exists solely for the predeclared body-substitution positive control.
    Models receive only :meth:`quote` and may invoke :meth:`buy_report`.
    """

    def __init__(
        self,
        *,
        case: str,
        obligation_id: str,
        output_dir: Path,
        port: int,
        served_case: str | None = None,
    ) -> None:
        if case not in ("good", "bad"):
            raise ValueError("case must select a GOOD or BAD core invoice fixture")
        if served_case is not None and served_case not in ("good", "bad"):
            raise ValueError("served_case must select a GOOD or BAD core invoice fixture")
        if type(port) is not int or not 1024 < port < 65480:
            raise ValueError("port is outside the bounded loopback range")
        self._case = case
        self._served_case = served_case or case
        self._obligation_id = _identifier(obligation_id, "obligation_id")
        self._output_dir = Path(output_dir)
        self._port = port
        self._completed_request_id: str | None = None
        self._completed_receipt: ReportPurchaseReceipt | None = None

        fixture, artifact = FIXTURES[case]
        quote_base = {
            "service_id": SERVICE_ID,
            "amount_minor_units": NATIVE_AMOUNT_MINOR,
            "asset": NATIVE_ASSET_LABEL,
            "recipient": NATIVE_SELLER,
            "task_id": fixture.task_id,
            "task_prompt": fixture.task_prompt,
            "obligation_id": self._obligation_id,
            "expected_report_digest": artifact.digest(),
        }
        self._quote = InvoiceAccessQuote(
            quote_id=canonical_sha256(quote_base),
            **quote_base,
        )

    def quote(self) -> InvoiceAccessQuote:
        """Return immutable public terms without initiating payment."""
        return self._quote

    def buy_report(
        self,
        *,
        actor: str,
        request_id: str,
        intent: str,
        quote_id: str,
        service_id: str,
        amount_minor_units: int,
        recipient: str,
    ) -> ReportPurchaseReceipt:
        """Execute one exact native-local purchase after explicit agent intent."""
        request_id = _identifier(request_id, "request_id")
        if self._completed_receipt is not None:
            if request_id == self._completed_request_id:
                return self._completed_receipt
            raise PurchaseRefused("REPORT_ALREADY_PURCHASED")
        if actor != "auditor":
            raise PurchaseRefused("ONLY_AUDITOR_MAY_BUY_REPORT")
        if intent != "BUY_REPORT":
            raise PurchaseRefused("EXPLICIT_BUY_REPORT_INTENT_REQUIRED")
        selected = (quote_id, service_id, amount_minor_units, recipient.lower())
        frozen = (
            self._quote.quote_id,
            self._quote.service_id,
            self._quote.amount_minor_units,
            self._quote.recipient.lower(),
        )
        if selected != frozen:
            raise PurchaseRefused("SELECTION_DOES_NOT_MATCH_FROZEN_QUOTE")
        if _file_sha256(X402_RUNNER) != X402_RUNNER_SHA256:
            raise NativePurchaseFailed("pinned x402 runner source changed")
        if self._output_dir.exists():
            raise NativePurchaseFailed("refusing to overwrite x402 invoice evidence")

        self._output_dir.mkdir(parents=True)
        _, served_artifact = FIXTURES[self._served_case]
        resource_body = build_resource_body(
            artifact=served_artifact,
            obligation_id=self._obligation_id,
        )
        resource_path = self._output_dir / "resource-body.json"
        raw_path = self._output_dir / "raw-native-x402.json"
        intent_path = self._output_dir / "purchase-intent.json"
        resource_path.write_text(json.dumps(resource_body, indent=2, sort_keys=True) + "\n")
        intent_record = {
            "schema_version": 1,
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "request_id": request_id,
            "intent": intent,
            "quote": self._quote.public_result(),
            "selected": {
                "quote_id": quote_id,
                "service_id": service_id,
                "amount_minor_units": amount_minor_units,
                "recipient": recipient,
            },
            "positive_control": (
                "BODY_SUBSTITUTION" if self._served_case != self._case else None
            ),
            "runner": {
                "path": "scripts/run_x402_local.mjs",
                "sha256": X402_RUNNER_SHA256,
                "x402_commit": X402_COMMIT,
            },
        }
        intent_path.write_text(json.dumps(intent_record, indent=2, sort_keys=True) + "\n")

        result = subprocess.run(
            [
                "node", str(X402_RUNNER), "--port", str(self._port),
                "--resource-record-file", str(resource_path), "--output", str(raw_path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        (self._output_dir / "runner.stdout.txt").write_text(result.stdout)
        (self._output_dir / "runner.stderr.txt").write_text(result.stderr)
        if result.returncode != 0 or not raw_path.is_file():
            raise NativePurchaseFailed(
                f"native x402 runner failed with exit code {result.returncode}"
            )

        # Import only after raw evidence exists.  This verifier rereads files and
        # does not trust controller objects or the runner's PASS summary.
        from .x402_invoice_verifier import verify_purchase

        verified = verify_purchase(self._output_dir)
        (self._output_dir / "independent-verification.json").write_text(
            json.dumps(verified.to_dict(), indent=2, sort_keys=True) + "\n"
        )
        raw = json.loads(raw_path.read_text())
        body = raw["http"]["resourceBody"]
        report = body["report"]
        strict = StrictInvoiceReportAdapter().assess(body, asdict(self._quote))
        receipt = ReportPurchaseReceipt(
            request_id=request_id,
            quote_id=quote_id,
            service_id=service_id,
            amount_minor_units=amount_minor_units,
            recipient=recipient.lower(),
            transaction_hash=verified.transaction_hash,
            transfer_log_index=verified.transfer_log_index,
            protocol_paid=verified.protocol_charge_valid,
            application_binding_valid=strict.accepted,
            application_binding_reason=strict.reason,
            report=ReportDocument(
                task_id=str(report["task_id"]),
                submitted_amount_cents=report["submitted_amount_cents"],
                digest=canonical_sha256(report),
            ),
            receipt_id=canonical_sha256({
                "request_id": request_id,
                "transaction_hash": verified.transaction_hash,
                "report_digest": canonical_sha256(report),
            }),
        )
        self._completed_request_id = request_id
        self._completed_receipt = receipt
        return receipt


def public_contract_facts(case: str) -> dict[str, object]:
    """Return comparison fields that must match across GOOD and BAD cells."""
    fixture, _ = FIXTURES[case]
    return {
        "task_prompt": fixture.task_prompt,
        "contract_amount_cents": fixture.contract_amount_cents,
        "service_id": SERVICE_ID,
        "amount_minor_units": NATIVE_AMOUNT_MINOR,
        "asset": NATIVE_ASSET_LABEL,
        "recipient": NATIVE_SELLER,
    }
