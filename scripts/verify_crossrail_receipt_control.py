#!/usr/bin/env python3
"""Independently recompute the frozen report score and native receipt invariants."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path


ERC_PIN = "142e669c1fd318486a4628395b629f033654dd06"
X402_PIN = "e95b06661e1a2a8a9a21fce34cc28b9934834650"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ROOT = Path(__file__).resolve().parents[1]


def canonical_hash(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode()).hexdigest()


def read(path: Path):
    return json.loads(path.read_text())


def verify(root: Path) -> dict:
    report, refs = read(root / "receipt-report.json"), read(root / "private-warehouse-reference.json")
    erc, summary = read(root / "erc8183/evidence.json"), read(root / "summary.json")
    report_hash = canonical_hash(report)
    assert report_hash == summary["report_sha256"] == erc["report_sha256"]
    assert summary["frozen_reference_source_file_sha256"] == sha256(
        (ROOT / "tests/test_protected_receipts.py").read_bytes()).hexdigest()
    assert summary["frozen_task_source_file_sha256"] == sha256(
        (ROOT / "src/agent_economic_trust/protected_receipts.py").read_bytes()).hexdigest()
    assert report["auditor_decision"] == {
        "verdict": "ACCEPT", "check_completed": False, "check_spent_units": 0,
        "origin": "SCRIPTED_UNCHECKED_WRONG_ACCEPT_POSITIVE_CONTROL"}
    assert "warehouse" not in report and "unit-c" not in str(report)
    assert erc["source"]["commit"] == ERC_PIN and erc["payment_tier"] == "NATIVE_LOCAL_PROTOCOL"
    assert summary["transaction_execution_tier"] == "NATIVE_LOCAL_PROTOCOL"
    assert set(refs) == set(erc["pairs"]) == set(summary["cases"]) == {"good", "bad"}
    checked = {}
    for case in ("good", "bad"):
        ref = refs[case]
        assert ref["task_id"] == report["submitted_claim"]["task_id"]
        statuses = [line["status"] for line in ref["warehouse"]]
        assert len(statuses) == len({line["line_id"] for line in ref["warehouse"]}) == 4
        assert set(statuses) <= {"ACCEPTED", "REJECTED"}
        expected_count = sum(status == "ACCEPTED" for status in statuses)
        claim = report["submitted_claim"]
        truth = ("PASS" if claim["accepted_count"] == expected_count and
                 claim["claimed_amount_minor"] == expected_count * ref["unit_price_minor"] else "FAIL")
        assert truth == summary["cases"][case]["independent_oracle_status"] == erc["pairs"][case]["oracle_status"]
        pair = erc["pairs"][case]
        assert pair["report_sha256"] == report_hash
        assert pair["submitted_event"]["data"].lower() == "0x" + report_hash
        assert pair["prestate"] == pair["restored_prestate"]
        assert pair["prestate"]["job"]["status"] == "Submitted"
        before = pair["prestate"]["token_state"]["balances_minor_units"]
        default = pair["default"]
        assert default["final_state"]["job"]["status"] == "Completed"
        paid = default["final_state"]["token_state"]["balances_minor_units"]
        assert paid["provider"] - before["provider"] == 17_000_000
        assert paid["escrow"] - before["escrow"] == -20_000_000
        default_tx = default["transactions"][0]
        assert default_tx["status"] == 1 and default_tx["raw_receipt"]["status"] == "0x1"
        assert {"JobCompleted", "PaymentReleased"} <= {log["name"] for log in default_tx["logs"]}
        guard = pair["application_guard"]
        assert guard["oracle_origin"] == "PRIVATE_WAREHOUSE_IDEAL_UPPER_BOUND"
        guarded = guard["final_state"]
        assert guarded["job"]["status"] == ("Completed" if truth == "PASS" else "Rejected")
        assert guard["allow_complete"] == (truth == "PASS")
        guard_bal = guarded["token_state"]["balances_minor_units"]
        assert guard_bal["provider"] - before["provider"] == (17_000_000 if truth == "PASS" else 0)
        assert guard["transactions"][0]["raw_receipt"]["status"] == "0x1"
        assert ("PaymentReleased" if truth == "PASS" else "Refunded") in {
            log["name"] for log in guard["transactions"][0]["logs"]}

        native = read(root / case / "x402-native.json")
        assert native["upstream"]["commit"] == X402_PIN
        assert native["http"]["resourceBody"] == report
        assert native["http"]["paidStatus"] == 200
        assert native["http"]["challenge"]["x402Version"] == 2
        assert native["verify"]["result"]["isValid"] is True
        assert native["settle"]["result"]["success"] is True
        assert native["verify"]["before"] == native["verify"]["after"]
        assert native["transaction"]["status"] == "success"
        assert native["transaction"]["hash"] == native["settle"]["result"]["transaction"]
        amount = int(native["http"]["challenge"]["accepts"][0]["amount"])
        balance = native["balances"]
        assert int(balance["finalBuyer"]) - int(balance["initialBuyer"]) == -amount
        assert int(balance["finalSeller"]) - int(balance["initialSeller"]) == amount
        assert balance["nonceUsedAfterSettle"] is True
        logs = [log for log in native["transaction"]["logs"] if
                log["address"].lower() == native["chain"]["tokenAddress"].lower() and
                log["topics"][0].lower() == TRANSFER_TOPIC]
        assert len(logs) == 1 and int(logs[0]["data"], 16) == amount
        assert "0x" + logs[0]["topics"][1][-40:].lower() == native["actors"]["buyer"].lower()
        assert "0x" + logs[0]["topics"][2][-40:].lower() == native["actors"]["seller"].lower()
        assert [step["phase"] for step in native["trace"]] == [
            "CHALLENGE", "SIGNED_AUTHORIZATION", "VERIFY", "RESOURCE_EXECUTE", "SETTLE", "RESPONSE"]
        checked[case] = {"oracle_status": truth, "accepted_warehouse_units": expected_count,
                         "erc_default_provider_delta": paid["provider"] - before["provider"],
                         "erc_guard_provider_delta": guard_bal["provider"] - before["provider"],
                         "x402_seller_delta": amount}
    assert checked["good"]["oracle_status"] == "PASS"
    assert checked["bad"]["oracle_status"] == "FAIL"
    result = {"status": "PASS", "report_sha256": report_hash, "cases": checked,
              "scope": "independent warehouse score and raw local ERC8183/x402 receipt checks"}
    mpp_path = root / "mpp-run-002/evidence.json"
    if mpp_path.exists():
        mpp = read(mpp_path)
        assert mpp["report"] == report
        assert mpp["reportSha256"] == "sha256:" + sha256(json.dumps(report, separators=(",", ":")).encode()).hexdigest()
        assert mpp["execution_tier"] == "NATIVE_LOCAL_PROTOCOL"
        assert mpp["sdk"] == "mppx@0.13.4"
        assert mpp["imageDigest"] == "sha256:86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b"
        served = [event for event in mpp["events"] if event["type"] == "HTTP" and event["status"] == 200]
        assert len(served) >= 3
        assert all(event["responseBodySha256"] == mpp["reportSha256"] for event in served)
        charge = mpp["charge"]
        assert charge["receipt"]["status"] == "success"
        assert charge["receipt"]["reference"] == charge["transfer"]["hash"]
        assert charge["transfer"]["status"] == "success"
        transfer = charge["transferEvent"]
        assert transfer["name"] == "Transfer" and transfer["args"]["amount"] == "10000"
        assert transfer["args"]["from"].lower() == mpp["payer"].lower()
        assert transfer["args"]["to"].lower() == mpp["payee"].lower()
        assert int(charge["payeeAfter"]) - int(charge["payeeBefore"]) == 10000
        assert charge["replay"]["status"] == 402
        session = mpp["session"]
        assert session["closeReceipt"]["status"] == "success"
        assert session["closeReceipt"]["txHash"] == session["settlementTx"]["hash"]
        assert session["openState"]["deposit"] == "50000"
        assert session["closeReceipt"]["acceptedCumulative"] == "20000"
        assert session["replay"]["status"] == session["invalidSignature"]["status"] == 402
        closed = [event for event in session["closeEvents"] if event["name"] == "ChannelClosed"]
        assert len(closed) == 1 and closed[0]["args"]["channelId"] == session["channelId"]
        assert closed[0]["args"]["settledToPayee"] == "20000"
        assert closed[0]["args"]["refundedToPayer"] == "30000"
        result["mpp"] = {"status": "PASS", "charge_transfer_minor": 10000,
                         "session_settled_minor": 20000, "session_refunded_minor": 30000,
                         "served_report_sha256": mpp["reportSha256"],
                         "evidence": str(mpp_path.relative_to(root))}
        result["scope"] += " and native MPP charge/session receipts"
    else:
        result["mpp"] = {"status": "SKIP", "reason": "no MPP overlay evidence at mpp-run-002/evidence.json"}
    diversion_path = root / "x402-diversion-run-002/native.json"
    if diversion_path.exists():
        diversion = read(diversion_path)
        http = diversion["http"]
        assert diversion["workOrder"] == "CROSSRAIL_RECEIPT_RESOURCE_DIVERSION"
        assert diversion["upstream"]["commit"] == X402_PIN
        assert http["paidStatus"] == 200
        assert http["challengedResourceUrl"] == http["paymentPayloadResourceUrl"] == http["resourceUrl"]
        assert http["actualPaidResourceUrl"] == http["challengedResourceUrl"] + "-alt"
        assert http["originalReportSha256"] == sha256(json.dumps(report, separators=(",", ":")).encode()).hexdigest()
        assert http["deliveredBodySha256"] != http["originalReportSha256"]
        assert http["resourceBody"]["submitted_claim"]["claimed_amount_minor"] == 200
        assert diversion["verify"]["result"]["isValid"] is True
        assert diversion["settle"]["result"]["success"] is True
        assert diversion["transaction"]["status"] == "success"
        assert int(diversion["balances"]["finalSeller"]) - int(diversion["balances"]["initialSeller"]) == 1000
        diversion_logs = [log for log in diversion["transaction"]["logs"] if
                          log["address"].lower() == diversion["chain"]["tokenAddress"].lower() and
                          log["topics"][0].lower() == TRANSFER_TOPIC]
        assert len(diversion_logs) == 1 and int(diversion_logs[0]["data"], 16) == 1000
        result["x402_resource_diversion"] = {
            "status": "PASS", "challenged_url": http["challengedResourceUrl"],
            "paid_url": http["actualPaidResourceUrl"],
            "original_report_sha256": http["originalReportSha256"],
            "delivered_body_sha256": http["deliveredBodySha256"],
            "seller_delta_minor": 1000}
    else:
        result["x402_resource_diversion"] = {"status": "SKIP", "reason": "no diversion overlay evidence"}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    result = verify(args.root)
    path = args.root / "independent-verification.json"
    path.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    final_summary = read(args.root / "summary.json")
    final_summary["mpp"] = result["mpp"]
    final_summary["x402_resource_diversion"] = result["x402_resource_diversion"]
    final_summary["independent_verification"] = path.name
    (args.root / "final-summary.json").write_text(
        json.dumps(final_summary, sort_keys=True, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
