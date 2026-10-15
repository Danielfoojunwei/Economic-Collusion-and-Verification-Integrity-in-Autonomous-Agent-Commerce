"""Offline unit and negative tests for the heterogeneous service-term collector."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from agent_economic_trust.service_terms_suite import (
    EvidenceError,
    build_service_record,
    validate_ap2,
    validate_erc8183,
    validate_mpp,
    validate_x402,
    warehouse_oracle,
    warehouse_reports,
)


ROOT = Path(__file__).resolve().parents[1]


class ServiceTermSuiteTests(unittest.TestCase):
    def test_diverse_service_oracles_and_pressure_isolation(self):
        record = build_service_record()
        self.assertEqual(len(record["cases"]), 6)
        statuses = {case["case_id"]: case["oracle"]["status"] for case in record["cases"]}
        self.assertEqual(statuses, record["oracle_control_expectations"])
        self.assertEqual(set(statuses.values()), {"PASS", "FAIL"})
        self.assertTrue(all(case["untrusted_provider_message"] for case in record["cases"]))
        self.assertTrue(all(case["provider_message_is_oracle_input"] is False
                            for case in record["cases"]))
        self.assertIn("positive control", record["pressure_track"]["scripted_wrong_accept_interpretation"].lower())

    def test_warehouse_oracle_rejects_overstated_and_malformed_receipts(self):
        good, bad = warehouse_reports()
        self.assertEqual(warehouse_oracle(good)["status"], "PASS")
        self.assertEqual(warehouse_oracle(bad), {
            "status": "FAIL", "reason_code": "ACCEPTED_QUANTITY_MISMATCH"})
        duplicate = deepcopy(good)
        duplicate["lines"][1]["receipt_id"] = duplicate["lines"][0]["receipt_id"]
        self.assertEqual(warehouse_oracle(duplicate)["reason_code"], "DUPLICATE_OR_INVALID_RECEIPT")

    def test_existing_native_evidence_and_tamper_negatives(self):
        erc = json.loads((ROOT / "artifacts/gates/G2/local-run-004/evidence.json").read_text())
        self.assertEqual(validate_erc8183(erc)["settlement"],
                         "native local ERC-20 escrow release/refund receipts")
        altered = deepcopy(erc)
        altered["scenarios"]["bad_completed_without_app_guard"]["oracle_status"] = "PASS"
        with self.assertRaises(EvidenceError):
            validate_erc8183(altered)

        x402 = json.loads((ROOT / "artifacts/gates/G3/native-run.json").read_text())
        self.assertEqual(validate_x402(x402, x402["http"]["resourceBody"])["execution_tier"],
                         "NATIVE_LOCAL_PROTOCOL")
        altered = deepcopy(x402)
        altered["settle"]["result"]["success"] = False
        with self.assertRaises(EvidenceError):
            validate_x402(altered, x402["http"]["resourceBody"])

        mpp = json.loads((ROOT / "artifacts/gates/G6/W14/evidence.json").read_text())
        self.assertEqual(validate_mpp(mpp)["native_policy"],
                         "metered charge and cumulative session")
        altered = deepcopy(mpp)
        altered["boundedSession"]["blockedError"] = None
        with self.assertRaises(EvidenceError):
            validate_mpp(altered)

        ap2 = json.loads((ROOT / "artifacts/gates/G6/W15/conformance.json").read_text())
        self.assertEqual(validate_ap2(ap2)["settlement"], "NONE")
        altered = deepcopy(ap2)
        altered["payment_execution"] = "SETTLED"
        with self.assertRaises(EvidenceError):
            validate_ap2(altered)


if __name__ == "__main__":
    unittest.main()

