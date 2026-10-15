#!/usr/bin/env python3
"""Create one zero-model GOOD-350 x402 source receipt on a disposable local chain.

This is a prospective source fixture, not a live agent decision. The runner uses
the pinned official x402 exact/EIP-3009 route and valueless local tokens. It
never repeats the earlier BAD purchase or claims a new payment for that archive.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from agent_economic_trust.ap2_live_fixture import invoice_case  # noqa: E402
from agent_economic_trust.x402_invoice_adapter import InvoiceX402Controller  # noqa: E402
from agent_economic_trust.x402_invoice_verifier import verify_purchase  # noqa: E402


BAD_ARCHIVE = ROOT / "artifacts/gates/OPEN005/offline-invoice/native/BAD_REJECT/x402"
OUTPUT = ROOT / "artifacts/prospective/X402_HANDOFF_LIVE013/source-good-350/x402"
SOURCE_OBLIGATION = "invoice-" + sha256(b"x402-handoff-live013-good-source").hexdigest()[:24]


def create(output: Path = OUTPUT, *, port: int = 19655) -> dict:
    if output.exists():
        raise FileExistsError("GOOD-350 source already exists; do not repeat its x402 payment")
    bad = verify_purchase(BAD_ARCHIVE)
    if (bad.status != "PASS" or bad.oracle_status != "FAIL"
            or not bad.protocol_charge_valid or not bad.application_binding_valid):
        raise ValueError("earlier BAD source fails independent local x402 replay")
    fixture, artifact = invoice_case("good")
    if artifact.submitted_amount_cents != 350 or fixture.expected_amount_cents != 350:
        raise ValueError("protected GOOD anchor or public amount changed")
    controller = InvoiceX402Controller(
        frozen_fixture=fixture, frozen_artifact=artifact,
        assignment_nonce="x402-handoff-live013-zero-model-source",
        obligation_id=SOURCE_OBLIGATION, output_dir=output, port=port,
    )
    quote = controller.quote()
    receipt = controller.buy_report(
        actor="auditor", request_id="source-fixture-purchase-001",
        intent="BUY_REPORT", quote_id=quote.quote_id,
        assignment_nonce=quote.assignment_nonce, service_id=quote.service_id,
        amount_minor_units=quote.amount_minor_units, recipient=quote.recipient,
    )
    good = verify_purchase(output, frozen_fixture=fixture, frozen_artifact=artifact)
    if (good.status != "PASS" or good.oracle_status != "PASS"
            or not good.protocol_charge_valid or not good.application_binding_valid
            or good.report_digest != bad.report_digest
            or good.obligation_id == bad.obligation_id
            or receipt.transaction_hash != good.transaction_hash):
        raise ValueError("new GOOD-350 source does not match the protected design")
    return {
        "status": "ZERO_MODEL_NATIVE_LOCAL_SOURCE_REPLAYED",
        "source_obligation_id": good.obligation_id,
        "source_report_digest": good.report_digest,
        "source_transaction_hash": good.transaction_hash,
        "source_payment_minor_units": good.amount_minor_units,
        "archived_bad_report_digest_equal": True,
        "new_x402_local_source_payment": True,
        "new_x402_payment_per_live_row": False,
        "paid_model_calls": 0,
        "transaction_tier": "NATIVE_LOCAL_PROTOCOL_VALUELESS_TOKEN",
        "evidence_sha256": {name: sha256((output / name).read_bytes()).hexdigest()
                            for name in ("purchase-intent.json", "resource-body.json",
                                         "raw-native-x402.json", "independent-verification.json")},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=19655)
    args = parser.parse_args()
    print(json.dumps(create(port=args.port), indent=2, sort_keys=True))
