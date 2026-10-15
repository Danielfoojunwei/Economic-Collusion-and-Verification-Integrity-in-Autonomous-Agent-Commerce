"""Assignment-owned native-local x402 payment for invoice audit intake.

The controller signs with disposable local keys outside ORBIT. Its response is
an intake receipt, not a quality certificate or an auditor verdict.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess

from .ap2_live_fixture import invoice_case


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts/run_x402_audit_retainer.mjs"
SERVICE_ID = "independent-invoice-audit-intake/v1"
FEE_MINOR = 2_000_000
ASSET = "valueless local Research Test USD"
AUDITOR_WALLET = "0x90f79bf6eb2c4f870365e785982e1f101e93b906"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def digest(value: object) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


@dataclass(frozen=True)
class RetainerAssignment:
    episode_id: str
    obligation_id: str
    truth: str
    payer_role: str

    def validate(self) -> None:
        if self.truth not in {"good", "bad"} or self.payer_role not in {"provider", "buyer"}:
            raise ValueError("truth and payer role must be assigned before execution")
        for name, value in (("episode_id", self.episode_id),
                            ("obligation_id", self.obligation_id)):
            if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{8,100}", value) is None:
                raise ValueError(f"{name} must be a bounded opaque identifier")


def public_report(row: RetainerAssignment) -> dict[str, object]:
    row.validate()
    _, artifact = invoice_case(row.truth)
    return {"submitted_amount_cents": artifact.submitted_amount_cents,
            "report_digest": digest({"submitted_amount_cents": artifact.submitted_amount_cents,
                                     "obligation_id": row.obligation_id})}


def intake_body(row: RetainerAssignment) -> dict[str, object]:
    """The paid endpoint acknowledges intake, with exact task binding only."""
    report = public_report(row)
    terms = {"service_id": SERVICE_ID, "obligation_id": row.obligation_id,
             "report_digest": report["report_digest"], "payer_role": row.payer_role,
             "payee": AUDITOR_WALLET, "amount_minor_units": FEE_MINOR}
    return {"schema_version": 1, "resource_type": "invoice_audit_intake_ack",
            **terms, "binding_sha256": digest(terms),
            "acknowledgment": "PAID_INTAKE_ONLY", "proves_invoice_quality": False,
            "audit_verdict": None}


def public_receipt(row: RetainerAssignment, verified: dict) -> dict:
    """Safe model-facing receipt; no signer, secret, oracle or raw payload."""
    if (verified.get("status") != "PASS" or verified.get("protocol_settled") is not True
            or verified.get("payer_role") != row.payer_role
            or verified.get("payee") != AUDITOR_WALLET
            or verified.get("amount_minor_units") != FEE_MINOR
            or verified.get("body_sha256") != digest(intake_body(row))):
        raise ValueError("native x402 retainer was not independently verified")
    return {"status": "AUDIT_INTAKE_PAID", "service_id": SERVICE_ID,
            "obligation_id": row.obligation_id,
            "payer_role": row.payer_role, "payee_role": "auditor",
            "payee": AUDITOR_WALLET, "amount_minor_units": FEE_MINOR,
            "transaction_hash": verified["transaction_hash"],
            "body_sha256": verified["body_sha256"],
            "transaction_tier": "NATIVE_LOCAL_PROTOCOL",
            "proves_invoice_quality": False, "audit_verdict": None}


def run_native_intake(row: RetainerAssignment, output: Path, *, port: int) -> dict:
    """Run the exact local endpoint once; preserve evidence on every failure."""
    row.validate()
    if type(port) is not int or not 1024 < port < 65480:
        raise ValueError("port must leave room for local x402 HTTP endpoints")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    body_path = output / "intake-body.json"
    body_path.write_text(json.dumps(intake_body(row), indent=2, sort_keys=True) + "\n")
    (output / "assignment.json").write_text(json.dumps(asdict(row), indent=2,
                                                 sort_keys=True) + "\n")
    result = subprocess.run(["node", str(RUNNER), "--port", str(port),
                             "--payer-role", row.payer_role,
                             "--resource-record-file", str(body_path),
                             "--output", str(output / "raw-native-x402.json")],
                            cwd=ROOT, capture_output=True, text=True,
                            timeout=120, check=False)
    (output / "runner.stdout.txt").write_text(result.stdout)
    (output / "runner.stderr.txt").write_text(result.stderr)
    if result.returncode:
        raise RuntimeError(f"native x402 retainer failed (exit {result.returncode})")
    from .x402_audit_retainer_verifier import verify_intake
    verification = verify_intake(output, row)
    (output / "independent-verification.json").write_text(
        json.dumps(verification, indent=2, sort_keys=True) + "\n")
    return public_receipt(row, verification)
