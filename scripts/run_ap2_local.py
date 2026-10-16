"""W15 AP2 v0.2.0 local signed mandate conformance, with valueless fixtures.

The official AP2 SDK verifies delegation signatures and open-mandate constraints.
This caller also binds the closed mandate to a proposed transaction and keeps a
one-use receipt ledger. Those caller checks are not native AP2 guarantees.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from ap2.sdk.generated.open_payment_mandate import (
    AllowedPayees,
    AllowedPaymentInstruments,
    AmountRange,
    OpenPaymentMandate,
)
from ap2.sdk.generated.payment_mandate import PaymentMandate
from ap2.sdk.generated.types.amount import Amount
from ap2.sdk.generated.types.merchant import Merchant
from ap2.sdk.generated.types.payment_instrument import PaymentInstrument
from ap2.sdk.mandate import MandateClient
from ap2.sdk.payment_mandate_chain import PaymentMandateChain
from ap2.sdk.utils import compute_sha256_b64url
from jwcrypto.jwk import JWK


UPSTREAM_COMMIT = "b4587ac1d055888a73b4b21750973cffba961793"
AUDIENCE = "https://example.invalid/ap2/merchant-test"
NONCE = "w15-local-challenge-1"


@dataclass(frozen=True)
class ProposedPayment:
    transaction_id: str
    payee_id: str
    amount_minor: int
    currency: str
    instrument_id: str


BASE = ProposedPayment(
    # AP2's transaction_id is a base64url digest of checkout_jwt. This is a
    # synthetic checkout reference, not an independently verified checkout.
    transaction_id=base64.urlsafe_b64encode(
        hashlib.sha256(b"W15 synthetic checkout JWT").digest()
    ).rstrip(b"=").decode(),
    payee_id="demo-merchant-1",
    amount_minor=2500,
    currency="USD",
    instrument_id="demo-instrument-1",
)


def new_test_key() -> JWK:
    """Create a fresh P-256 key in memory; never write private key material."""
    return JWK.generate(kty="EC", crv="P-256")


def create_presentation(
    issuer: JWK,
    agent: JWK,
    proposed: ProposedPayment = BASE,
    *,
    now: int | None = None,
    root_exp: int | None = None,
    leaf_exp: int | None = None,
    audience: str = AUDIENCE,
    nonce: str = NONCE,
    signer: JWK | None = None,
) -> str:
    """Use the official SDK to issue an open mandate and delegated closed one."""
    issued_at = now if now is not None else int(time.time())
    allowed_payee = Merchant(id=BASE.payee_id, name="Demo Merchant")
    allowed_instrument = PaymentInstrument(id=BASE.instrument_id, type="demo")
    root = OpenPaymentMandate(
        constraints=[
            AmountRange(currency="USD", min=1, max=5000),
            AllowedPayees(allowed=[allowed_payee]),
            AllowedPaymentInstruments(allowed=[allowed_instrument]),
        ],
        cnf={"jwk": json.loads(agent.export_public())},
        iat=issued_at,
        exp=root_exp if root_exp is not None else issued_at + 3600,
    )
    closed = PaymentMandate(
        transaction_id=proposed.transaction_id,
        payee=Merchant(id=proposed.payee_id, name="Demo Merchant"),
        payment_amount=Amount(amount=proposed.amount_minor, currency=proposed.currency),
        payment_instrument=PaymentInstrument(id=proposed.instrument_id, type="demo"),
        iat=issued_at,
        exp=leaf_exp if leaf_exp is not None else issued_at + 3600,
    )
    client = MandateClient()
    root_token = client.create(payloads=[root], issuer_key=issuer)
    return client.present(
        holder_key=signer or agent,
        mandate_token=root_token,
        payloads=[closed],
        nonce=nonce,
        aud=audience,
    )


class PaymentAuthorization:
    """Verifier with trusted root key and a local one-use ledger."""

    def __init__(self, trusted_issuer_public: JWK):
        self.trusted_issuer_public = trusted_issuer_public
        self._used_references: set[str] = set()

    def authorize(
        self,
        presentation: str,
        proposed: ProposedPayment,
        *,
        audience: str = AUDIENCE,
        nonce: str = NONCE,
        current_time: int | None = None,
    ) -> str:
        client = MandateClient()
        verified_payloads = client.verify(
            token=presentation,
            key_or_provider=lambda _token: self.trusted_issuer_public,
            expected_aud=audience,
            expected_nonce=nonce,
            clock_skew_seconds=0,
            current_time=current_time,
        )
        chain = PaymentMandateChain.parse(verified_payloads)
        violations = chain.verify(expected_transaction_id=proposed.transaction_id)
        if violations:
            raise ValueError("scope: " + "; ".join(violations))

        closed = chain.closed_mandate
        if closed.payee.id != proposed.payee_id:
            raise ValueError("transaction payee mismatch")
        if (closed.payment_amount.amount, closed.payment_amount.currency) != (
            proposed.amount_minor,
            proposed.currency,
        ):
            raise ValueError("transaction amount or currency mismatch")
        if closed.payment_instrument.id != proposed.instrument_id:
            raise ValueError("transaction instrument mismatch")

        reference = compute_sha256_b64url(client.get_closed_mandate_jwt(presentation))
        if reference in self._used_references:
            raise ValueError("replay: mandate reference already used")
        self._used_references.add(reference)
        return reference


def tamper_root_signature(presentation: str) -> str:
    """Corrupt one signed byte of the root JWT without changing its payload."""
    root, rest = presentation.split("~~", 1)
    compact, disclosures = root.split("~", 1)
    header, payload, signature = compact.split(".")
    alternate = "A" if signature[0] != "A" else "B"
    return f"{header}.{payload}.{alternate}{signature[1:]}~{disclosures}~~{rest}"


def run_cases() -> dict:
    issuer = new_test_key()
    agent = new_test_key()
    trusted_public = JWK.from_json(issuer.export_public())
    now = int(time.time())
    valid = create_presentation(issuer, agent, now=now)
    scenarios: list[dict] = []

    def check(name: str, presentation: str, proposed: ProposedPayment = BASE,
              *, expect: str = "PASS", reason: str = "authorized",
              verifier: PaymentAuthorization | None = None,
              audience: str = AUDIENCE, nonce: str = NONCE) -> None:
        actual = "PASS"
        detail = "authorized"
        try:
            (verifier or PaymentAuthorization(trusted_public)).authorize(
                presentation, proposed, audience=audience, nonce=nonce,
                current_time=now + 300,
            )
        except Exception as exc:
            actual = "REJECT"
            detail = f"{type(exc).__name__}: {exc}"
        scenarios.append({
            "name": name, "expected": expect, "actual": actual,
            "test_passed": actual == expect and reason in detail, "detail": detail,
            "presentation_sha256": hashlib.sha256(presentation.encode()).hexdigest(),
        })

    verifier = PaymentAuthorization(trusted_public)
    check("valid_signed_delegation", valid, verifier=verifier)
    check("replay_guard", valid, verifier=verifier, expect="REJECT", reason="replay:")
    check("bad_signature", tamper_root_signature(valid), expect="REJECT", reason="InvalidJWSSignature")
    check("wrong_trusted_issuer", valid, verifier=PaymentAuthorization(
        JWK.from_json(new_test_key().export_public())), expect="REJECT", reason="InvalidJWSSignature")
    check("wrong_holder_key", create_presentation(issuer, agent, now=now,
                                                 signer=new_test_key()),
          expect="REJECT", reason="InvalidJWSSignature")
    check("wrong_audience", valid, audience="https://wrong.invalid", expect="REJECT", reason="aud mismatch")
    check("wrong_nonce", valid, nonce="different-challenge", expect="REJECT", reason="nonce mismatch")
    check("expired_root", create_presentation(
        issuer, agent, now=now - 1000, root_exp=now - 500,
        leaf_exp=now + 500), expect="REJECT", reason="Token 0 expired")
    check("expired_leaf", create_presentation(
        issuer, agent, now=now - 1000, root_exp=now + 500,
        leaf_exp=now - 500), expect="REJECT", reason="Token 1 expired")
    for name, changed, reason in (
        ("out_of_scope_payee", replace(BASE, payee_id="other-merchant"), "not in allowed list"),
        ("out_of_scope_amount", replace(BASE, amount_minor=7000), "exceeds maximum"),
        ("out_of_scope_currency", replace(BASE, currency="EUR"), "Currency mismatch"),
        ("out_of_scope_instrument", replace(BASE, instrument_id="other-instrument"), "not in allowed list"),
    ):
        check(name, create_presentation(issuer, agent, changed, now=now),
              expect="REJECT", reason=reason)
    check("proposed_payee_mismatch", valid, replace(BASE, payee_id="other-merchant"),
          expect="REJECT", reason="transaction payee mismatch")
    check("proposed_amount_mismatch", valid, replace(BASE, amount_minor=2501),
          expect="REJECT", reason="transaction amount or currency mismatch")
    check("proposed_instrument_mismatch", valid, replace(BASE, instrument_id="other-instrument"),
          expect="REJECT", reason="transaction instrument mismatch")
    check("transaction_reference_mismatch", valid,
          replace(BASE, transaction_id="different-checkout-hash"),
          expect="REJECT", reason="transaction_id mismatch")

    return {
        "work_order": "W15", "protocol": "AP2", "upstream_tag": "v0.2.0",
        "upstream_commit": UPSTREAM_COMMIT,
        "sdk_package_version": version("ap2"),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "execution_tier": "NATIVE_LOCAL_PROTOCOL",
        "payment_execution": "NONE: signed authorization only; no PSP or funds",
        "private_keys_written": False,
        "sdk_checks": ["ES256 root/holder signatures", "audience", "challenge nonce",
                       "exp", "open-to-closed constraints"],
        "caller_checks": ["proposed transaction equality", "one-use replay ledger"],
        "cases": scenarios,
        "pass_count": sum(case["test_passed"] for case in scenarios),
        "fail_count": sum(not case["test_passed"] for case in scenarios),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
                        default=Path("artifacts/gates/G6/W15/conformance.json"))
    args = parser.parse_args()
    result = run_cases()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"W15 AP2 conformance: {result['pass_count']}/{len(result['cases'])} cases passed")
    return 0 if result["fail_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
