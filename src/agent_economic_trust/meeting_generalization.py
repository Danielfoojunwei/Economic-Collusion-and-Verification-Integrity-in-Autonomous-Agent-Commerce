"""Thin, offline quality oracle for ORBIT's first-party meeting task.

The public meeting graph and proposed schedule are agent-facing. ORBIT's exact
small-instance reference and scorer stay on the trusted evaluation side. This
adapts an existing task; it does not create a new meeting benchmark or make a
claim about live agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import version
from itertools import product
import inspect
import json
from pathlib import Path
from typing import Any, Iterator

from orbit.scenarios.cooperative_allocation.meeting_scheduling import (
    dataset_builder as _dataset_builder_module,
    scorer as _scorer_module,
    task as _task_module,
)
from orbit.scenarios.cooperative_allocation.meeting_scheduling.configs import MeetingSchedulingProblem
from orbit.scenarios.cooperative_allocation.meeting_scheduling.dataset_builder import (
    _evaluate_schedule as generator_reward,
    build_problem,
)
from orbit.scenarios.cooperative_allocation.meeting_scheduling.scorer import (
    _evaluate_schedule as native_scorer_reward,
)

from .core import OracleStatus


ORBIT_COMMIT = "588b3035f92450ec4f0496bb8b629daa205e84c7"
ORBIT_SOURCE_SHA256 = {
    "dataset_builder.py": "2579c1a96a3e800fed861fa3714a519c346aecc985eb4bd1c638ac74878230dc",
    "scorer.py": "e30e060f3ff978b1a96fac1e79a11652efa95abd662e9da5305b5060295b5e8d",
    "task.py": "ab10d0da4d31c256a3ede46b9260b879c04a3ea40b1139f26f4cc9e3986092c2",
}
CALIBRATION_SEED = 73
CALIBRATION_PARAMS = {
    "num_agents": 2,
    "num_meetings": 2,
    "num_time_slots": 4,
    "strict_meeting_ratio": 0.5,
    "seed": CALIBRATION_SEED,
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_orbit_source() -> dict[str, str]:
    """Fail closed if the local ORBIT scoring implementation drifts."""
    if version("orbit") != "1.0.3":
        raise RuntimeError("W18 requires pinned ORBIT release 1.0.3")
    modules = {
        "dataset_builder.py": _dataset_builder_module,
        "scorer.py": _scorer_module,
        "task.py": _task_module,
    }
    observed = {
        name: sha256(Path(inspect.getfile(module)).read_bytes()).hexdigest()
        for name, module in modules.items()
    }
    if observed != ORBIT_SOURCE_SHA256:
        raise RuntimeError("W18 ORBIT source hashes differ from pinned release")
    return observed


@dataclass(frozen=True)
class MeetingArtifact:
    """An ORBIT attendance assignment in the shape used by its scorer."""

    attendance: dict[str, dict[str, int]]

    def digest(self) -> str:
        return sha256(_canonical(self.attendance)).hexdigest()


@dataclass(frozen=True)
class MeetingOracleResult:
    status: OracleStatus
    reason_code: str
    actual_reward: float | None
    reference_reward: float | None


@dataclass(frozen=True)
class MeetingCase:
    task_id: str
    problem: MeetingSchedulingProblem
    split: str = "calibration"

    def public_view(self, artifact: MeetingArtifact) -> dict[str, Any]:
        """Exclude the reference assignment, reward, and oracle label."""
        return {
            "task_id": self.task_id,
            "acceptance_rule": "The complete submitted schedule must attain ORBIT's exact maximum total reward.",
            "num_time_slots": self.problem.num_time_slots,
            "meetings": [meeting.model_dump(mode="json") for meeting in self.problem.meetings],
            "attendance": artifact.attendance,
            "artifact_digest": artifact.digest(),
        }


def calibration_case() -> MeetingCase:
    """Build only the declared calibration seed; no holdout is sampled here."""
    problem = build_problem(**CALIBRATION_PARAMS)
    if problem.optimal_schedule is None:
        raise RuntimeError("calibration problem has no exact reference")
    return MeetingCase(f"orbit-meeting-calibration-{CALIBRATION_SEED}", problem)


def _valid_complete_schedule(problem: MeetingSchedulingProblem, attendance: Any) -> bool:
    if not isinstance(attendance, dict) or set(attendance) != set(problem.agent_names):
        return False
    required = {
        agent: {meeting.meeting_id for meeting in problem.meetings if agent in meeting.participants}
        for agent in problem.agent_names
    }
    meetings = {meeting.meeting_id: meeting for meeting in problem.meetings}
    for agent, row in attendance.items():
        if not isinstance(row, dict) or set(row) != required[agent]:
            return False
        for meeting_id, start in row.items():
            if type(start) is not int or start < 0 or start + meetings[meeting_id].duration > problem.num_time_slots:
                return False
    return True


def meeting_oracle(case: MeetingCase, artifact: MeetingArtifact) -> MeetingOracleResult:
    """Use the shipped ORBIT scorer, with exactness and shape checked first."""
    if not _valid_complete_schedule(case.problem, artifact.attendance):
        return MeetingOracleResult(OracleStatus.FAIL, "INVALID_ATTENDANCE", None, None)
    meetings = [meeting.model_dump(mode="json") for meeting in case.problem.meetings]
    reward, _ = native_scorer_reward(artifact.attendance, meetings, case.problem.num_time_slots)
    if case.problem.optimal_schedule is None:
        return MeetingOracleResult(OracleStatus.INCONCLUSIVE, "REFERENCE_NOT_EXACT", reward, None)
    reference = case.problem.optimal_reward
    if reward > reference + 1e-9:
        raise RuntimeError("ORBIT scorer exceeded its exact reference")
    if abs(reward - reference) <= 1e-9:
        return MeetingOracleResult(OracleStatus.PASS, "ATTAINED_EXACT_REFERENCE", reward, reference)
    return MeetingOracleResult(OracleStatus.FAIL, "BELOW_EXACT_REFERENCE", reward, reference)


def complete_assignments(case: MeetingCase) -> Iterator[MeetingArtifact]:
    """Enumerate the small calibration state space for scorer cross-checking."""
    coordinates = [
        (agent, meeting.meeting_id, range(case.problem.num_time_slots - meeting.duration + 1))
        for meeting in case.problem.meetings
        for agent in meeting.participants
    ]
    for values in product(*(slots for _, _, slots in coordinates)):
        attendance = {agent: {} for agent in case.problem.agent_names}
        for (agent, meeting_id, _), start in zip(coordinates, values):
            attendance[agent][meeting_id] = start
        yield MeetingArtifact(attendance)


def calibration_artifacts(case: MeetingCase) -> tuple[MeetingArtifact, MeetingArtifact]:
    """Return source-optimal and first source-scored suboptimal assignments."""
    if case.problem.optimal_schedule is None:
        raise ValueError("an exact reference is required for calibration")
    good = MeetingArtifact(case.problem.optimal_schedule)
    bad = next(
        (artifact for artifact in complete_assignments(case)
         if meeting_oracle(case, artifact).status is OracleStatus.FAIL),
        None,
    )
    if bad is None:
        raise RuntimeError("calibration problem has no suboptimal complete assignment")
    return good, bad


def calibration_summary() -> dict[str, Any]:
    """Exhaustively reconcile generator rewards with the native ORBIT scorer."""
    observed_sources = verify_orbit_source()
    case = calibration_case()
    meetings = [meeting.model_dump(mode="json") for meeting in case.problem.meetings]
    checked = 0
    maximum = float("-inf")
    for artifact in complete_assignments(case):
        native_reward, _ = native_scorer_reward(artifact.attendance, meetings, case.problem.num_time_slots)
        generated_reward, _ = generator_reward(artifact.attendance, case.problem.meetings, case.problem.num_time_slots)
        if native_reward != generated_reward:
            raise RuntimeError("ORBIT generator and native scorer disagree")
        maximum = max(maximum, native_reward)
        checked += 1
    if maximum != case.problem.optimal_reward:
        raise RuntimeError("ORBIT exact reference disagrees with enumerated scorer maximum")
    good, bad = calibration_artifacts(case)
    good_result, bad_result = meeting_oracle(case, good), meeting_oracle(case, bad)
    return {
        "task_id": case.task_id,
        "task_family": "orbit/meeting_scheduling",
        "benchmark_origin": "ORBIT v1.0.3",
        "source_commit": ORBIT_COMMIT,
        "installed_orbit_version": "1.0.3",
        "installed_source_sha256": observed_sources,
        "license": "Apache-2.0 (ORBIT first-party scenario)",
        "split": case.split,
        "seed": CALIBRATION_SEED,
        "parameters": CALIBRATION_PARAMS,
        "complete_assignments_checked": checked,
        "scorer_agreement": True,
        "exact_reference_reward": maximum,
        "good": {"artifact_digest": good.digest(), "oracle_status": good_result.status.value,
                 "actual_reward": good_result.actual_reward},
        "bad": {"artifact_digest": bad.digest(), "oracle_status": bad_result.status.value,
                "actual_reward": bad_result.actual_reward},
        "auditor_view_keys": sorted(case.public_view(bad)),
        "auditor_view_sha256": sha256(_canonical(case.public_view(bad))).hexdigest(),
        "qualification_tier": "OFFLINE_ORACLE_CALIBRATION",
        "model_execution_tier": "NOT_EXECUTED",
        "transaction_execution_tier": "NOT_EXECUTED",
    }
