"""Zero-network negatives for the prospective AP2 paid runner boundary."""

from __future__ import annotations

import asyncio
from pathlib import Path
from hashlib import sha256
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from inspect_ai.model import ChatMessageUser, GenerateConfig

from agent_economic_trust.ap2_live_plan import CANONICAL_LEDGER_PATH
from agent_economic_trust.ap2_live_plan import make_schedule
from agent_economic_trust.ap2_live_remote import (Ap2LivePlan, guard_api)
from agent_economic_trust.open004_task import invoice_case
from agent_economic_trust.open005_native import (Open005NativeController,
    verify_open005_funded_evidence)
from agent_economic_trust.remote import RemoteBoundaryError
from scripts.collect_ap2_live import collect


class Ap2LiveRunnerTests(unittest.TestCase):
    def test_worktree_local_ledger_is_rejected_before_freeze_read(self):
        plan = Ap2LivePlan(ledger_path=Path("/tmp/worktree-ledger.jsonl"))
        self.assertNotEqual(plan.ledger_path, CANONICAL_LEDGER_PATH)
        with self.assertRaisesRegex(RemoteBoundaryError, "canonical frozen limits"):
            plan.validate()

    def test_invalid_sdk_retry_or_bytes_cannot_reach_provider(self):
        calls = []

        async def provider(input, tools, tool_choice, config):
            calls.append((input, tools, tool_choice, config))
            return SimpleNamespace()

        model = SimpleNamespace(api=SimpleNamespace(generate=provider))
        observed = guard_api(model, Ap2LivePlan(max_input_bytes=64))
        base = dict(reasoning_effort="high", reasoning_history="none",
                    max_tokens=4096, max_retries=0)
        with self.assertRaisesRegex(RemoteBoundaryError, "exceeded frozen"):
            asyncio.run(model.api.generate([ChatMessageUser(content="X" * 100)],
                                           [], "auto", GenerateConfig(**base)))
        with self.assertRaisesRegex(RemoteBoundaryError, "exceeded frozen"):
            asyncio.run(model.api.generate([], [], "auto",
                                           GenerateConfig(**{**base, "max_retries": 1})))
        self.assertEqual(calls, [])
        self.assertEqual(len(observed), 2)
        self.assertTrue(all(item["provider_api_invoked"] is False
                            and item["network_forwarding"] == "NO_LOCAL_REJECTION"
                            for item in observed))

    def test_explicit_execute_flag_requires_paid_settings(self):
        from agent_economic_trust.ap2_live_remote import _enabled
        with patch.dict("os.environ", {"ALLOW_EXTERNAL_MODEL_CALLS": "false",
                                      "MAX_REAL_SPEND": "50"}):
            with self.assertRaisesRegex(RemoteBoundaryError, "explicit approved"):
                _enabled()

    def test_no_verdict_preserves_unsettled_native_prefix(self):
        row = next(row for row in make_schedule("ab" * 32) if row.truth == "good")
        fixture, artifact = invoice_case(row.truth)
        root = Path(tempfile.mkdtemp(prefix="ap2-live-prefix-", dir="/tmp"))
        with Open005NativeController(row.native_row(), fixture, artifact,
                                     root / "erc8183"):
            pass
        result = verify_open005_funded_evidence(root / "erc8183")
        self.assertEqual(result["status"], "FUNDED_SUBMITTED_VERIFIED")
        self.assertIs(result["terminal_settlement"], False)

    def test_stopped_partial_hash_is_required_and_denominator_remains_four(self):
        rows = make_schedule("cd" * 32)
        root = Path(tempfile.mkdtemp(prefix="ap2-live-stopped-", dir="/tmp"))
        episode = root / "episodes" / rows[0].episode_id
        episode.mkdir(parents=True)
        partial = episode / "native-partial.json"
        partial.write_text('{"saved":true}\n')
        stop = {
            "episode_id": rows[0].episode_id, "assignment_manifest_sha256": "fake-sha",
            "no_retry_or_substitution": True, "complete_dual_payment_claim": False,
            "billing_state": "ZERO_REQUESTS_PROVEN",
            "provider_api_invoked": False,
            "ledger_run_id": f"ap2live-{'fake-sha'[:12]}-{rows[0].episode_id}",
            "partial_artifacts": [{"path": partial.name,
                                   "sha256": sha256(partial.read_bytes()).hexdigest()}],
        }
        (episode / "STOPPED.json").write_text(json.dumps(stop))
        with (patch("scripts.freeze_ap2_live.verify", return_value=(
                    {"study_id": "ap2-test"}, "fake-sha", rows)),
              patch("agent_economic_trust.ap2_live_remote.RUNS", root),
              patch("scripts.collect_ap2_live.BudgetLedger") as ledger):
            ledger.return_value.snapshot.return_value = {"seq": 1}
            report = collect()
            self.assertEqual((report["planned_episodes"], report["stopped_episodes"],
                              report["pending_episodes"]), (4, 1, 3))
            partial.write_text('{"saved":false}\n')
            with self.assertRaisesRegex(ValueError, "partial archive hash"):
                collect()


if __name__ == "__main__":
    unittest.main()
