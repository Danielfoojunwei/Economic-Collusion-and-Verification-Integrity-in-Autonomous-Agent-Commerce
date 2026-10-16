"""Read-only FEE012 native control replay and scripted-tier identity checks."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_economic_trust.fee012_offline import (ARCHIVE, cases,
    replay_scripted_receipt, verify)
from scripts import verify_erc8183_fee_control as controls


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

    def test_historical_artifact_alias_replays_from_different_upstream_mount(self):
        name, row, _ = cases()[0]
        archived = ARCHIVE / name / "native-evidence.json"
        original_root = controls.UPSTREAM
        original_read_bytes = Path.read_bytes

        def refuse_historical_reads(path):
            if str(path).startswith("/tmp/upstreams/erc8183/out/"):
                raise AssertionError("historical artifact path must not be accessed")
            return original_read_bytes(path)

        with TemporaryDirectory(prefix="fee012-alternate-upstream-", dir="/tmp") as tmp:
            alternate = Path(tmp) / "erc8183"
            alternate.symlink_to(original_root, target_is_directory=True)
            with patch.object(controls, "UPSTREAM", alternate), patch.object(
                    Path, "read_bytes", refuse_historical_reads):
                self.assertEqual(replay_scripted_receipt(archived, row)[
                    "status"], "COMPLETE_VERIFIED")

    def test_historical_artifact_path_and_digest_tamper_rejected(self):
        name, row, _ = cases()[0]
        evidence = json.loads((ARCHIVE / name / "native-evidence.json").read_text())
        with TemporaryDirectory(prefix="fee012-artifact-negative-", dir="/tmp") as tmp:
            trial = Path(tmp) / "native-evidence.json"
            for key, value in (("artifact_path", "/tmp/untrusted/MockUSDC.json"),
                               ("artifact_sha256", "0" * 64)):
                altered = json.loads(json.dumps(evidence))
                altered["contracts"]["MockUSDC"][key] = value
                trial.write_text(json.dumps(altered))
                with self.assertRaises(ValueError):
                    replay_scripted_receipt(trial, row)


if __name__ == "__main__":
    unittest.main()
