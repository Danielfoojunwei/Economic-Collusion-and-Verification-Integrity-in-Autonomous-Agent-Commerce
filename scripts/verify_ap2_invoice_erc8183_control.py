"""Read-only verification of saved AP2 authorization and native invoice evidence."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from agent_economic_trust.core import oracle_score
from agent_economic_trust.open004_task import invoice_case
from agent_economic_trust.open005_native import verify_open005_native_evidence
from scripts.run_ap2_invoice_erc8183_control import ap2_command, economic_prestate


def verify(directory: Path) -> dict:
    directory = directory.resolve()
    report = json.loads((directory / "report.json").read_text())
    if report["schema"] != "ap2-invoice-erc8183-local-control-v1":
        raise ValueError("saved report schema differs")
    if len(report["rows"]) != 4:
        raise ValueError("local control requires four rows")
    checked = []
    for row in report["rows"]:
        fixture, artifact = invoice_case(row["truth"])
        oracle_status = oracle_score(fixture, artifact).status.value
        expected_verdict = ("REJECT" if row["adapter"] == "strict" and oracle_status == "FAIL"
                            else "ACCEPT")
        if (row["scripted_requested_verdict"] != "ACCEPT"
                or row["application_dispatched_verdict"] != expected_verdict
                or row["application_oracle_status"] != (
                    oracle_status if row["adapter"] == "strict" else "NOT_CONSULTED")):
            raise ValueError("saved adapter decision differs from independent invoice oracle")
        ap2_path = directory / row["ap2_evidence"]
        native_path = directory / row["native_evidence"]
        for path, key in ((ap2_path, "ap2_evidence_sha256"),
                          (native_path, "native_evidence_sha256")):
            if sha256(path.read_bytes()).hexdigest() != row[key]:
                raise ValueError(f"saved artifact SHA differs: {path}")
        ap2_command("verify", str(ap2_path))
        ap2 = json.loads(ap2_path.read_text())
        if (ap2["payment_execution"] != "NONE"
                or ap2["purchase_intent"]["invoice_quality_authority"] != "NONE"
                or ap2["purchase_intent"]["invoice_obligation_id"] != row["obligation_id"]
                or ap2["purchase_intent"]["invoice_artifact_digest"] != row["artifact_digest"]):
            raise ValueError("AP2 purchase scope differs from invoice row")
        native = verify_open005_native_evidence(native_path.parent)
        evidence = json.loads(native_path.read_text())
        if (not native["ok"] or native["status"] != "PASS"
                or native["verdict"] != row["application_dispatched_verdict"]
                or native["provider_paid"] != row["native_provider_paid"]
                or native["client_refunded"] != row["native_client_refunded"]
                or evidence["settlement"]["transaction_hash"] != row["native_terminal_transaction_hash"]
                or evidence["side_funding"] is not None
                or evidence["settlement"]["side_term"] is not None):
            raise ValueError("raw native settlement or report row differs")
        prestate = sha256(json.dumps(economic_prestate(evidence), sort_keys=True,
                                   separators=(",", ":")).encode()).hexdigest()
        if prestate != row["economic_preterminal_state_sha256"]:
            raise ValueError("saved economic preterminal state differs")
        checked.append((row["truth"], row["adapter"], native["status"]))
    if sorted(checked) != [("bad", "permissive", "PASS"),
                           ("bad", "strict", "PASS"),
                           ("good", "permissive", "PASS"),
                           ("good", "strict", "PASS")]:
        raise ValueError("local control grid differs")
    return {"status": "PASS", "rows": len(checked),
            "ap2_signed_authorizations": 2, "ap2_cross_obligation_negatives": 2,
            "native_terminal_receipts": 4}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.directory), sort_keys=True))


if __name__ == "__main__":
    main()
