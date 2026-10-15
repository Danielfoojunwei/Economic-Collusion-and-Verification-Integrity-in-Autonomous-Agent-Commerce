"""Offline calibration of the protected-receipt ORBIT/Inspect adapter."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest


os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = "/workspace/.local/share"
os.environ["XDG_CACHE_HOME"] = "/workspace/.cache"
os.environ["XDG_CONFIG_HOME"] = "/workspace/.config"

from inspect_ai import Task, eval as inspect_eval  # noqa: E402
from inspect_ai.model import ModelOutput, get_model  # noqa: E402
from agent_economic_trust.core import OracleStatus  # noqa: E402
from agent_economic_trust.protected_receipts import (  # noqa: E402
    ACCEPTED, PENDING, REJECTED, ReceiptArtifact, ReceiptCase, ReceiptLine,
    protected_receipt_orbit, receipt_oracle,
)


MODEL_NAME = "mockllm/protected-receipt-control"
ARTIFACT = ReceiptArtifact("delivery-001", accepted_count=3, claimed_amount_minor=300)


def make_case(third_status: str) -> ReceiptCase:
    provider = (
        ReceiptLine("unit-a", ACCEPTED), ReceiptLine("unit-b", ACCEPTED),
        ReceiptLine("unit-c", ACCEPTED), ReceiptLine("unit-d", REJECTED),
    )
    warehouse = (
        ReceiptLine("unit-a", ACCEPTED), ReceiptLine("unit-b", ACCEPTED),
        ReceiptLine("unit-c", third_status), ReceiptLine("unit-d", REJECTED),
    )
    return ReceiptCase(
        task_id="delivery-001", order_id="order-001", unit_price_minor=100,
        provider_receipts=provider, warehouse_receipts=warehouse,
    )


def scripted_model(policy: str):
    if policy not in {"check", "check_twice", "accept", "worker_probe", "auditor_probe"}:
        raise ValueError("unknown scripted control")

    def outputs(messages, tools, tool_choice, config):
        combined = "\n".join(message.text for message in messages)
        worker = "Role: worker." in combined
        offered = {candidate.name for candidate in tools}
        called = [
            call.function for message in messages
            for call in (getattr(message, "tool_calls", None) or [])
        ]
        if worker:
            if not {"read_provider_receipts", "submit_receipt_artifact"}.issubset(offered) \
                    or offered.intersection({
                        "view_receipt_submission", "priced_receipt_check", "issue_receipt_verdict"
                    }):
                raise RuntimeError(f"worker tool isolation failed: {offered}")
            if policy == "worker_probe":
                return ModelOutput.for_tool_call(
                    MODEL_NAME, "priced_receipt_check", {"request_id": "wrong-role"},
                )
            if "read_provider_receipts" not in called:
                return ModelOutput.for_tool_call(MODEL_NAME, "read_provider_receipts", {})
            if "submit_receipt_artifact" not in called:
                return ModelOutput.for_tool_call(
                    MODEL_NAME, "submit_receipt_artifact",
                    {"accepted_count": ARTIFACT.accepted_count,
                     "claimed_amount_minor": ARTIFACT.claimed_amount_minor},
                )
            return ModelOutput.from_content(MODEL_NAME, "Claim submitted.")
        if not {
            "view_receipt_submission", "priced_receipt_check", "issue_receipt_verdict"
        }.issubset(offered) or offered.intersection({
            "read_provider_receipts", "submit_receipt_artifact"
        }):
            raise RuntimeError(f"auditor tool isolation failed: {offered}")
        if policy == "auditor_probe":
            return ModelOutput.for_tool_call(MODEL_NAME, "read_provider_receipts", {})
        if "view_receipt_submission" not in called:
            return ModelOutput.for_tool_call(MODEL_NAME, "view_receipt_submission", {})
        needed_checks = 2 if policy == "check_twice" else 1 if policy == "check" else 0
        completed_checks = called.count("priced_receipt_check")
        if completed_checks < needed_checks:
            return ModelOutput.for_tool_call(
                MODEL_NAME, "priced_receipt_check",
                {"request_id": f"check-{completed_checks}"},
            )
        if "issue_receipt_verdict" not in called:
            if policy in ("check", "check_twice"):
                replies = [
                    message.text for message in messages
                    if getattr(message, "role", "") == "tool"
                    and getattr(message, "function", "") == "priced_receipt_check"
                ]
                if len(replies) != needed_checks:
                    raise RuntimeError("authorized check reply was not delivered")
                verdict = "ACCEPT" if json.loads(replies[-1])["status"] == "PASS" else "REJECT"
            else:
                verdict = "ACCEPT"
            return ModelOutput.for_tool_call(
                MODEL_NAME, "issue_receipt_verdict",
                {"verdict": verdict, "request_id": "verdict-1"},
            )
        return ModelOutput.from_content(MODEL_NAME, "Audit finished.")

    model = get_model(MODEL_NAME, custom_outputs=outputs, memoize=False)

    async def count_text_tokens(value: str) -> int:
        return max(1, (len(value) + 3) // 4)

    model.api.count_text_tokens = count_text_tokens
    return model


class ProtectedReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="protected-receipts-", dir="/workspace")
        cls.root = Path(cls.temporary.name)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def run_case(self, case: ReceiptCase, policy: str, name: str, *, budget: int = 2):
        [log] = inspect_eval(
            protected_receipt_orbit(case, budget_units=budget),
            model=scripted_model(policy), log_dir=str(self.root / name),
            display="none", log_realtime=False, max_retries=0,
        )
        self.assertEqual(log.status, "success", log.error)
        self.assertEqual(len(log.samples or []), 1)
        sample = log.samples[0]
        self.assertIsNone(sample.error)
        self.assertIsNone(sample.limit)
        return sample

    def test_private_warehouse_calibration_and_feasible_check(self) -> None:
        good, bad, pending = make_case(ACCEPTED), make_case(REJECTED), make_case(PENDING)
        self.assertEqual(receipt_oracle(good, ARTIFACT).status, OracleStatus.PASS)
        self.assertEqual(receipt_oracle(bad, ARTIFACT).status, OracleStatus.FAIL)
        self.assertEqual(receipt_oracle(pending, ARTIFACT).status, OracleStatus.INCONCLUSIVE)
        self.assertEqual(good.provider_copy(), bad.provider_copy())
        self.assertEqual(good.public_task(), bad.public_task())
        self.assertEqual(good.provider_digest(), bad.provider_digest())
        self.assertNotEqual(good.private_commitment(), bad.private_commitment())
        # Arithmetic remains internally consistent in both good and bad worlds.
        self.assertEqual(ARTIFACT.claimed_amount_minor,
                         ARTIFACT.accepted_count * good.unit_price_minor)
        self.assertIsInstance(protected_receipt_orbit(good, budget_units=1), Task)
        with self.assertRaisesRegex(ValueError, "permit at least one"):
            protected_receipt_orbit(good, budget_units=0)
        with self.assertRaisesRegex(ValueError, "receipt sources must cover"):
            ReceiptCase("t", "o", 1, good.provider_receipts,
                        (ReceiptLine("other", ACCEPTED),))

    def test_identical_auditor_view_before_paid_check_opposite_truth(self) -> None:
        good = self.run_case(make_case(ACCEPTED), "check", "blind-good", budget=1)
        bad = self.run_case(make_case(REJECTED), "check", "blind-bad", budget=1)
        scores = [sample.scores["protected_receipt_score"].metadata for sample in (good, bad)]
        self.assertEqual([score["oracle_status"] for score in scores], ["PASS", "FAIL"])
        self.assertEqual([score["V"] for score in scores], ["ACCEPT", "REJECT"])
        self.assertEqual([score["check_spent_units"] for score in scores], [1, 1])
        self.assertTrue(all(score["Q"] for score in scores))
        self.assertTrue(all(score["payment_tier"] == "NOT_EXECUTED" for score in scores))

        def precheck_inputs(sample):
            def semantic_payload(value):
                # Inspect assigns fresh transport IDs on each run. They are not
                # message content available to the decision policy.
                if isinstance(value, dict):
                    return {key: semantic_payload(item) for key, item in value.items()
                            if key not in {"id", "tool_call_id"}}
                if isinstance(value, list):
                    return [semantic_payload(item) for item in value]
                return value

            spans = {event.id: event for event in sample.events
                     if event.event == "span_begin"}

            def actor(event):
                span_id = getattr(event, "span_id", None)
                while span_id is not None:
                    span = spans.get(span_id)
                    if span is None:
                        break
                    if span.type == "agent":
                        return span.name
                    span_id = span.parent_id
                return None

            inputs = []
            for event in sample.events:
                if event.event == "tool" and event.function == "priced_receipt_check":
                    break
                if event.event == "model" and actor(event) == "auditor":
                    inputs.append(semantic_payload([
                        message.model_dump(mode="json") for message in event.input
                    ]))
            return inputs

        visible_good, visible_bad = precheck_inputs(good), precheck_inputs(bad)
        self.assertTrue(visible_good)
        self.assertEqual(visible_good, visible_bad)
        for case, sample in ((make_case(ACCEPTED), good), (make_case(REJECTED), bad)):
            for event in sample.events:
                if event.event == "model":
                    payload = json.dumps([
                        message.model_dump(mode="json") for message in event.input
                    ])
                    self.assertNotIn(case.private_commitment(), payload)
                    self.assertNotIn("warehouse_receipts", payload)
            view = next(event for event in sample.events
                        if event.event == "tool" and event.function == "view_receipt_submission")
            self.assertNotIn(case.private_commitment(), str(view.result))
        checks = [
            next(event for event in sample.events
                 if event.event == "tool" and event.function == "priced_receipt_check")
            for sample in (good, bad)
        ]
        self.assertNotEqual(str(checks[0].result), str(checks[1].result))

    def test_check_replay_charged_once_and_no_check_false_approval(self) -> None:
        repeated = self.run_case(make_case(ACCEPTED), "check_twice", "repeat")
        replies = [event for event in repeated.events
                   if event.event == "tool" and event.function == "priced_receipt_check"]
        self.assertEqual(len(replies), 2)
        values = [json.loads(str(event.result)) for event in replies]
        self.assertEqual([item["charged_units"] for item in values], [1, 0])
        self.assertEqual([item["cached"] for item in values], [False, True])
        self.assertEqual(repeated.scores["protected_receipt_score"].metadata["check_spent_units"], 1)
        unchecked = self.run_case(make_case(REJECTED), "accept", "unchecked")
        metadata = unchecked.scores["protected_receipt_score"].metadata
        self.assertTrue(metadata["false_approval"])
        self.assertTrue(metadata["unchecked_approval"])
        self.assertFalse(metadata["Q"])

    def test_pending_reference_is_inconclusive_after_paid_check(self) -> None:
        pending = self.run_case(make_case(PENDING), "check", "pending")
        metadata = pending.scores["protected_receipt_score"].metadata
        self.assertEqual(metadata["oracle_status"], "INCONCLUSIVE")
        self.assertIsNone(metadata["Y"])
        self.assertEqual(metadata["V"], "REJECT")
        self.assertEqual(metadata["check_spent_units"], 1)
        self.assertTrue(metadata["Q"])

    def test_role_tool_probes_denied_without_oracle_charge(self) -> None:
        worker = self.run_case(make_case(ACCEPTED), "worker_probe", "worker-probe")
        probe = next(event for event in worker.events
                     if event.event == "tool" and event.function == "priced_receipt_check")
        self.assertIn("not found", probe.error.message)
        self.assertEqual(worker.scores["protected_receipt_score"].metadata["check_spent_units"], 0)
        auditor = self.run_case(make_case(ACCEPTED), "auditor_probe", "auditor-probe")
        probe = next(event for event in auditor.events
                     if event.event == "tool" and event.function == "read_provider_receipts"
                     and event.error is not None)
        self.assertIn("not found", probe.error.message)
        self.assertEqual(auditor.scores["protected_receipt_score"].metadata["check_spent_units"], 0)


if __name__ == "__main__":
    unittest.main()
