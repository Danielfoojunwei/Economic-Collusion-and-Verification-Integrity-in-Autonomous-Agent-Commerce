"""W18 offline controls against the pinned ORBIT meeting implementation."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from inspect_ai import Task
from orbit.scenarios.cooperative_allocation.meeting_scheduling.task import meeting_scheduling

from agent_economic_trust.core import OracleStatus
from agent_economic_trust.meeting_generalization import (
    MeetingArtifact,
    MeetingCase,
    calibration_artifacts,
    calibration_case,
    calibration_summary,
    meeting_oracle,
    verify_orbit_source,
)


class MeetingGeneralizationTests(unittest.TestCase):
    def test_pinned_orbit_task_constructs_and_calibration_is_exact(self) -> None:
        self.assertIsInstance(meeting_scheduling(
            num_agents=2, num_meetings=2, num_time_slots=4,
            strict_meeting_ratio=0.5, seed=73, max_turns=4,
        ), Task)
        summary = calibration_summary()
        self.assertEqual(summary["complete_assignments_checked"], 36)
        self.assertEqual(summary["exact_reference_reward"], 2.0)
        self.assertTrue(summary["scorer_agreement"])
        self.assertEqual(summary["model_execution_tier"], "NOT_EXECUTED")
        self.assertEqual(summary["good"]["oracle_status"], "PASS")
        self.assertEqual(summary["bad"]["oracle_status"], "FAIL")

    def test_blinded_view_and_negative_schedule_controls(self) -> None:
        case = calibration_case()
        good, bad = calibration_artifacts(case)
        self.assertEqual(meeting_oracle(case, good).status, OracleStatus.PASS)
        self.assertEqual(meeting_oracle(case, bad).status, OracleStatus.FAIL)
        view = case.public_view(bad)
        serialized = json.dumps(view, sort_keys=True)
        for private_name in ("optimal_schedule", "optimal_reward", "oracle_status",
                             "reference_reward", "reason_code"):
            self.assertNotIn(private_name, serialized)
        self.assertIn("meetings", view)
        self.assertIn("attendance", view)
        self.assertEqual(view["artifact_digest"], bad.digest())

        missing = MeetingArtifact({"agent_0": {}, "agent_1": {}})
        self.assertEqual(meeting_oracle(case, missing).reason_code, "INVALID_ATTENDANCE")
        invalid = MeetingArtifact({agent: dict(row) for agent, row in good.attendance.items()})
        invalid.attendance["agent_0"]["MTG-1"] = True
        self.assertEqual(meeting_oracle(case, invalid).status, OracleStatus.FAIL)
        invalid.attendance["agent_0"]["MTG-1"] = case.problem.num_time_slots
        self.assertEqual(meeting_oracle(case, invalid).status, OracleStatus.FAIL)

    def test_upper_bound_reference_is_inconclusive(self) -> None:
        case = calibration_case()
        good, _ = calibration_artifacts(case)
        unqualified = MeetingCase("unqualified", case.problem.model_copy(update={"optimal_schedule": None}))
        result = meeting_oracle(unqualified, good)
        self.assertEqual(result.status, OracleStatus.INCONCLUSIVE)
        self.assertEqual(result.reason_code, "REFERENCE_NOT_EXACT")
        self.assertIsNone(result.reference_reward)

    def test_source_drift_fails_closed(self) -> None:
        self.assertEqual(len(verify_orbit_source()), 3)
        with patch("agent_economic_trust.meeting_generalization.version", return_value="other"):
            with self.assertRaisesRegex(RuntimeError, "pinned ORBIT"):
                verify_orbit_source()
        with patch("agent_economic_trust.meeting_generalization.ORBIT_SOURCE_SHA256",
                   {"dataset_builder.py": "0" * 64}):
            with self.assertRaisesRegex(RuntimeError, "source hashes differ"):
                verify_orbit_source()


if __name__ == "__main__":
    unittest.main()
