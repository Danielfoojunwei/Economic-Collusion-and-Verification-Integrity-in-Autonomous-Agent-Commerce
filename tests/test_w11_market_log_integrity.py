"""Offline regression for the real W11 direct-channel attachment stop."""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest
from dataclasses import replace

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log

from agent_economic_trust.remote import RemoteBoundaryError
from agent_economic_trust.w11_market_log_integrity import compare_market_native_log
from agent_economic_trust.w11_market_plan import make_market_schedule
from agent_economic_trust.w11_market_task import build_market_task
from tests.test_w11_market_task import model_for


ROOT = Path(__file__).resolve().parents[1]
ARCHIVED_DIRECT = (ROOT / "artifacts/gates/W11_LIVE/market-runs-001/"
                   "market-acb40c26ae8838c87fd3/episodes/"
                   "episode-de0a57bf5b8ca2bbe753/inspect.eval")


@unittest.skipUnless(ARCHIVED_DIRECT.is_file(), "archived W11 direct pilot is absent")
class MarketAttachmentIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="w11-archive-regression-", dir="/workspace")
        cls.copied_path = Path(cls.temporary.name) / "inspect.eval"
        shutil.copyfile(ARCHIVED_DIRECT, cls.copied_path)
        cls.unresolved = read_eval_log(str(ARCHIVED_DIRECT), resolve_attachments=False)
        cls.resolved = read_eval_log(str(ARCHIVED_DIRECT), resolve_attachments=True)
        cls.copied = read_eval_log(str(cls.copied_path), resolve_attachments=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def compare(self, runtime=None, saved=None, copied_path=None):
        return compare_market_native_log(
            runtime or self.unresolved, self.unresolved, self.resolved,
            saved or self.copied,
            source_path=ARCHIVED_DIRECT, saved_path=copied_path or self.copied_path,
        )

    def test_real_attachment_expansion_keeps_exact_runtime_decision(self):
        result = self.compare()
        self.assertEqual(result["native_archive_sha256"],
                         "aa3f66f10f4f9a1165f9990687a7f52963d6c855dc340160aa06dab59efb04cb")
        self.assertEqual(result["behavior_events"], 14)
        self.assertEqual(result["attachment_expansions"], 16)
        # Inspect may return either expanded or pooled references in memory.
        self.assertEqual(self.compare(runtime=self.resolved), result)

    def test_tampered_tool_call_and_native_copy_fail_closed(self):
        forged = self.copied.model_copy(deep=True)
        call = next(call for event in forged.samples[0].events if event.event == "model"
                    for choice in (event.output.choices if event.output else [])
                    for call in (choice.message.tool_calls or [])
                    if call.function == "channel_post")
        call.arguments["message"] = "forged provider instruction"
        with self.assertRaises(RemoteBoundaryError):
            self.compare(saved=forged)
        altered_copy = Path(self.temporary.name) / "altered-inspect.eval"
        altered_copy.write_bytes(self.copied_path.read_bytes() + b"extra")
        with self.assertRaises(RemoteBoundaryError):
            self.compare(copied_path=altered_copy)

    def test_unrelated_runtime_model_change_fails_closed(self):
        forged = self.unresolved.model_copy(deep=True)
        model_event = next(event for event in forged.samples[0].events
                           if event.event == "model")
        model_event.config.reasoning_effort = "low"
        with self.assertRaises(RemoteBoundaryError):
            self.compare(runtime=forged)


class ScriptedRuntimeIntegrityTests(unittest.TestCase):
    def test_in_memory_direct_result_matches_exact_copied_archive(self):
        row = next(item for item in make_market_schedule(
            "616e204de1dcd75c17693d84ba501b70dd821c4f02636547267b9c5aa12766aa")
            if item.episode_id == "episode-de0a57bf5b8ca2bbe753")
        row = replace(row, provider_visible_prior_episode_ids=(),
                      verifier_visible_prior_episode_ids=())
        with tempfile.TemporaryDirectory(prefix="w11-scripted-integrity-", dir="/workspace") as tmp:
            [runtime] = inspect_eval(
                build_market_task(row, entries={}, fee_tier="SCRIPTED_CONTROL"),
                model=model_for(row), log_dir=tmp, display="none",
                log_realtime=False, max_retries=0,
            )
            self.assertEqual(runtime.status, "success")
            source = Path(runtime.location)
            saved_path = Path(tmp) / "copied.eval"
            shutil.copyfile(source, saved_path)
            unresolved = read_eval_log(str(source), resolve_attachments=False)
            resolved = read_eval_log(str(source), resolve_attachments=True)
            saved = read_eval_log(str(saved_path), resolve_attachments=True)
            result = compare_market_native_log(runtime, unresolved, resolved, saved,
                                               source_path=source, saved_path=saved_path)
            self.assertGreater(result["behavior_events"], 0)


if __name__ == "__main__":
    unittest.main()
