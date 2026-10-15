"""Issue and verify time-valid AP2 v0.2 audit purchase authorizations locally."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import time

from jwcrypto.jwk import JWK

from scripts.ap2_invoice_authorization import (canonical, proposed_for,
                                                purchase_intent)
from scripts.run_ap2_local import (AUDIENCE, UPSTREAM_COMMIT, PaymentAuthorization,
                                   create_presentation, new_test_key)


VALIDITY_SECONDS = 24 * 60 * 60


def verify_live(record: dict, *, now: int | None = None) -> dict:
    if record.get("schema") != "ap2-live-audit-authorization-v1":
        raise ValueError("AP2 live authorization schema differs")
    at = int(time.time()) if now is None else now
    issued, expires = record["issued_at"], record["expires_at"]
    if (type(issued) is not int or type(expires) is not int
            or expires - issued != VALIDITY_SECONDS
            or not issued <= at < expires):
        raise ValueError("AP2 live authorization is not currently valid")
    intent = record["purchase_intent"]
    proposed = proposed_for(intent)
    if asdict(proposed) != record["proposed_payment"]:
        raise ValueError("AP2 proposed payment differs from scoped checkout reference")
    public = JWK.from_json(json.dumps(record["trusted_issuer_public_jwk"]))
    reference = PaymentAuthorization(public).authorize(
        record["signed_presentation"], proposed,
        audience=record["audience"], nonce=record["nonce"], current_time=at)
    if reference != record["authorization_reference"]:
        raise ValueError("AP2 signed mandate reference differs")
    alternate = dict(intent, invoice_obligation_id=record["cross_obligation_id"])
    try:
        PaymentAuthorization(public).authorize(
            record["signed_presentation"], proposed_for(alternate),
            audience=record["audience"], nonce=record["nonce"], current_time=at)
    except ValueError as exc:
        if "transaction_id mismatch" not in str(exc):
            raise
    else:
        raise ValueError("AP2 cross-obligation reference unexpectedly passed")
    return {"status": "PASS", "authorization_reference": reference,
            "valid_at_unix": at, "expires_at_unix": expires,
            "cross_obligation_rejected": True}


def issue_live(obligation_id: str, artifact_digest: str,
               cross_obligation_id: str) -> dict:
    if obligation_id == cross_obligation_id:
        raise ValueError("cross-obligation negative requires a distinct obligation")
    issuer, agent = new_test_key(), new_test_key()
    issued = int(time.time())
    intent = purchase_intent(obligation_id, artifact_digest)
    proposed = proposed_for(intent)
    nonce = f"ap2-live-{obligation_id}"
    signed = create_presentation(
        issuer, agent, proposed, now=issued,
        root_exp=issued + VALIDITY_SECONDS,
        leaf_exp=issued + VALIDITY_SECONDS, nonce=nonce)
    record = {
        "schema": "ap2-live-audit-authorization-v1",
        "upstream_commit": UPSTREAM_COMMIT,
        "payment_execution": "NONE",
        "private_keys_written": False,
        "issued_at": issued, "expires_at": issued + VALIDITY_SECONDS,
        "audience": AUDIENCE, "nonce": nonce,
        "purchase_intent": intent, "proposed_payment": asdict(proposed),
        "cross_obligation_id": cross_obligation_id,
        "trusted_issuer_public_jwk": json.loads(issuer.export_public()),
        "signed_presentation": signed,
        "authorization_reference": PaymentAuthorization(
            JWK.from_json(issuer.export_public())).authorize(
                signed, proposed, audience=AUDIENCE, nonce=nonce,
                current_time=issued),
    }
    record["trusted_issuer_public_sha256"] = sha256(
        canonical(record["trusted_issuer_public_jwk"])).hexdigest()
    record["issue_time_verification"] = verify_live(record, now=issued)
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    issue = sub.add_parser("issue")
    issue.add_argument("--obligation", required=True)
    issue.add_argument("--artifact-digest", required=True)
    issue.add_argument("--cross-obligation", required=True)
    issue.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify-live")
    verify.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.action == "issue":
        record = issue_live(args.obligation, args.artifact_digest,
                            args.cross_obligation)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(record, handle, sort_keys=True, indent=2)
            handle.write("\n")
    else:
        record = json.loads(args.path.read_text())
        print(json.dumps(verify_live(record), sort_keys=True))


if __name__ == "__main__":
    main()
