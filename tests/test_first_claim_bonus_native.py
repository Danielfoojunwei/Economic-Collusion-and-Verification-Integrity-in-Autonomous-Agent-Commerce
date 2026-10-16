"""Negative replay cases for archived same-job first-claim bonus receipts."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.verify_first_claim_bonus_control import _compile_artifact, verify


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = (ROOT / "artifacts/prospective/ERC8183_BILATERAL030_FIRST_CLAIM_NATIVE001"
            / "evidence.json")


class FirstClaimBonusNativeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact, cls.artifact_sha = _compile_artifact()
        cls.original = json.loads(EVIDENCE.read_text())

    def _reject(self, evidence: dict, message: str) -> None:
        with TemporaryDirectory() as temp:
            path = Path(temp) / "tampered-evidence.json"
            path.write_text(json.dumps(evidence))
            with self.assertRaisesRegex(ValueError, message):
                verify(path, artifact=self.artifact, artifact_sha256=self.artifact_sha)

    def test_scripted_same_job_receipts_replay(self) -> None:
        result = verify(EVIDENCE, artifact=self.artifact, artifact_sha256=self.artifact_sha)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["native_transactions_replayed"], 57)
        self.assertEqual(result["cases"]["bad_eval_approve"]["evaluator_bonus_minor"], 5_000_000)
        self.assertEqual(result["cases"]["bad_eval_reject"]["provider_bonus_refund_minor"],
                         5_000_000)
        self.assertEqual(result["cases"]["bad_client_settle"]["evaluator_bonus_minor"], 0)

    def test_private_buyer_description_or_wrong_creation_calldata_rejected(self) -> None:
        evidence = copy.deepcopy(self.original)
        create = next(tx for tx in evidence["transactions"] if tx["step"] ==
                      "bad_eval_approve.create_job")
        create["raw_transaction"]["input"] = "0xdeadbeef"
        self._reject(evidence, "public-only job description")

    def test_wrong_first_decision_calldata_rejected(self) -> None:
        evidence = copy.deepcopy(self.original)
        first = next(tx for tx in evidence["transactions"] if tx["step"] ==
                     "bad_eval_approve.first_decision")
        first["raw_transaction"]["input"] = "0xdeadbeef"
        self._reject(evidence, "first native decision calldata")

    def test_wrong_bonus_beneficiary_rejected_even_if_log_summary_matches(self) -> None:
        evidence = copy.deepcopy(self.original)
        first = next(tx for tx in evidence["transactions"] if tx["step"] ==
                     "bad_eval_approve.first_decision")
        raw = first["raw_receipt"]["logs"]
        log = next(log for log in raw if log["address"].lower() ==
                   evidence["scenarios"]["bad_eval_approve"]["hook"].lower()
                   and len(log["topics"]) == 3)
        log["topics"][2] = "0x" + "0" * 24 + evidence["actors"]["provider"][2:].lower()
        index = raw.index(log)
        first["logs"][index]["topics"] = log["topics"][:]
        self._reject(evidence, "bonus payout event")

    def test_wrong_protected_oracle_rejected(self) -> None:
        evidence = copy.deepcopy(self.original)
        evidence["scenarios"]["bad_eval_approve"]["oracle"]["buyer_po_cents"] = 400
        self._reject(evidence, "independent BAD invoice oracle")


if __name__ == "__main__":
    unittest.main()
