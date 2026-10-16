"""Native-log role and attachment checks for the protected receipt pilot."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = "/workspace/.local/share"
os.environ["XDG_CACHE_HOME"] = "/workspace/.cache"
os.environ["XDG_CONFIG_HOME"] = "/workspace/.config"

from inspect_ai import eval as inspect_eval  # noqa: E402
from inspect_ai.log import read_eval_log  # noqa: E402

from agent_economic_trust.protected_receipts import protected_receipt_orbit  # noqa: E402
from agent_economic_trust.reporting import _agent_for_event  # noqa: E402
from agent_economic_trust.w10_remote import FROZEN_ARTIFACT, pilot_case  # noqa: E402
from agent_economic_trust.w10_reporting import (  # noqa: E402
    ProtectedEvidenceError, inspect_protected_log,
)
from tests.test_protected_receipts import MODEL_NAME, scripted_model  # noqa: E402


class ProtectedNativeEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = TemporaryDirectory(prefix="w10-report-test-", dir="/workspace")
        cls.case = pilot_case("good")
        [log] = inspect_eval(
            protected_receipt_orbit(cls.case, budget_units=1,
                                    frozen_artifact=FROZEN_ARTIFACT),
            model=scripted_model("check"), log_dir=str(Path(cls.temporary.name) / "log"),
            display="none", log_realtime=False, max_retries=0,
        )
        if log.status != "success":
            raise AssertionError(log.error)
        cls.native = Path(log.location)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def resolved(self):
        return read_eval_log(str(self.native), resolve_attachments=True)

    def inspect(self, log):
        with patch("agent_economic_trust.w10_reporting.MODEL", MODEL_NAME):
            return inspect_protected_log(log, self.case, FROZEN_ARTIFACT)

    def test_pinned_orbit_channel_definitions_are_offered_but_not_called(self) -> None:
        log = self.resolved()
        result = self.inspect(log)
        self.assertEqual(result["priced_check_calls"], 1)
        self.assertGreater(result["auditor_model_events"], 0)
        self.assertFalse(any(event.event == "tool" and event.function.startswith("channel_")
                             for event in log.samples[0].events))

    def test_unresolved_attachments_fail_closed(self) -> None:
        log = read_eval_log(str(self.native))
        with self.assertRaisesRegex(ProtectedEvidenceError, "unresolved Inspect attachments"):
            self.inspect(log)

    def test_channel_call_in_model_output_or_tool_event_is_rejected(self) -> None:
        log = self.resolved()
        event = next(event for event in log.samples[0].events
                     if event.event == "model" and event.output
                     and any(choice.message.tool_calls for choice in event.output.choices))
        event.output.choices[0].message.tool_calls[0].function = "channel_post"
        with self.assertRaisesRegex(ProtectedEvidenceError, "called a channel"):
            self.inspect(log)

        log = self.resolved()
        event = next(event for event in log.samples[0].events if event.event == "tool")
        event.function = "channel_read"
        with self.assertRaisesRegex(ProtectedEvidenceError, "channel tool was called"):
            self.inspect(log)

    def test_offered_channel_definition_and_cross_role_tool_are_rejected(self) -> None:
        log = self.resolved()
        worker = next(event for event in log.samples[0].events
                      if event.event == "model" and
                      _agent_for_event(event, log.samples[0]) == "worker")
        channel = next(tool for tool in worker.tools if tool.name == "channel_post")
        channel.description = "Send the private warehouse truth."
        with self.assertRaisesRegex(ProtectedEvidenceError, "shared channel definition"):
            self.inspect(log)

        log = self.resolved()
        worker = next(event for event in log.samples[0].events
                      if event.event == "model" and
                      _agent_for_event(event, log.samples[0]) == "worker")
        auditor = next(event for event in log.samples[0].events
                       if event.event == "model" and
                       _agent_for_event(event, log.samples[0]) == "auditor")
        worker.tools.append(next(tool for tool in auditor.tools
                                 if tool.name == "priced_receipt_check"))
        with self.assertRaisesRegex(ProtectedEvidenceError, "scoped pilot tools"):
            self.inspect(log)

    def test_resolved_private_truth_in_model_input_is_rejected(self) -> None:
        log = self.resolved()
        worker = next(event for event in log.samples[0].events if event.event == "model")
        worker.input[0].content = str(worker.input[0].content) + self.case.private_commitment()
        with self.assertRaisesRegex(ProtectedEvidenceError, "private warehouse truth"):
            self.inspect(log)


if __name__ == "__main__":
    unittest.main()
