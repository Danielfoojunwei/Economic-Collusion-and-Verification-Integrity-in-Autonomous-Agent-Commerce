"""Deterministic scripted controls executed by the real ORBIT/Inspect runtime."""

from __future__ import annotations

import json
from pathlib import Path
import re

from inspect_ai import eval as inspect_eval
from inspect_ai.log import EvalLog
from inspect_ai.model import Model, ModelOutput, get_model

from .core import FIXTURES
from .orbit_task import reconciliation_orbit


MODEL_NAME = "mockllm/reconciliation-control"
_ARTIFACT_BY_ID = {
    fixture.task_id: artifact.submitted_amount_cents
    for fixture, artifact in FIXTURES.values()
}


def scripted_model(policy: str = "check") -> Model:
    """Produce offline actions; `policy` is a control, never a measured LLM."""
    if policy not in {"check", "check_twice", "always_accept", "always_reject", "worker_probe"}:
        raise ValueError("unknown scripted policy")

    def outputs(messages, tools, tool_choice, config):
        combined = "\n".join(message.text for message in messages)
        task_match = re.search(r"reconcile-00[123]", combined)
        if task_match is None:
            raise RuntimeError("public task ID was not delivered")
        task_id = task_match.group()
        worker = "Role: worker." in combined
        actor_tools = {tool.name for tool in tools}
        if worker:
            if "submit_artifact" not in actor_tools or actor_tools.intersection(
                {"view_submission", "priced_check", "issue_verdict"}
            ):
                raise RuntimeError(f"worker tool isolation failed: {actor_tools}")
        elif "submit_artifact" in actor_tools or not {
            "view_submission", "priced_check", "issue_verdict"
        }.issubset(actor_tools):
            raise RuntimeError(f"auditor tool isolation failed: {actor_tools}")
        called = {
            call.function
            for message in messages
            for call in (getattr(message, "tool_calls", None) or [])
        }
        if worker:
            if policy == "worker_probe":
                return ModelOutput.for_tool_call(
                    MODEL_NAME, "priced_check", {"request_id": f"unauthorized-{task_id}"},
                )
            if "submit_artifact" not in called:
                return ModelOutput.for_tool_call(
                    MODEL_NAME, "submit_artifact",
                    {"submitted_amount_cents": _ARTIFACT_BY_ID[task_id]},
                )
            return ModelOutput.from_content(MODEL_NAME, "Submission recorded.")
        if "view_submission" not in called:
            return ModelOutput.for_tool_call(MODEL_NAME, "view_submission", {})
        check_calls = sum(
            call.function == "priced_check"
            for message in messages
            for call in (getattr(message, "tool_calls", None) or [])
        )
        needed_checks = 2 if policy == "check_twice" else 1 if policy == "check" else 0
        if check_calls < needed_checks:
            return ModelOutput.for_tool_call(
                MODEL_NAME, "priced_check", {"request_id": f"check-{task_id}"},
            )
        if "issue_verdict" not in called:
            if policy == "always_accept":
                verdict = "ACCEPT"
            elif policy == "always_reject":
                verdict = "REJECT"
            elif policy in {"check", "check_twice"}:
                replies = [
                    message.text for message in messages
                    if getattr(message, "role", "") == "tool"
                    and getattr(message, "function", "") == "priced_check"
                ]
                if len(replies) != needed_checks:
                    raise RuntimeError("authorized check result was not delivered")
                check_status = json.loads(replies[-1])["status"]
                verdict = "ACCEPT" if check_status == "PASS" else "REJECT"
            else:
                verdict = "REJECT"
            return ModelOutput.for_tool_call(
                MODEL_NAME, "issue_verdict",
                {"verdict": verdict, "request_id": f"verdict-{task_id}"},
            )
        return ModelOutput.from_content(MODEL_NAME, "Audit decision recorded.")

    model = get_model(MODEL_NAME, custom_outputs=outputs, memoize=False)

    async def count_text_tokens(value: str) -> int:
        # Avoid mock provider's optional tokenizer download while keeping native
        # Inspect tool, message and token accounting paths exercised.
        return max(1, (len(value) + 3) // 4)

    model.api.count_text_tokens = count_text_tokens
    return model


def run_offline(log_dir: str | Path, *, policy: str = "check") -> EvalLog:
    """Execute one true Inspect evaluation; raises if its native run fails."""
    [log] = inspect_eval(
        reconciliation_orbit(), model=scripted_model(policy),
        log_dir=str(log_dir), display="none", log_realtime=False,
        max_retries=0,
    )
    if log.status != "success" or log.results is None:
        raise RuntimeError(f"Inspect evaluation failed: {log.error}")
    bad = [
        (sample.id, sample.error, sample.limit)
        for sample in log.samples or [] if sample.error or sample.limit
    ]
    if bad:
        raise RuntimeError(f"Inspect sample error or limit: {bad}")
    return log
