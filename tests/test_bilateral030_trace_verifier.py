"""Independent read-only Inspect handoff checks using mock-only ORBIT traces."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from inspect_ai.log import write_eval_log

from agent_economic_trust.bilateral030_plan import HIGH_RISK, NO_CONTACT, SOL, SONNET
from agent_economic_trust.bilateral030_trace_verifier import (
    TraceVerificationError, verify_inspect_trace, verify_saved_inspect_trace,
)
import test_bilateral030_task as task_helper


class InspectTraceVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        helper = task_helper.Bilateral030TaskTests()
        cls.channel_row = task_helper._row(HIGH_RISK, SOL)
        cls.no_contact_row = task_helper._row(NO_CONTACT, SONNET)
        cls.channel_log = helper._mock_trace(cls.channel_row)[0]
        cls.no_contact_log = helper._mock_trace(cls.no_contact_row)[0]
        cls.scripted_bad_approve_log = helper._mock_trace(
            cls.channel_row, decision="APPROVE")[0]
        cls.unchecked_approve_log = helper._mock_trace(
            cls.channel_row, decision="APPROVE", buy_check=False)[0]
        cls.wait_log = helper._mock_trace(cls.channel_row, choice="WAIT")[0]

    def verify_channel(self, log=None):
        return verify_inspect_trace(log or self.channel_log,
                                    self.channel_row,
                                    task_helper._prefix(self.channel_row))

    def test_exact_model_note_exposure_and_reverse_direction_mask(self):
        received = self.verify_channel()
        withheld = verify_inspect_trace(self.no_contact_log, self.no_contact_row,
                                        task_helper._prefix(self.no_contact_row))
        self.assertEqual(received["status"],
                         "INSPECT_TRACE_VERIFIED_NATIVE_JOIN_REQUIRED")
        self.assertTrue(received["provider_note_exposed_to_auditor"])
        self.assertFalse(withheld["provider_note_exposed_to_auditor"])
        self.assertEqual(received["early_decision"], "REJECT")
        self.assertEqual(received["check_oracle_status_controller_claim"], "FAIL")
        self.assertFalse(received["scientific_result_row"])
        self.assertEqual(received["model_behavior_tier"], "SCRIPTED_SIMULATION")
        self.assertEqual(received["model_event_count"], 5)
        self.assertFalse(received["auditor_saw_fail_check_callback_before_approval"])
        self.assertTrue(received[
            "paid_check_result_model_exposure_before_verdict_trace_verified"])
        self.assertEqual(received["check_feedback_sha256"],
                         received["decision_input_check_feedback_sha256"])

    def test_scripted_bad_approval_has_prior_fail_feedback_but_no_live_evidence(self):
        observed = self.verify_channel(self.scripted_bad_approve_log)
        self.assertTrue(observed["auditor_saw_fail_check_callback_before_approval"])
        self.assertEqual(observed["early_decision"], "APPROVE")
        self.assertEqual(observed["model_behavior_tier"], "SCRIPTED_SIMULATION")
        self.assertFalse(observed["native_receipts_independently_replayed"])
        self.assertLess(observed["check_tool_event_index"],
                        observed["early_decision_model_event_index"])

    def test_unchecked_approval_cannot_claim_knowledge_from_paid_fail(self):
        observed = self.verify_channel(self.unchecked_approve_log)
        self.assertEqual(observed["early_decision"], "APPROVE")
        self.assertFalse(observed["paid_check_requested"])
        self.assertFalse(observed[
            "paid_check_result_model_exposure_before_verdict_trace_verified"])
        self.assertFalse(observed["auditor_saw_fail_check_callback_before_approval"])

    def test_wait_is_terminal_without_forged_note_or_verdict(self):
        observed = self.verify_channel(self.wait_log)
        self.assertEqual(observed["claim_choice"], "WAIT")
        self.assertEqual(observed["model_event_count"], 1)
        self.assertIsNone(observed["provider_note_text"])
        self.assertIsNone(observed["early_decision"])

    def test_saved_archive_is_read_only_and_hashed(self):
        with tempfile.TemporaryDirectory(prefix="bilateral030-trace-") as raw:
            archive = Path(raw) / "inspect.eval"
            write_eval_log(self.channel_log, archive, format="eval")
            result = verify_saved_inspect_trace(
                archive, self.channel_row,
                task_helper._prefix(self.channel_row))
            self.assertEqual(result["provider_note_sha256"],
                             self.verify_channel()["provider_note_sha256"])
            self.assertEqual(len(result["inspect_archive_sha256"]), 64)

    def test_model_call_cannot_be_relabelled_as_tool_authorship(self):
        altered = deepcopy(self.channel_log)
        model = next(event for event in altered.samples[0].events
                     if event.event == "model" and event.model.endswith("provider-transport")
                     and event.output.choices[0].message.tool_calls[0].function ==
                     "post_auditor_note")
        model.output.choices[0].message.tool_calls[0].arguments["message"] = "forged"
        with self.assertRaisesRegex(TraceVerificationError, "model-call origin"):
            self.verify_channel(altered)

    def test_auditor_feedback_cannot_be_changed_after_view(self):
        altered = deepcopy(self.channel_log)
        view = next(event for event in altered.samples[0].events
                    if event.event == "tool" and event.function == "view_claim_inbox")
        data = json.loads(view.result)
        data["provider_inbox"][0]["content"] = "forged note"
        view.result = json.dumps(data)
        with self.assertRaisesRegex(TraceVerificationError, "prior model/tool history"):
            self.verify_channel(altered)

    def test_precheck_buyer_fields_cannot_enter_view_or_model(self):
        altered = deepcopy(self.channel_log)
        view = next(event for event in altered.samples[0].events
                    if event.event == "tool" and event.function == "view_claim_inbox")
        data = json.loads(view.result)
        data["buyer_records"] = {"purchase_order_amount_cents": 350}
        view.result = json.dumps(data)
        auditor = [event for event in altered.samples[0].events
                   if event.event == "model" and event.model.endswith("auditor-transport")]
        for event in auditor[1:]:
            message = next(item for item in event.input
                           if item.role == "tool" and item.function == "view_claim_inbox")
            message.content = view.result
        with self.assertRaisesRegex(TraceVerificationError, "protected buyer fields"):
            self.verify_channel(altered)

    def test_assignment_metadata_and_auditor_route_tamper_fail(self):
        for change in ("metadata", "route", "prompt"):
            altered = deepcopy(self.channel_log)
            sample = altered.samples[0]
            if change == "metadata":
                sample.metadata["bilateral030"]["delivery_to_auditor_withheld"] = True
            elif change == "route":
                sample.metadata["experiment"]["setup"]["agents"][1]["model"] = (
                    "openrouter/anthropic/claude-sonnet-5.5")
            else:
                auditor = next(event for event in sample.events
                               if event.event == "model" and
                               event.model.endswith("auditor-transport"))
                auditor.input[0].content += " Private truth BAD."
            with self.subTest(change=change):
                with self.assertRaises(TraceVerificationError):
                    self.verify_channel(altered)

    def test_per_agent_reasoning_cap_is_required_in_raw_log(self):
        altered = deepcopy(self.channel_log)
        auditor = next(event for event in altered.samples[0].events
                       if event.event == "model" and
                       event.model.endswith("auditor-transport"))
        auditor.config.reasoning_effort = None
        with self.assertRaisesRegex(TraceVerificationError, "reasoning request"):
            self.verify_channel(altered)

    def test_score_cannot_override_raw_early_decision(self):
        altered = deepcopy(self.channel_log)
        altered.samples[0].scores["bilateral030_score"].metadata[
            "early_decision"] = "APPROVE"
        with self.assertRaisesRegex(TraceVerificationError, "score differs"):
            self.verify_channel(altered)


if __name__ == "__main__":
    unittest.main()
