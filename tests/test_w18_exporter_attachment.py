"""Regression for Inspect attachment pooling in the W18 saved-log comparator.

The only task here is the scripted seed-73 calibration case. Long mock model
text becomes an attachment in the native .eval file; no remote model or
held-out case is constructed.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import unittest


os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = "/workspace/.local/share"
os.environ["XDG_CACHE_HOME"] = "/workspace/.cache"
os.environ["XDG_CONFIG_HOME"] = "/workspace/.config"

from inspect_ai import eval as inspect_eval  # noqa: E402
from inspect_ai.log import read_eval_log  # noqa: E402

from agent_economic_trust.meeting_generalization import (  # noqa: E402
    calibration_artifacts, calibration_case,
)
from agent_economic_trust.remote import RemoteBoundaryError  # noqa: E402
from agent_economic_trust.w18_meeting_remote import (  # noqa: E402
    _behavior_signature, compare_runtime_saved_logs,
)
from agent_economic_trust.w18_meeting_task import meeting_audit_orbit  # noqa: E402
from tests.test_w18_meeting_task import scripted_model  # noqa: E402


class SavedAttachmentRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="w18-attachment-", dir="/workspace")
        cls.root = Path(cls.temporary.name)
        case = calibration_case()
        good, _ = calibration_artifacts(case)
        model = scripted_model(good, checked=True)
        original_generate = model.api.generate

        async def long_text_generate(input, tools, tool_choice, config):
            result = await original_generate(input, tools, tool_choice, config)
            output = result[0] if isinstance(result, tuple) else result
            for choice in output.choices:
                if not choice.message.tool_calls:
                    # Inspect pools ModelEvent text longer than 100 characters.
                    choice.message.content = "SCRIPTED-CALIBRATION-" + ("a" * 180)
            return result

        model.api.generate = long_text_generate
        [cls.runtime_log] = inspect_eval(
            meeting_audit_orbit(case, scheduler_seconds=60, task_token_limit=12000),
            model=model, log_dir=str(cls.root / "source"), display="none",
            log_realtime=False, max_retries=0, retry_on_error=0,
        )
        if cls.runtime_log.status != "success" or not cls.runtime_log.location:
            raise AssertionError("scripted attachment fixture did not complete")
        cls.source_resolved_log = read_eval_log(
            cls.runtime_log.location, resolve_attachments=True)
        cls.source_unresolved_log = read_eval_log(
            cls.runtime_log.location, resolve_attachments=False)
        saved_path = cls.root / "copied-inspect.eval"
        shutil.copyfile(cls.runtime_log.location, saved_path)
        cls.saved_resolved_log = read_eval_log(str(saved_path), resolve_attachments=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_attachment_resolution_changes_output_but_not_behavior(self) -> None:
        unresolved = _behavior_signature(
            self.source_unresolved_log, include_inputs=False)
        resolved = _behavior_signature(
            self.saved_resolved_log, include_inputs=False)
        self.assertNotEqual(unresolved, resolved)
        self.assertTrue(any(
            "attachment://" in str(row.get("output"))
            for row in unresolved if row["kind"] == "model"
        ))
        self.assertFalse(any(
            "attachment://" in str(row.get("output"))
            for row in resolved if row["kind"] == "model"
        ))
        # The in-memory result can retain references. Comparing its entire
        # output object with a resolved log spuriously rejects the same run.
        self.assertNotEqual(
            _behavior_signature(self.runtime_log, include_inputs=False), resolved)
        self.assertIsNone(compare_runtime_saved_logs(
            self.runtime_log, self.source_resolved_log, self.saved_resolved_log))

    def test_saved_tool_call_or_config_tamper_still_fails(self) -> None:
        forged_call = self.saved_resolved_log.model_copy(deep=True)
        tool_call = next(
            call for event in forged_call.samples[0].events if event.event == "model"
            for choice in event.output.choices
            for call in (choice.message.tool_calls or [])
        )
        tool_call.function = "forged_meeting_action"
        with self.assertRaises(RemoteBoundaryError):
            compare_runtime_saved_logs(
                self.runtime_log, self.source_resolved_log, forged_call)

        forged_config = self.saved_resolved_log.model_copy(deep=True)
        first_model = next(event for event in forged_config.samples[0].events
                           if event.event == "model")
        first_model.config.max_tokens = 999
        with self.assertRaises(RemoteBoundaryError):
            compare_runtime_saved_logs(
                self.runtime_log, self.source_resolved_log, forged_config)


if __name__ == "__main__":
    unittest.main()
