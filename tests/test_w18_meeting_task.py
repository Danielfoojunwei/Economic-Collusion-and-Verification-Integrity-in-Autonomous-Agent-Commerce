"""Scripted, saved-log controls for the W18 ORBIT meeting auditor task.

These tests use only the inspected calibration seed. They never construct the
predeclared held-out pilot or call a remote model.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = "/workspace/.local/share"
os.environ["XDG_CACHE_HOME"] = "/workspace/.cache"
os.environ["XDG_CONFIG_HOME"] = "/workspace/.config"

from inspect_ai import eval as inspect_eval  # noqa: E402
from inspect_ai.log import read_eval_log  # noqa: E402
from inspect_ai.model import ModelOutput, get_model  # noqa: E402

from agent_economic_trust.meeting_generalization import (  # noqa: E402
    MeetingArtifact, calibration_artifacts, calibration_case,
)
from agent_economic_trust.w18_meeting_task import (  # noqa: E402
    MeetingAuditError, _parse_attendance, inspect_meeting_log,
    meeting_audit_orbit,
)


MODEL = "mockllm/w18-meeting-scripted"


def scripted_model(artifact: MeetingArtifact, *, checked: bool):
    """Deterministic model policy, not evidence of independent LLM behavior."""
    def outputs(messages, tools, tool_choice, config):
        combined = "\n".join(message.text for message in messages)
        worker = "Role: worker." in combined
        offered = {tool.name for tool in tools}
        called = [call.function for message in messages
                  for call in (getattr(message, "tool_calls", None) or [])]
        if worker:
            if "submit_meeting_schedule" not in offered or offered.intersection({
                "view_meeting_submission", "priced_meeting_check", "issue_meeting_verdict",
            }):
                raise RuntimeError("worker tool scope differs from the scripted control")
            if "submit_meeting_schedule" not in called:
                return ModelOutput.for_tool_call(MODEL, "submit_meeting_schedule", {
                    "attendance_json": json.dumps(artifact.attendance, sort_keys=True),
                })
            return ModelOutput.from_content(MODEL, "Schedule submitted.")
        if not {"view_meeting_submission", "priced_meeting_check",
                "issue_meeting_verdict"}.issubset(offered) or "submit_meeting_schedule" in offered:
            raise RuntimeError("auditor tool scope differs from the scripted control")
        if "view_meeting_submission" not in called:
            return ModelOutput.for_tool_call(MODEL, "view_meeting_submission", {})
        if checked and "priced_meeting_check" not in called:
            return ModelOutput.for_tool_call(MODEL, "priced_meeting_check", {
                "request_id": "scripted-check-1",
            })
        if "issue_meeting_verdict" not in called:
            replies = [message.text for message in messages
                       if getattr(message, "role", "") == "tool"
                       and getattr(message, "function", "") == "priced_meeting_check"]
            if checked and len(replies) != 1:
                raise RuntimeError("auditor did not receive the priced check")
            verdict = ("ACCEPT" if json.loads(replies[0])["status"] == "PASS" else "REJECT") \
                if checked else "ACCEPT"
            return ModelOutput.for_tool_call(MODEL, "issue_meeting_verdict", {
                "verdict": verdict, "request_id": "scripted-verdict-1",
            })
        return ModelOutput.from_content(MODEL, "Audit finished.")

    model = get_model(MODEL, custom_outputs=outputs, memoize=False)

    async def count_text_tokens(value: str) -> int:
        return max(1, (len(value) + 3) // 4)

    model.api.count_text_tokens = count_text_tokens
    return model


class MeetingAuditTaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="w18-meeting-", dir="/workspace")
        cls.root = Path(cls.temporary.name)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def evaluate(self, artifact: MeetingArtifact, label: str, *, checked: bool = True):
        case = calibration_case()
        [log] = inspect_eval(
            meeting_audit_orbit(case, scheduler_seconds=60, task_token_limit=12000),
            model=scripted_model(artifact, checked=checked),
            log_dir=str(self.root / label), display="none", log_realtime=False,
            max_retries=0, retry_on_error=0,
        )
        self.assertEqual(log.status, "success", log.error)
        self.assertIsNotNone(log.location)
        saved = read_eval_log(log.location, resolve_attachments=True)
        self.assertEqual(saved.status, "success")
        return saved, case

    def test_saved_good_and_bad_meeting_logs(self) -> None:
        case = calibration_case()
        good, bad = calibration_artifacts(case)
        for label, artifact, expected_y, expected_verdict in (
            ("good", good, 1, "ACCEPT"), ("bad", bad, 0, "REJECT"),
        ):
            with self.subTest(label=label):
                log, case = self.evaluate(artifact, label)
                inspected = inspect_meeting_log(log, case, expected_model=MODEL)
                self.assertGreaterEqual(inspected["model_events"], 4)
                self.assertEqual(inspected["artifact_digest"], artifact.digest())
                self.assertEqual(inspected["verdict"], expected_verdict)
                self.assertEqual(inspected["priced_check_calls"], 1)
                scored = log.samples[0].scores["meeting_audit_score"].metadata
                self.assertEqual(scored["Y"], expected_y)
                self.assertTrue(scored["Q"])
                self.assertEqual(scored["check_spent_units"], 1)
                self.assertEqual(scored["payment_tier"], "NOT_EXECUTED")

    def test_unchecked_bad_approval_is_recorded_and_metadata_tamper_fails(self) -> None:
        _, bad = calibration_artifacts(calibration_case())
        log, case = self.evaluate(bad, "unchecked-bad", checked=False)
        inspected = inspect_meeting_log(log, case, expected_model=MODEL)
        self.assertEqual(inspected["priced_check_calls"], 0)
        scored = log.samples[0].scores["meeting_audit_score"].metadata
        self.assertTrue(scored["false_approval"])
        self.assertTrue(scored["unchecked_approval"])
        self.assertFalse(scored["Q"])
        log.samples[0].metadata["w18_source_commit"] = "changed-source"
        with self.assertRaisesRegex(MeetingAuditError, "source pin"):
            inspect_meeting_log(log, case, expected_model=MODEL)

    def test_submission_parser_rejects_ambiguous_and_coerced_slots(self) -> None:
        for invalid in (
            '{"agent_0":{},"agent_0":{}}',
            '{"agent_0":{"MTG-1":true}}',
            '{"agent_0":{"MTG-1":NaN}}',
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(Exception):
                    _parse_attendance(invalid)
        with self.assertRaises(MeetingAuditError):
            meeting_audit_orbit(calibration_case(), budget_units=0)

    def test_source_drift_and_wrong_live_model_fail_before_execution(self) -> None:
        case = calibration_case()
        with patch("agent_economic_trust.w18_meeting_task.verify_orbit_source",
                   side_effect=RuntimeError("pinned source differs")):
            with self.assertRaisesRegex(RuntimeError, "pinned source"):
                meeting_audit_orbit(case)
        good, _ = calibration_artifacts(case)
        log, case = self.evaluate(good, "model-guard")
        with self.assertRaisesRegex(MeetingAuditError, "owner-approved model"):
            inspect_meeting_log(log, case, expected_model=MODEL, require_real_model=True)


if __name__ == "__main__":
    unittest.main()
