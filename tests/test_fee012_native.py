"""Read-only FEE012 native control replay and scripted-tier identity checks."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent_economic_trust.fee012_offline import (ARCHIVE, cases,
    replay_scripted_receipt, verify)


class Fee012NativeControls(unittest.TestCase):
    def test_eight_scripted_native_cases_and_seven_tamper_negatives(self):
        result = verify(ARCHIVE)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["scripted_native_cases_reverified"], 8)
        self.assertEqual(result["scripted_bad_accept_positive_controls"], 1)
        self.assertEqual(result["no_verdict_prefix_controls"], 1)
        self.assertEqual(result["tamper_negatives_reverified"], 7)
        self.assertEqual(result["paid_model_calls"], 0)

    def test_raw_receipts_cannot_claim_remote_model_behavior(self):
        for name, row, verdict in cases():
            path = ARCHIVE / name / (
                "native-evidence.json" if verdict else "native-partial.json")
            evidence = json.loads(path.read_text())
            self.assertEqual(evidence["model_behavior_tier"], "SCRIPTED_SIMULATION")
            self.assertEqual(replay_scripted_receipt(path, row)[
                "model_behavior_tier"], "SCRIPTED_SIMULATION")
        name, row, verdict = cases()[0]
        original = ARCHIVE / name / "native-evidence.json"
        evidence = json.loads(original.read_text())
        evidence["model_behavior_tier"] = "REAL_LLM_REMOTE_APPROVED"
        with TemporaryDirectory(prefix="fee012-tier-negative-", dir="/tmp") as tmp:
            trial = Path(tmp) / "native-evidence.json"
            trial.write_text(json.dumps(evidence))
            with self.assertRaises(ValueError):
                replay_scripted_receipt(trial, row)


if __name__ == "__main__":
    unittest.main()
