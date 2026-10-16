"""Read-only regression checks for 012 valueless native payment evidence."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from agent_economic_trust.x402_audit_retainer import RetainerAssignment
from agent_economic_trust.x402_live012_native_verifier import (
    verify_incomplete_native, verify_live_native,
)
from agent_economic_trust.x402_live012_plan import make_schedule
from agent_economic_trust.x402_retainer_job import RetainerJob
from agent_economic_trust.x402_retainer_job_verifier import JobEvidenceError, verify_job
from scripts.verify_x402_live012_offline import verify, verify_incomplete


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "artifacts/prospective/X402_LIVE012/offline-native-001"
INCOMPLETE_ARCHIVE = ROOT / "artifacts/prospective/X402_LIVE012/offline-incomplete-001"


class X402Live012NativeTests(unittest.TestCase):
    def test_native_study_id_is_012_and_other_study_binding_fails(self):
        row = next(r for r in make_schedule("00" * 32)
                   if r.truth == "bad" and r.payer_role == "provider")
        assignment = RetainerAssignment(row.episode_id, row.obligation_id,
                                        row.truth, row.payer_role)
        obj = RetainerJob(assignment, Path("/tmp/unused-native-012"), port=19802,
                          study_id="X402_AUDIT_RETAINER_012")
        self.assertEqual(obj.study_id, "X402_AUDIT_RETAINER_012")
        with self.assertRaises(ValueError):
            RetainerJob(assignment, Path("/tmp/unused-native-013"), port=19803,
                        study_id="X402_AUDIT_RETAINER_013")
        path = ARCHIVE / "bad-provider-checked-reject/erc8183-job/native-job.json"
        self.assertTrue(path.is_file(), "generate and verify offline-native-001 first")
        self.assertEqual(verify_job(path, assignment, model_tier="SCRIPTED_SIMULATION",
                                    study_id="X402_AUDIT_RETAINER_012")["status"], "PASS")
        with self.assertRaises(JobEvidenceError):
            verify_job(path, assignment, model_tier="SCRIPTED_SIMULATION",
                       study_id="X402_AUDIT_RETAINER_011")

    def test_six_scripted_native_cases_replay_without_live_claim(self):
        result = verify(ARCHIVE)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["scripted_cases_reverified"], 6)
        self.assertEqual(result["matched_assignment_cells_reverified"], 4)
        self.assertTrue(result["bad_unchecked_wrongful_payout_control"])
        self.assertEqual(result["live_collusion_observations"], 0)
        report = json.loads((ARCHIVE / "report.json").read_bytes())
        self.assertFalse(report["payer_effect_inferred_from_scripted_cases"])

    def test_scripted_receipt_cannot_be_relabelled_as_live_model_evidence(self):
        row = next(r for r in make_schedule("00" * 32)
                   if r.truth == "bad" and r.payer_role == "provider")
        directory = ARCHIVE / "bad-provider-checked-reject"
        verified = verify_live_native(directory, row, model_tier="SCRIPTED_SIMULATION")
        self.assertEqual(verified["oracle_status"], "FAIL")
        self.assertTrue(verified["x402_replay_rejected_verified"])
        self.assertEqual(verified["x402_intake_component_model_tier"],
                         "SCRIPTED_SIMULATION")
        with self.assertRaisesRegex(ValueError, "evidence tier differs"):
            verify_live_native(directory, row,
                               model_tier="REAL_LLM_REMOTE_APPROVED")

    def test_no_verdict_native_effects_replay_and_terminal_is_rejected(self):
        control = verify_incomplete(INCOMPLETE_ARCHIVE)
        self.assertEqual(control["status"], "PASS")
        self.assertEqual(control["scripted_no_verdict_cases_reverified"], 2)
        self.assertEqual(control["tamper_negatives_reverified"], 11)
        rows = {(row.truth, row.payer_role): row
                for row in make_schedule("00" * 32)}
        for payer, checked in (("provider", False), ("buyer", True)):
            row = rows["bad", payer]
            case = ("bad-provider-unchecked" if not checked
                    else "bad-buyer-checked")
            result = verify_incomplete_native(INCOMPLETE_ARCHIVE / case, row,
                                              model_tier="SCRIPTED_SIMULATION")
            self.assertEqual(result["status"], "OBSERVED_INCOMPLETE")
            self.assertIs(result["check_paid"], checked)
            self.assertEqual(result["provider_paid_minor"], 0)
            self.assertEqual(result["client_refunded_minor"], 0)
            self.assertFalse(result["terminal_transaction_observed"])
            self.assertEqual(result["native_state_scope"],
                             "SAVED_LOCAL_CHAIN_HEAD_ONLY")
        with self.assertRaisesRegex(ValueError, "terminal or ambiguous"):
            verify_incomplete_native(
                ARCHIVE / "bad-provider-checked-reject",
                rows["bad", "provider"], model_tier="SCRIPTED_SIMULATION")


if __name__ == "__main__":
    unittest.main()
