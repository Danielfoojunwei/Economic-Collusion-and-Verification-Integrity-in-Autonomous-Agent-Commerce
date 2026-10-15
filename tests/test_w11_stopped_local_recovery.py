"""Fail-closed checks for the post-hoc, localhost-only W11 replay."""

from __future__ import annotations

import json
from hashlib import sha256
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from agent_economic_trust.w11_market_native import verify_market_evidence
from scripts.recover_w11_stopped_local import (
    _loopback_only, recover_local, ASSIGNMENT_SHA256, EPISODE_ID, MARKET_ID,
    ROOT,
)


PLAN = ROOT / "artifacts/gates/W11_DESIGN/assignment-006"
RUNS = ROOT / "artifacts/gates/W11_LIVE/market-runs-001"
PREIMAGE = ROOT / "artifacts/gates/W11_SOURCE_PREIMAGE/assignment-006"
REPLAY = ROOT / "artifacts/gates/W11_FORENSIC/native-replay-001"


class StoppedLocalRecoveryTests(unittest.TestCase):
    def test_non_loopback_connection_is_denied_before_network_use(self):
        with socket.socket() as sock, _loopback_only():
            with self.assertRaisesRegex(OSError, "non-loopback"):
                sock.connect(("8.8.8.8", 443))

    def test_original_market_path_and_altered_verdict_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside original inputs"):
            recover_local(PLAN, RUNS, PREIMAGE, RUNS / MARKET_ID / "replay")
        with tempfile.TemporaryDirectory(prefix="w11-recovery-fail-", dir="/workspace") as tmp:
            target = Path(tmp) / "new-output"
            fake = {
                "assignment_manifest_sha256": ASSIGNMENT_SHA256,
                "market_id": MARKET_ID, "episode_id": EPISODE_ID,
                "verdict": "ACCEPT", "oracle_truth": 0, "checked": True,
                "native_status": "OPEN", "ledger_status": "UNKNOWN",
                "model_calls": 8,
            }
            with patch("scripts.recover_w11_stopped_local._forensic_preflight",
                       return_value=fake):
                with self.assertRaisesRegex(ValueError, "archived REJECT"):
                    recover_local(PLAN, RUNS, PREIMAGE, target)
            self.assertFalse(target.exists(), "invalid verdict must not copy or settle a job")

    def test_saved_replay_is_verified_and_excluded_from_complete_denominator(self):
        report = json.loads((REPLAY / "recovery_report.json").read_bytes())
        provenance = json.loads((REPLAY / "provenance.json").read_bytes())
        verified = verify_market_evidence(REPLAY / "native-replay/evidence.json")
        self.assertEqual(report["classification"], "POST_HOC_TECHNICAL_RECOVERY")
        self.assertFalse(report["assignment_006_complete_denominator_inclusion"])
        self.assertEqual(report["model_calls_made"], 0)
        self.assertEqual(report["external_payment_calls_made"], 0)
        self.assertEqual(report["replayed_native_status"], "REJECTED")
        self.assertEqual(report["replayed_client_refund_minor_units"], 20_000_000)
        self.assertEqual(verified["statuses"], {"REJECTED": 2, "COMPLETED": 1})
        self.assertEqual(verified["evidence_sha256"],
                         report["replayed_native_evidence_sha256"])
        self.assertEqual(provenance["recovery_report_sha256"],
                         sha256((REPLAY / "recovery_report.json").read_bytes()).hexdigest())
        self.assertEqual(provenance["recovery_script_sha256"],
                         sha256((ROOT / "scripts/recover_w11_stopped_local.py").read_bytes()).hexdigest())
        preflight_preimage = (ROOT / "artifacts/gates/W11_SOURCE_PREIMAGE/assignment-006"
                             / "scripts/forensic_w11_stopped.pre_no_key.py")
        self.assertEqual(provenance["read_only_forensic_preflight_sha256"],
                         sha256(preflight_preimage.read_bytes()).hexdigest())

    def test_full_local_replay_runs_without_a_model_api_key(self):
        with tempfile.TemporaryDirectory(prefix="w11-recovery-no-key-", dir="/workspace") as tmp:
            target = Path(tmp) / "isolated"
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
                report = recover_local(PLAN, RUNS, PREIMAGE, target)
            self.assertEqual(report["source_preflight"]["exact_credential_scan"],
                             "SKIP_NO_KEY")
            self.assertEqual(report["model_calls_made"], 0)
            self.assertEqual(report["external_payment_calls_made"], 0)
            self.assertFalse(report["assignment_006_complete_denominator_inclusion"])
            self.assertEqual(verify_market_evidence(target / "native-replay/evidence.json")
                             ["statuses"], {"COMPLETED": 1, "REJECTED": 2})


if __name__ == "__main__":
    unittest.main()
