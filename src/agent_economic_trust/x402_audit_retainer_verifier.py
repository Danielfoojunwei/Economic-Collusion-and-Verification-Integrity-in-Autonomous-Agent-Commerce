"""Recheck saved x402 audit-intake receipts against an external assignment.

This reads raw HTTP/transaction evidence rather than the runner's PASS field.
The local test chain is disposable; archived JSON is evidence, not a live chain
attestation after Anvil exits.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit

from .ap2_live_fixture import invoice_case
from .core import oracle_score
from .x402_audit_retainer import (
    ASSET, AUDITOR_WALLET, FEE_MINOR, ROOT, RUNNER, SERVICE_ID,
    RetainerAssignment, canonical_bytes, intake_body,
)


X402_COMMIT = "e95b06661e1a2a8a9a21fce34cc28b9934834650"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
PAYER_WALLETS = {
    "provider": "0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc",
    "buyer": "0x70997970c51812dc3a010c7d01b50e0d17dc79c8",
}
TRANSFER_WITH_AUTHORIZATION_SELECTOR = "e3ee160e"


class ReceiptError(AssertionError):
    """The receipt cannot be bound to this assigned intake service."""


def require(ok: object, reason: str) -> None:
    if not ok:
        raise ReceiptError(reason)


def read_json(path: Path) -> dict:
    try:
        result = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ReceiptError(f"unreadable {path.name}") from exc
    require(isinstance(result, dict), f"{path.name} must be a JSON object")
    return result


def local_url(url: object, path: str | None = None) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    return parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and (
        path is None or parsed.path == path) and not parsed.query and not parsed.fragment


def _word(input_hex: str, index: int) -> str:
    start = 8 + index * 64
    return input_hex[start:start + 64]


def verify_intake(directory: Path, assignment: RetainerAssignment) -> dict:
    """Fail closed on a paid receipt for another payer, report or obligation."""
    assignment.validate()
    directory = Path(directory)
    recorded_assignment = read_json(directory / "assignment.json")
    require(recorded_assignment == vars(assignment), "saved assignment differs")
    served = read_json(directory / "intake-body.json")
    require(served == intake_body(assignment), "paid body is stale, substituted or unbound")
    raw_path = directory / "raw-native-x402.json"
    raw = read_json(raw_path)
    require(raw.get("workOrder") == "X402_AUDIT_RETAINER_010"
            and raw.get("transactionExecutionTier") == "NATIVE_LOCAL_PROTOCOL",
            "native execution tier differs")
    upstream = raw.get("upstream", {})
    require(upstream.get("commit") == X402_COMMIT
            and upstream.get("protocol") == "x402 v2"
            and upstream.get("scheme") == "exact"
            and upstream.get("assetTransferMethod") == "eip3009",
            "official x402 mechanism/source pin differs")
    upstream_dir = Path("/workspace/upstreams/x402")
    require((upstream_dir / ".git").exists(), "pinned x402 checkout is unavailable")
    upstream_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=upstream_dir,
                                   capture_output=True, text=True, check=True).stdout.strip()
    require(upstream_head == X402_COMMIT, "installed official x402 checkout changed")
    assigned = raw.get("assignment", {})
    require(assigned.get("payerRole") == assignment.payer_role
            and assigned.get("obligationId") == assignment.obligation_id
            and assigned.get("serviceId") == SERVICE_ID
            and assigned.get("reportDigest") == served["report_digest"]
            and assigned.get("expectedBodySha256") == sha256(canonical_bytes(served)).hexdigest()
            and assigned.get("runnerSourceSha256") == sha256(RUNNER.read_bytes()).hexdigest()
            and assigned.get("tokenSourceSha256") == sha256(
                (ROOT / "contracts/x402/TestEIP3009Token.sol").read_bytes()).hexdigest(),
            "native invocation differs from assigned intake")
    chain = raw.get("chain", {})
    http = raw.get("http", {})
    actors = raw.get("actors", {})
    expected_path = f"/audit-intake/{assignment.obligation_id}"
    require(chain.get("chainId") == 31337 and chain.get("network") == "eip155:31337"
            and local_url(chain.get("rpcUrl"))
            and local_url(http.get("facilitatorUrl"))
            and local_url(http.get("resourceUrl"), expected_path),
            "local chain or paid resource URL differs")
    expected_payer = PAYER_WALLETS[assignment.payer_role]
    require(str(actors.get("payer", "")).lower() == expected_payer
            and actors.get("payerRole") == assignment.payer_role
            and str(actors.get("buyer", "")).lower() == expected_payer
            and str(actors.get("seller", "")).lower() == AUDITOR_WALLET
            and str(actors.get("auditor", "")).lower() == AUDITOR_WALLET
            and str(actors.get("provider", "")).lower() == PAYER_WALLETS["provider"]
            and str(actors.get("independentBuyer", "")).lower() == PAYER_WALLETS["buyer"],
            "payer/payee role mapping differs")

    challenge = http.get("challenge", {})
    accepts = challenge.get("accepts", [])
    require(challenge.get("x402Version") == 2 and len(accepts) == 1,
            "missing single-option x402 v2 challenge")
    option = accepts[0]
    require(option.get("scheme") == "exact"
            and option.get("network") == "eip155:31337"
            and option.get("asset", "").lower() == str(chain.get("tokenAddress", "")).lower()
            and option.get("amount") == str(FEE_MINOR)
            and option.get("payTo", "").lower() == AUDITOR_WALLET
            and option.get("extra", {}).get("assetTransferMethod") == "eip3009",
            "x402 challenge does not price the assigned auditor retainer")
    verify, settle = raw.get("verify", {}), raw.get("settle", {})
    require(verify.get("result", {}).get("isValid") is True
            and verify.get("before") == verify.get("after")
            and verify.get("after", {}).get("nonceUsed") is False,
            "facilitator verify failed or changed token state")
    require(settle.get("result", {}).get("success") is True
            and settle.get("before", {}).get("nonceUsed") is False
            and settle.get("after", {}).get("nonceUsed") is True,
            "facilitator settle did not consume nonce")
    auth, tx = raw.get("authorization", {}), raw.get("transaction", {})
    nonce = auth.get("nonce", "")
    require(auth.get("from", "").lower() == expected_payer
            and auth.get("to", "").lower() == AUDITOR_WALLET
            and auth.get("value") == str(FEE_MINOR)
            and isinstance(nonce, str) and len(nonce) == 66
            and auth.get("domain", {}).get("chainId") == 31337
            and auth.get("domain", {}).get("verifyingContract", "").lower()
                == str(chain.get("tokenAddress", "")).lower(),
            "signed EIP-3009 authorization role/amount/domain differs")
    require(tx.get("status") == "success"
            and tx.get("hash") == settle.get("result", {}).get("transaction")
            and tx.get("hash") == http.get("paymentResponse", {}).get("transaction")
            and tx.get("to", "").lower() == str(chain.get("tokenAddress", "")).lower()
            and tx.get("from", "").lower() == str(actors.get("facilitator", "")).lower()
            and int(tx.get("blockNumber", "0")) <= int(tx.get("observedHead", "-1")),
            "successful onchain settlement/HTTP receipt disagree")
    input_hex = str(tx.get("input", "")).removeprefix("0x").lower()
    require(len(input_hex) == 8 + 9 * 64
            and input_hex[:8] == TRANSFER_WITH_AUTHORIZATION_SELECTOR
            and "0x" + _word(input_hex, 0)[-40:] == expected_payer
            and "0x" + _word(input_hex, 1)[-40:] == AUDITOR_WALLET
            and int(_word(input_hex, 2), 16) == FEE_MINOR
            and int(_word(input_hex, 3), 16) == int(auth["validAfter"])
            and int(_word(input_hex, 4), 16) == int(auth["validBefore"])
            and "0x" + _word(input_hex, 5) == nonce.lower(),
            "settlement calldata differs from signed EIP-3009 terms")
    timestamp = int(tx.get("blockTimestampSeconds", "-1"))
    require(int(auth["validAfter"]) <= timestamp <= int(auth["validBefore"]),
            "settlement occurred outside authorization validity")
    transfers = [entry for entry in tx.get("logs", []) if
                 entry.get("address", "").lower() == str(chain.get("tokenAddress", "")).lower()
                 and entry.get("topics", [None])[0].lower() == TRANSFER_TOPIC]
    require(len(transfers) == 1, "expected one native token transfer")
    transfer = transfers[0]
    require("0x" + transfer["topics"][1][-40:].lower() == expected_payer
            and "0x" + transfer["topics"][2][-40:].lower() == AUDITOR_WALLET
            and int(transfer["data"], 16) == FEE_MINOR,
            "native transfer log differs from assigned retainer")
    balances = raw.get("balances", {})
    require(int(balances.get("initialBuyer", "-1")) == 2 * FEE_MINOR
            and int(balances.get("initialSeller", "-1")) == 0
            and int(balances.get("finalBuyer", "-1")) == FEE_MINOR
            and int(balances.get("finalSeller", "-1")) == FEE_MINOR
            and balances.get("nonceUsedAfterSettle") is True,
            "native balance deltas do not equal retainer")
    require(http.get("paidStatus") == 200 and http.get("resourceBody") == served
            and http.get("paymentResponse", {}).get("success") is True,
            "paid intake HTTP body or response differs")
    require([event.get("phase") for event in raw.get("trace", [])] == [
        "CHALLENGE", "SIGNED_AUTHORIZATION", "VERIFY", "RESOURCE_EXECUTE",
        "SETTLE", "RESPONSE"], "native payment event chronology differs")

    negatives = raw.get("negatives", {})
    for key, reason in {
        "wrongAmount": "invalid_exact_evm_payload_authorization_value_mismatch",
        "wrongPayee": "invalid_exact_evm_recipient_mismatch",
        "expired": "invalid_exact_evm_payload_authorization_valid_before",
    }.items():
        item = negatives.get(key, {})
        require(item.get("result", {}).get("isValid") is False
                and item.get("result", {}).get("invalidReason") == reason
                and item.get("before") == item.get("after"),
                f"{key} native negative did not fail without state change")
    require(negatives.get("replayVerify", {}).get("isValid") is False
            and negatives.get("replayHttpStatus") == 402
            and negatives.get("replayContractRejected") is True
            and negatives.get("invalidContractSignatureRejected") is True,
            "replay or tampered contract signature negative failed")
    failed = raw.get("handlerFailure", {})
    require(failed.get("status") == 503
            and failed.get("before") == failed.get("after")
            and failed.get("settleCallsBefore") == failed.get("settleCallsAfter")
            and failed.get("paymentResponseHeader") is None,
            "failed service handler nevertheless settled")
    require(raw.get("schemeLimit", {}).get("alteredResourceUrlVerified") is True,
            "EIP-3009 resource URL scope control changed")
    fixture, artifact = invoice_case(assignment.truth)
    oracle = oracle_score(fixture, artifact)
    return {"status": "PASS", "model_tier": "SCRIPTED_SIMULATION",
            "transaction_tier": "NATIVE_LOCAL_PROTOCOL",
            "protocol_settled": True, "application_binding_valid": True,
            "quality_attested_by_payment": False,
            "oracle_status": oracle.status.value, "oracle_reason_code": oracle.reason_code,
            "payer_role": assignment.payer_role, "payer": expected_payer,
            "payee": AUDITOR_WALLET, "amount_minor_units": FEE_MINOR,
            "asset": ASSET, "transaction_hash": tx["hash"],
            "transfer_log_index": transfer["logIndex"],
            "body_sha256": sha256(canonical_bytes(served)).hexdigest(),
            "raw_sha256": sha256(raw_path.read_bytes()).hexdigest()}
