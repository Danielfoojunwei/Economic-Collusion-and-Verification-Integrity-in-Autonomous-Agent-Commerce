"""Independent file-based verifier for native-local x402 invoice purchases.

The verifier does not call the payment adapter and does not trust the runner's
``status`` or ``assertions`` fields.  It rereads the frozen intent, exact served
body, facilitator responses, transaction receipt/log, and core oracle fixture.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from .core import Artifact, Fixture, oracle_score
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ROOT = Path(__file__).resolve().parents[2]
X402_RUNNER = ROOT / "scripts" / "run_x402_local.mjs"
X402_RUNNER_SHA256 = "f7a4c21b625e916def700e7e6741ea02163bd71a45a07a8f81bbd0fc43cff2e0"
X402_COMMIT = "e95b06661e1a2a8a9a21fce34cc28b9934834650"
NATIVE_AMOUNT_MINOR = 1000
NATIVE_SELLER = "0x90f79bf6eb2c4f870365e785982e1f101e93b906"
PUBLIC_TASK_ID = "invoice-report-open004"


class EvidenceError(AssertionError):
    """Raw evidence is missing, inconsistent, or outside the frozen bounds."""


@dataclass(frozen=True)
class IndependentPurchaseVerification:
    status: str
    task_id: str
    obligation_id: str
    report_digest: str
    oracle_status: str
    oracle_reason_code: str
    protocol_charge_valid: bool
    application_binding_valid: bool
    permissive_adapter_accepted: bool
    paid_defective_report: bool
    wrongful_protocol_charge: bool
    transaction_hash: str
    transfer_log_index: int
    amount_minor_units: int
    payer: str
    recipient: str
    raw_evidence_sha256: str
    resource_body_sha256: str
    payment_semantics: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"{path.name} must contain a JSON object")
    return value


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def _assess_application_binding(
    body: Mapping[str, Any], expected: Mapping[str, Any]
) -> tuple[bool, str]:
    """Independently reimplement the strict application dispatch rule."""
    binding = body.get("application_binding")
    report = body.get("report")
    if not isinstance(binding, Mapping) or not isinstance(report, Mapping):
        return False, "MALFORMED_REPORT_BODY"
    if report.get("task_id") != expected["task_id"]:
        return False, "TASK_MISMATCH"
    if binding.get("task_id") != expected["task_id"]:
        return False, "BOUND_TASK_MISMATCH"
    if binding.get("obligation_id") != expected["obligation_id"]:
        return False, "OBLIGATION_MISMATCH"
    report_digest = _canonical_sha256({
        "task_id": report.get("task_id"),
        "submitted_amount_cents": report.get("submitted_amount_cents"),
    })
    if report_digest != expected["expected_report_digest"]:
        return False, "REPORT_DIGEST_MISMATCH"
    if body.get("report_digest") != report_digest:
        return False, "BODY_DIGEST_MISMATCH"
    binding_digest = _canonical_sha256({
        "task_id": expected["task_id"],
        "obligation_id": expected["obligation_id"],
        "report_digest": expected["expected_report_digest"],
    })
    if binding.get("binding_sha256") != binding_digest:
        return False, "BINDING_DIGEST_MISMATCH"
    return True, "EXACT_BINDING_MATCH"


def _permissive_positive_control(body: Mapping[str, Any]) -> bool:
    report = body.get("report")
    return (isinstance(report, Mapping) and "task_id" in report
            and "submitted_amount_cents" in report)


def _require(condition: object, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def _loopback_http(url: object) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    return parsed.scheme == "http" and parsed.hostname == "127.0.0.1"


def _private_oracle_inputs(binding: Mapping[str, Any]) -> tuple[Fixture, Artifact]:
    fixture_value = binding.get("oracle_fixture")
    artifact_value = binding.get("oracle_artifact")
    if not isinstance(fixture_value, Mapping) or not isinstance(artifact_value, Mapping):
        raise EvidenceError("private controller binding lacks frozen oracle inputs")
    try:
        fixture = Fixture(**fixture_value)
        artifact = Artifact(**artifact_value)
    except (TypeError, ValueError) as exc:
        raise EvidenceError(f"invalid frozen oracle inputs: {exc}") from exc
    if fixture.task_id != artifact.task_id:
        raise EvidenceError("frozen fixture and artifact task IDs differ")
    return fixture, artifact


def verify_purchase(
    directory: Path,
    *,
    frozen_fixture: Fixture | None = None,
    frozen_artifact: Artifact | None = None,
) -> IndependentPurchaseVerification:
    directory = Path(directory)
    intent = _load_object(directory / "purchase-intent.json")
    served = _load_object(directory / "resource-body.json")
    raw_path = directory / "raw-native-x402.json"
    raw = _load_object(raw_path)
    quote = intent.get("quote")
    selected = intent.get("selected")
    controller_binding = intent.get("controller_binding")
    _require(isinstance(quote, Mapping) and isinstance(selected, Mapping)
             and isinstance(controller_binding, Mapping),
             "intent lacks quote, selected terms, or private controller binding")
    _require(not ({"task_id", "obligation_id", "expected_report_digest"} & set(quote)),
             "model-facing quote leaked private fixture binding")
    _require(intent.get("actor") == "auditor" and intent.get("intent") == "BUY_REPORT",
             "stored action is not explicit auditor purchase intent")
    for field in ("quote_id", "assignment_nonce", "service_id", "amount_minor_units"):
        _require(selected.get(field) == quote.get(field), f"selected {field} differs from quote")
    _require(str(selected.get("recipient", "")).lower() == str(quote.get("recipient", "")).lower(),
             "selected recipient differs from quote")
    _require(quote.get("amount_minor_units") == NATIVE_AMOUNT_MINOR,
             "quote amount differs from pinned runner amount")
    _require(str(quote.get("recipient", "")).lower() == NATIVE_SELLER,
             "quote recipient differs from pinned local seller")
    _require(quote.get("public_task_id") == PUBLIC_TASK_ID,
             "quote uses a non-public or treatment-specific task ID")
    quote_base = {key: value for key, value in quote.items()
                  if key not in ("quote_id", "assignment_nonce", "transaction_tier")}
    _require(quote.get("quote_id") == _canonical_sha256(quote_base),
             "quote ID does not bind the frozen public terms")
    _require(sha256(X402_RUNNER.read_bytes()).hexdigest() == X402_RUNNER_SHA256,
             "pinned x402 runner source changed")

    _require(raw.get("upstream", {}).get("commit") == X402_COMMIT,
             "x402 upstream source pin changed")
    _require(raw.get("upstream", {}).get("protocol") == "x402 v2"
             and raw.get("upstream", {}).get("scheme") == "exact"
             and raw.get("upstream", {}).get("assetTransferMethod") == "eip3009",
             "native protocol mechanism differs from x402 v2 exact/EIP-3009")
    _require(raw.get("transactionExecutionTier") == "NATIVE_LOCAL_PROTOCOL",
             "transaction tier is not native local protocol")
    chain = raw.get("chain", {})
    http = raw.get("http", {})
    _require(chain.get("chainId") == 31337 and chain.get("network") == "eip155:31337",
             "unexpected local chain")
    _require(_loopback_http(chain.get("rpcUrl")) and _loopback_http(http.get("resourceUrl"))
             and _loopback_http(http.get("facilitatorUrl")), "non-loopback x402 endpoint")

    challenge = http.get("challenge")
    _require(isinstance(challenge, Mapping) and challenge.get("x402Version") == 2,
             "missing x402 v2 HTTP challenge")
    accepts = challenge.get("accepts")
    _require(isinstance(accepts, list) and len(accepts) == 1, "challenge is not exact single-option")
    requirement = accepts[0]
    _require(requirement.get("scheme") == "exact"
             and requirement.get("network") == "eip155:31337", "challenge scheme/network mismatch")
    _require(int(requirement.get("amount", -1)) == NATIVE_AMOUNT_MINOR,
             "challenge amount differs from selected amount")
    _require(str(requirement.get("payTo", "")).lower() == NATIVE_SELLER,
             "challenge recipient differs from selected recipient")
    _require(str(requirement.get("asset", "")).lower() == str(chain.get("tokenAddress", "")).lower(),
             "challenge asset differs from deployed token")

    verify = raw.get("verify")
    settle = raw.get("settle")
    _require(isinstance(verify, Mapping) and verify.get("result", {}).get("isValid") is True,
             "facilitator verify did not accept authorization")
    _require(verify.get("before") == verify.get("after")
             and verify.get("after", {}).get("nonceUsed") is False,
             "verify mutated token state")
    _require(isinstance(settle, Mapping) and settle.get("result", {}).get("success") is True,
             "facilitator settle did not succeed")
    _require(settle.get("before", {}).get("nonceUsed") is False
             and settle.get("after", {}).get("nonceUsed") is True,
             "settlement did not consume authorization nonce")

    tx = raw.get("transaction")
    auth = raw.get("authorization")
    actors = raw.get("actors")
    _require(isinstance(tx, Mapping) and isinstance(auth, Mapping) and isinstance(actors, Mapping),
             "raw authorization/transaction/actor evidence missing")
    _require(tx.get("status") == "success"
             and tx.get("hash") == settle.get("result", {}).get("transaction")
             and http.get("paymentResponse", {}).get("transaction") == tx.get("hash"),
             "settlement responses disagree with successful transaction")
    _require(str(tx.get("to", "")).lower() == str(chain.get("tokenAddress", "")).lower(),
             "settlement transaction did not call token")
    _require(str(tx.get("from", "")).lower() == str(actors.get("facilitator", "")).lower(),
             "settlement transaction sender is not facilitator")
    _require(str(auth.get("from", "")).lower() == str(actors.get("buyer", "")).lower()
             and str(auth.get("to", "")).lower() == NATIVE_SELLER
             and int(auth.get("value", -1)) == NATIVE_AMOUNT_MINOR,
             "EIP-3009 authorization payer/payee/amount mismatch")

    logs = [log for log in tx.get("logs", [])
            if str(log.get("address", "")).lower() == str(chain.get("tokenAddress", "")).lower()
            and log.get("topics") and str(log["topics"][0]).lower() == TRANSFER_TOPIC]
    _require(len(logs) == 1, "expected exactly one token Transfer log")
    transfer = logs[0]
    _require(int(transfer.get("data", "0x0"), 16) == NATIVE_AMOUNT_MINOR,
             "Transfer amount differs from quote")
    topics = transfer["topics"]
    payer = "0x" + str(topics[1])[-40:]
    recipient = "0x" + str(topics[2])[-40:]
    _require(payer.lower() == str(actors.get("buyer", "")).lower(), "Transfer payer mismatch")
    _require(recipient.lower() == NATIVE_SELLER, "Transfer recipient mismatch")
    balances = raw.get("balances", {})
    buyer_delta = int(balances.get("finalBuyer", 0)) - int(balances.get("initialBuyer", 0))
    seller_delta = int(balances.get("finalSeller", 0)) - int(balances.get("initialSeller", 0))
    _require(buyer_delta == -NATIVE_AMOUNT_MINOR and seller_delta == NATIVE_AMOUNT_MINOR,
             "balance changes do not equal the exact charge")
    _require(balances.get("nonceUsedAfterSettle") is True, "final nonce is not consumed")
    _require([event.get("phase") for event in raw.get("trace", [])] == [
        "CHALLENGE", "SIGNED_AUTHORIZATION", "VERIFY", "RESOURCE_EXECUTE", "SETTLE", "RESPONSE"
    ], "native event chronology changed")

    negatives = raw.get("negatives", {})
    expected_reasons = {
        "wrongAmount": "invalid_exact_evm_payload_authorization_value_mismatch",
        "wrongPayee": "invalid_exact_evm_recipient_mismatch",
        "expired": "invalid_exact_evm_payload_authorization_valid_before",
    }
    for name, reason in expected_reasons.items():
        control = negatives.get(name, {})
        _require(control.get("result", {}).get("isValid") is False
                 and control.get("result", {}).get("invalidReason") == reason,
                 f"{name} native negative did not fail for the expected reason")
        _require(control.get("before") == control.get("after"),
                 f"{name} native negative changed token state")
    _require(negatives.get("replayVerify", {}).get("isValid") is False
             and negatives.get("replayHttpStatus") == 402
             and negatives.get("replayContractRejected") is True,
             "replay negative control was not rejected at all three boundaries")
    _require(negatives.get("invalidContractSignatureRejected") is True,
             "tampered-payee signature negative was not rejected")
    handler_failure = raw.get("handlerFailure", {})
    _require(handler_failure.get("status") == 503
             and handler_failure.get("settleCallsBefore") == handler_failure.get("settleCallsAfter")
             and handler_failure.get("before") == handler_failure.get("after"),
             "failed-resource negative charged or changed token state")

    body = http.get("resourceBody")
    _require(isinstance(body, Mapping) and body == served, "stored response body differs from served body")
    _require(http.get("paidStatus") == 200, "paid HTTP response was not successful")
    fixture, expected_artifact = _private_oracle_inputs(controller_binding)
    if frozen_fixture is not None or frozen_artifact is not None:
        _require(frozen_fixture == fixture and frozen_artifact == expected_artifact,
                 "caller-frozen oracle inputs differ from stored controller binding")
    _require(isinstance(controller_binding.get("obligation_id"), str)
             and bool(controller_binding.get("obligation_id")),
             "private obligation binding is missing")
    expected_public_report = {
        "task_id": PUBLIC_TASK_ID,
        "submitted_amount_cents": expected_artifact.submitted_amount_cents,
    }
    _require(controller_binding.get("task_id") == PUBLIC_TASK_ID,
             "private binding uses a non-public resource task ID")
    _require(controller_binding.get("expected_report_digest")
             == _canonical_sha256(expected_public_report),
             "private expected report digest differs from frozen artifact")
    expected = {
        "task_id": PUBLIC_TASK_ID,
        "obligation_id": controller_binding.get("obligation_id"),
        "expected_report_digest": controller_binding.get("expected_report_digest"),
    }
    strict_accepted, _ = _assess_application_binding(body, expected)
    permissive_accepted = _permissive_positive_control(body)
    report = body.get("report")
    _require(isinstance(report, Mapping), "response lacks report")
    observed = Artifact(
        task_id=fixture.task_id,
        submitted_amount_cents=report.get("submitted_amount_cents"),
    )
    # Correctness uses the protected frozen fixture.  The paid body carries only
    # the shared public task alias and never chooses the oracle fixture.
    oracle = oracle_score(fixture, observed)
    protocol_charge_valid = True
    paid_defective = protocol_charge_valid and oracle.status.value == "FAIL"
    wrongful_protocol_charge = not protocol_charge_valid and seller_delta > 0
    return IndependentPurchaseVerification(
        status="PASS",
        task_id=PUBLIC_TASK_ID,
        obligation_id=str(controller_binding.get("obligation_id")),
        report_digest=_canonical_sha256(report),
        oracle_status=oracle.status.value,
        oracle_reason_code=oracle.reason_code,
        protocol_charge_valid=protocol_charge_valid,
        application_binding_valid=strict_accepted,
        permissive_adapter_accepted=permissive_accepted,
        paid_defective_report=paid_defective,
        wrongful_protocol_charge=wrongful_protocol_charge,
        transaction_hash=str(tx["hash"]),
        transfer_log_index=int(transfer["logIndex"]),
        amount_minor_units=NATIVE_AMOUNT_MINOR,
        payer=payer.lower(),
        recipient=recipient.lower(),
        raw_evidence_sha256=sha256(raw_path.read_bytes()).hexdigest(),
        resource_body_sha256=_canonical_sha256(body),
        payment_semantics=(
            "x402 settled one-time HTTP access; report correctness and downstream "
            "invoice approval are application-layer outcomes"
        ),
    )
