"""Issue and independently recheck valueless AP2 audit-purchase mandates.

Run with the pinned AP2 v0.2 SDK environment. No checkout or PSP is executed.
The invoice obligation is bound by this caller's synthetic checkout reference;
AP2 itself authorizes only the purchase described by that reference.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path
import time

from jwcrypto.jwk import JWK

from scripts.run_ap2_local import (
    AUDIENCE, BASE, NONCE, UPSTREAM_COMMIT, PaymentAuthorization,
    create_presentation, new_test_key,
)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def purchase_intent(obligation_id: str, artifact_digest: str) -> dict:
    return {
        "sku": "independent-invoice-audit/v1",
        "invoice_obligation_id": obligation_id,
        "invoice_artifact_digest": artifact_digest,
        "payee_id": BASE.payee_id,
        "amount_minor": BASE.amount_minor,
        "currency": BASE.currency,
        "instrument_id": BASE.instrument_id,
        "purpose": "purchase independent audit service only",
        "invoice_quality_authority": "NONE",
    }


def proposed_for(intent: dict):
    # Caller-defined synthetic checkout bytes, not a verified checkout JWT.
    checkout_reference = b"ap2-local-audit-checkout-v1:" + canonical(intent)
    import base64
    transaction_id = base64.urlsafe_b64encode(sha256(checkout_reference).digest()).rstrip(b"=").decode()
    return replace(BASE, transaction_id=transaction_id)


def verify_saved(record: dict) -> dict:
    public = JWK.from_json(json.dumps(record["trusted_issuer_public_jwk"]))
    intent = record["purchase_intent"]
    expected = proposed_for(intent)
    if asdict(expected) != record["proposed_payment"]:
        raise ValueError("saved proposed payment differs from bound purchase intent")
    at = int(record["issued_at"]) + 300
    reference = PaymentAuthorization(public).authorize(
        record["signed_presentation"], expected,
        audience=record["audience"], nonce=record["nonce"], current_time=at,
    )
    if reference != record["authorization_reference"]:
        raise ValueError("saved authorization reference differs")
    alternate = dict(intent, invoice_obligation_id=record["cross_obligation_id"])
    try:
        PaymentAuthorization(public).authorize(
            record["signed_presentation"], proposed_for(alternate),
            audience=record["audience"], nonce=record["nonce"], current_time=at,
        )
    except ValueError as exc:
        if "transaction_id mismatch" not in str(exc):
            raise
        cross_detail = f"{type(exc).__name__}: {exc}"
    else:
        raise ValueError("cross-obligation authorization unexpectedly passed")
    return {"valid_in_scope": True, "cross_obligation_rejected": True,
            "cross_obligation_detail": cross_detail,
            "authorization_reference": reference}


def issue(obligation_id: str, artifact_digest: str, cross_obligation_id: str) -> dict:
    issuer, agent = new_test_key(), new_test_key()
    intent = purchase_intent(obligation_id, artifact_digest)
    proposed = proposed_for(intent)
    now = int(time.time())
    signed = create_presentation(issuer, agent, proposed, now=now)
    record = {
        "schema": "ap2-invoice-audit-authorization-v1",
        "execution_tier": "NATIVE_LOCAL_PROTOCOL",
        "protocol": "AP2 v0.2.0 signed delegated payment authorization",
        "upstream_commit": UPSTREAM_COMMIT,
        "payment_execution": "NONE",
        "checkout_execution": "NONE; caller-defined synthetic reference only",
        "private_keys_written": False,
        "issued_at": now,
        "audience": AUDIENCE,
        "nonce": NONCE,
        "purchase_intent": intent,
        "proposed_payment": asdict(proposed),
        "cross_obligation_id": cross_obligation_id,
        "trusted_issuer_public_jwk": json.loads(issuer.export_public()),
        "signed_presentation": signed,
        "authorization_reference": PaymentAuthorization(
            JWK.from_json(issuer.export_public())).authorize(
                signed, proposed, current_time=now + 300),
    }
    record["verification"] = verify_saved(record)
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    issue_args = sub.add_parser("issue")
    issue_args.add_argument("--obligation", required=True)
    issue_args.add_argument("--artifact-digest", required=True)
    issue_args.add_argument("--cross-obligation", required=True)
    issue_args.add_argument("--output", type=Path, required=True)
    verify_args = sub.add_parser("verify")
    verify_args.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.action == "issue":
        data = issue(args.obligation, args.artifact_digest, args.cross_obligation)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(data, handle, sort_keys=True, indent=2)
            handle.write("\n")
    else:
        data = json.loads(args.path.read_text(encoding="utf-8"))
        result = verify_saved(data)
        if result != data["verification"]:
            raise ValueError("saved AP2 verification result differs")
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
