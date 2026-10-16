"""Independent linkage checks for the W09 frozen-decision native payment pilot."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from agent_economic_trust.core import FIXTURES, oracle_score
from run_w09_cross_flow import _record, canonical_sha256


class CrossFlowTests(unittest.TestCase):
    def test_native_paid_report_matches_frozen_erc_decision(self) -> None:
        with tempfile.TemporaryDirectory(prefix="w09-native-") as directory:
            output = Path(directory) / "run"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "run_w09_cross_flow.py"),
                 "--output", str(output), "--port-base", "18720"],
                cwd=ROOT, check=True, capture_output=True, text=True, timeout=90,
            )
            evidence = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
            w07_path = ROOT / "artifacts" / "gates" / "W07" / "native-run-001" / "evidence.json"
            w07 = json.loads(w07_path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["source"]["w07_evidence_file_sha256"],
                             sha256(w07_path.read_bytes()).hexdigest())
            self.assertEqual(evidence["work_order"], "W09")
            self.assertEqual(evidence["model_behavior_tier"], "SCRIPTED_SIMULATION")
            self.assertEqual(evidence["payment_tier"], "NATIVE_LOCAL_PROTOCOL")
            self.assertEqual(set(evidence["cases"]), {"good", "bad"})
            self.assertFalse(evidence["flow_semantics"]["amounts_comparable_across_flows"])
            self.assertFalse(evidence["flow_semantics"]["security_ranking_supported"])
            self.assertFalse(evidence["flow_semantics"]["x402_has_native_evaluator_or_semantic_oracle"])

            for case, summary in evidence["cases"].items():
                pair = w07["pairs"][case]
                fixture, artifact = FIXTURES[case]
                record_path = output / summary["resource_record_path"]
                native_path = output / summary["x402_evidence_path"]
                record = json.loads(record_path.read_text(encoding="utf-8"))
                native = json.loads(native_path.read_text(encoding="utf-8"))

                self.assertEqual(record["public_task"], fixture.public_task())
                self.assertEqual(record["submitted_artifact"], {
                    "task_id": artifact.task_id,
                    "submitted_amount_cents": artifact.submitted_amount_cents,
                })
                self.assertEqual(record["artifact_sha256"], artifact.digest())
                self.assertEqual(record["auditor_decision"], pair["frozen_auditor_decision"])
                self.assertEqual(record["auditor_decision_sha256"],
                                 canonical_sha256(pair["frozen_auditor_decision"]))
                self.assertEqual(record["decision_origin"], "SCRIPTED_UNCHECKED_CONTROL")
                self.assertEqual(record, native["http"]["resourceBody"])
                self.assertNotIn("oracle_status", json.dumps(record))
                self.assertNotIn("expected_amount_cents", json.dumps(record))
                self.assertEqual(summary["oracle_status"], oracle_score(fixture, artifact).status.value)
                self.assertEqual(summary["resource_record_file_sha256"],
                                 sha256(record_path.read_bytes()).hexdigest())
                self.assertEqual(summary["x402_evidence_file_sha256"],
                                 sha256(native_path.read_bytes()).hexdigest())
                self.assertEqual(summary["x402"]["resource_record_sha256"], canonical_sha256(record))
                self.assertEqual(summary["x402"]["settlement_transaction"],
                                 native["transaction"]["hash"])
                self.assertEqual(summary["x402"]["buyer_delta_minor_units"], -1000)
                self.assertEqual(summary["x402"]["seller_delta_minor_units"], 1000)
                self.assertFalse(summary["x402"]["native_evaluator_role"])
                self.assertFalse(summary["x402"]["resource_body_signed_by_eip3009"])
                self.assertTrue(summary["erc8183"]["native_evaluator_role"])
                self.assertEqual(summary["erc8183"]["unguarded_completion_transaction"],
                                 pair["arms"]["unguarded"]["transactions"][0]["transaction_hash"])
                self.assertEqual(summary["erc8183"]["unguarded_provider_delta_minor_units"], 17_000_000)
                self.assertEqual(summary["application_outcomes"]["erc_unguarded_bad_work_paid"],
                                 case == "bad")
                self.assertEqual(summary["application_outcomes"]["x402_incorrect_record_delivered_and_paid"],
                                 case == "bad")
                self.assertTrue(summary["application_outcomes"]["x402_native_payment_rule_satisfied"])

    def test_wrong_frozen_decision_hash_is_rejected_before_payment(self) -> None:
        path = ROOT / "artifacts" / "gates" / "W07" / "native-run-001" / "evidence.json"
        pair = deepcopy(json.loads(path.read_text(encoding="utf-8"))["pairs"]["good"])
        pair["frozen_decision_sha256"] = "0" * 64
        with self.assertRaisesRegex(AssertionError, "frozen decision hash"):
            _record("good", pair)

    def test_existing_output_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory(prefix="w09-existing-") as directory:
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "run_w09_cross_flow.py"),
                 "--output", directory],
                cwd=ROOT, capture_output=True, text=True, timeout=10,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing to overwrite W09 evidence", result.stderr)


if __name__ == "__main__":
    unittest.main()
