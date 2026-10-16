"""Offline standing-offer business rule and ORBIT005 source checks."""
from __future__ import annotations

import asyncio
import json
from hashlib import sha256
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent_economic_trust.free_mpp_native_orbit_adapter import ARMS, INDUCED
from agent_economic_trust.free_mpp_native_orbit004_lifecycle import assigned_row as prior_row
from agent_economic_trust.free_mpp_native_orbit005_offer_role import (
    AUDITOR_STANDING_RULE, ORDERED_SCHEDULE, STANDING_AUDITOR_TOOLS,
    assigned_row, assignment, build_task, standing_offer_policy,
    ordered_proposal_policy,
)
from agent_economic_trust.free_mpp_native_orbit005_chain import (
    CONTAINER, HTTP_URL, IMAGE, RPC_URL, adapted_chain_identity, validate_marker,
)
from agent_economic_trust.mpp010_native_service import NativeMeetingService
from agent_economic_trust import mpp010_boundary, mpp010_orbit
from agent_economic_trust.free_mpp_native_orbit_delivery import delivered_market_accept
from agent_economic_trust.open_mpp_meeting import MeetingMarket
from agent_economic_trust.reporting import _agent_for_event
from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log
from inspect_ai.model import ChatMessageTool, ModelOutput, get_model
from inspect_ai.model._providers.openrouter import OpenRouterAPI
from scripts import run_free_mpp_native_orbit005 as runner
from scripts.review_free_mpp_native_orbit005 import verify_ordered_model_sequence

ROOT = Path(__file__).resolve().parents[1]


def marker() -> dict:
    return {
        "rpc_url": RPC_URL, "container": CONTAINER, "image": IMAGE,
        "chain_id": 1337, "test_only": True, "marker_amount_atomic": "1015",
        "source_sha256": sha256((ROOT / "protocols/mpp/free-orbit005-chain-marker.mjs").read_bytes()).hexdigest(),
        "genesis_hash": "0x" + "1" * 64,
        "marker_transaction_hash": "0x" + "2" * 64,
        "marker_block_hash": "0x" + "3" * 64,
        "marker_block_number": "10",
    }


class StandingOfferTests(unittest.TestCase):
    def test_new_rows_and_fixed_business_rule(self):
        plan = assignment()
        self.assertEqual(plan["planned_rows"], 2)
        self.assertEqual(plan["role_schedule"], list(ORDERED_SCHEDULE))
        self.assertEqual(plan["fresh_chain"]["rpc_url"], RPC_URL)
        self.assertEqual(plan["fresh_chain"]["service_url"], HTTP_URL)
        self.assertEqual(plan["fresh_chain"]["marker_amount_atomic"], 1015)
        self.assertIn("ORBIT004 duty arm stopped", plan["post_hoc_motivation"])
        self.assertEqual(len({assigned_row(arm).episode_id for arm in ARMS}), 2)
        for arm in ARMS:
            self.assertNotEqual(assigned_row(arm), prior_row(arm))

    def test_task_auditor_cannot_counteroffer_but_can_choose_outcome(self):
        with TemporaryDirectory() as temp:
            for arm in ARMS:
                directory = Path(temp)
                service = NativeMeetingService(directory, assigned_row(arm))
                (directory / "prepare-evidence.json").write_text(json.dumps({
                    "request": service.economics(), "balances": {"provider": 100000}}))
                experiment = build_task(service).dataset[0].metadata["experiment"]
                provider, auditor = experiment["setup"]["agents"]
                self.assertEqual([step["agents"] for step in experiment["execution"]["plan"]["steps"]],
                                 [[role] for role in ORDERED_SCHEDULE])
                self.assertEqual(set(auditor["tools"]), STANDING_AUDITOR_TOOLS)
                self.assertNotIn("market_propose", auditor["tools"])
                self.assertIn("market_propose", provider["tools"])
                self.assertIn(AUDITOR_STANDING_RULE, auditor["system_prompt"])
                self.assertNotIn(AUDITOR_STANDING_RULE, provider["system_prompt"])
                self.assertEqual("Research control instruction: Your private objective" in
                                 auditor["system_prompt"], arm == INDUCED)
                self.assertIsNone(experiment["communication"])

    def test_live_dispatch_replay_rule_preserves_pending_provider_offer(self):
        terms = {"fee_atomic": 10000, "acceptance_bonus_atomic": 20000,
                 "message": "Please verify independently."}
        market = MeetingMarket("BAD")
        with standing_offer_policy():
            proposal, flow = mpp010_orbit.dispatch(market, "charge", "provider",
                                                   "market_propose", terms)
            self.assertEqual(proposal["actor"], "provider")
            self.assertEqual(market.public_view()["negotiation_messages_untrusted"][-1]["actor"], "provider")
            with self.assertRaisesRegex(ValueError, "unauthorized role tool"):
                mpp010_orbit.dispatch(market, flow, "auditor", "market_propose", terms)
            self.assertEqual(market.public_view()["negotiation_messages_untrusted"][-1]["actor"], "provider")
            accepted, _ = mpp010_orbit.dispatch(market, flow, "auditor", "market_accept", {})
            self.assertEqual(accepted["actor"], "auditor")
            checked, _ = mpp010_orbit.dispatch(market, flow, "auditor", "market_check", {})
            self.assertEqual(checked["status"], "FAIL")
            rejected, _ = mpp010_orbit.dispatch(market, flow, "auditor", "market_decide",
                                                 {"verdict": "REJECT", "message": "Calendar conflict"})
            self.assertEqual(rejected["verdict"], "REJECT")
            self.assertEqual(mpp010_boundary.ROLE_TOOLS["auditor"], STANDING_AUDITOR_TOOLS)
        self.assertIn("market_propose", mpp010_boundary.ROLE_TOOLS["auditor"])
        self.assertIn("market_propose", mpp010_orbit.AUDITOR_TOOLS)

    def test_acceptance_does_not_force_check_or_verdict(self):
        terms = {"fee_atomic": 10000, "acceptance_bonus_atomic": 20000,
                 "message": "Neutral standing offer."}
        with standing_offer_policy():
            for verdict in ("ACCEPT", "REJECT"):
                market = MeetingMarket("BAD")
                mpp010_orbit.dispatch(market, "charge", "provider", "market_propose", terms)
                mpp010_orbit.dispatch(market, "charge", "auditor", "market_accept", {})
                decision, _ = mpp010_orbit.dispatch(market, "charge", "auditor",
                    "market_decide", {"verdict": verdict, "message": "Independent choice"})
                self.assertEqual(decision["verdict"], verdict)

    def test_marker_is_distinct_and_source_bound(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "marker.json"
            fresh = marker()
            path.write_text(json.dumps(fresh))
            self.assertEqual(validate_marker(path), fresh)
            identity = adapted_chain_identity(fresh).decode()
            self.assertIn(RPC_URL, identity)
            self.assertIn(HTTP_URL, identity)
            self.assertIn("marker_amount_atomic: '1015'", identity)
            fresh["marker_amount_atomic"] = "1014"
            path.write_text(json.dumps(fresh))
            with self.assertRaises(ValueError):
                validate_marker(path)

    def test_worker_preparation_stop_is_single_attempt(self):
        with TemporaryDirectory() as temp:
            output = Path(temp)
            frozen = {"offline": True}
            (output / "assignment.json").write_text(json.dumps(frozen))
            arm = ARMS[0]
            row = assigned_row(arm)
            (output / ("worker-intent-" + arm + ".json")).write_text(json.dumps({
                "arm": arm, "episode_id": row.episode_id, "parent_pid": os.getppid(),
                "worker_nonce": "f" * 64,
                "assignment_sha256": sha256((output / "assignment.json").read_bytes()).hexdigest()}))
            with patch.object(runner, "frozen_assignment", return_value=frozen), \
                 patch.object(runner, "validate_marker", return_value=marker()), \
                 patch.object(runner, "prepare_overlay", side_effect=ValueError("offline stop")):
                result = runner.execute_worker(output, output / "marker.json", arm)
            self.assertEqual(result["status"], "STOPPED")
            self.assertEqual(json.loads((output / row.episode_id / "STOPPED.json").read_text())[
                "model_calls_forwarded"], 0)
            self.assertFalse((output / assigned_row(ARMS[1]).episode_id).exists())
            with patch.object(runner, "frozen_assignment", return_value=frozen), \
                 patch.object(runner, "validate_marker", return_value=marker()):
                with self.assertRaises(FileExistsError):
                    runner.execute_worker(output, output / "marker.json", arm)

    def test_parent_first_worker_failure_stops_second(self):
        with TemporaryDirectory() as temp:
            output = Path(temp)
            (output / "assignment.json").write_text("{}")
            launched = []

            class FailedProcess:
                def __init__(self, command, **kwargs):
                    launched.append(command)
                    self.pid = 40000
                    self.returncode = 1

                def communicate(self, timeout=None):
                    return b"", b"failed"

                def poll(self):
                    return self.returncode

            with patch.object(runner.subprocess, "Popen", FailedProcess):
                result = runner._run_workers(output, output / "marker.json")
            self.assertEqual(result["status"], "STOPPED")
            self.assertEqual(len(launched), 1)
            self.assertTrue((output / "BLOCK_STOPPED.json").exists())
            self.assertFalse((output / ("worker-intent-" + ARMS[1] + ".json")).exists())

    def test_real_orbit_mock_offers_standing_terms_without_counterproposal(self):
        """Real scheduler and delivery tool, mock model, no remote or native call."""
        with TemporaryDirectory() as temp:
            directory = Path(temp).resolve()
            service = NativeMeetingService(directory, assigned_row(ARMS[0]))
            (directory / "prepare-evidence.json").write_text(json.dumps({
                "request": service.economics(), "balances": {"provider": 100000}}))
            task = build_task(service)
            for agent in task.dataset[0].metadata["experiment"]["setup"]["agents"]:
                agent["model"] = None

            def outputs(messages, tools, _choice, _config):
                names = {item.name for item in tools}
                called = [call.function for message in messages
                          for call in (getattr(message, "tool_calls", None) or [])]
                route = "mockllm/orbit005-standing-offer-offline"
                if "select_mpp_flow" in names:
                    if "select_mpp_flow" not in called:
                        return ModelOutput.for_tool_call(route, "select_mpp_flow", {"flow": "charge"})
                    if "market_view" not in called:
                        return ModelOutput.for_tool_call(route, "market_view", {})
                    if "market_propose" not in called:
                        return ModelOutput.for_tool_call(route, "market_propose", {
                            "fee_atomic": 10000, "acceptance_bonus_atomic": 20000,
                            "message": "Please verify independently."})
                else:
                    self.assertNotIn("market_propose", names)
                    if "market_accept" not in called:
                        return ModelOutput.for_tool_call(route, "market_accept", {})
                return ModelOutput.from_content(route, "No further action")

            model = get_model("mockllm/orbit005-standing-offer-offline",
                              custom_outputs=outputs, memoize=False)
            with standing_offer_policy(), ordered_proposal_policy(), \
                 patch.object(mpp010_orbit, "market_accept", delivered_market_accept):
                [log] = inspect_eval(task, model=model, max_samples=1,
                    max_tasks=1, epochs=1, retry_on_error=0,
                    fail_on_error=True, time_limit=30, turn_limit=8,
                    log_dir=str(directory / "logs"), log_format="eval",
                    display="none", log_level="error")
            raw = read_eval_log(log.location, resolve_attachments=True)
            sample = raw.samples[0]
            self.assertIsNone(sample.error)
            self.assertEqual([_agent_for_event(e, sample) for e in sample.events
                              if e.event == "model"], list(ORDERED_SCHEDULE))
            self.assertFalse(any(e.event == "tool" and e.function == "market_propose"
                                 and _agent_for_event(e, sample) == "auditor"
                                 for e in sample.events))
            accepted = next(e for e in sample.events if e.event == "tool"
                            and e.function == "market_accept" and not e.error)
            self.assertIn("Please verify independently.", accepted.result)
            later = [e for e in sample.events if e.event == "model"
                     and _agent_for_event(e, sample) == "auditor"
                     and any(isinstance(message, ChatMessageTool)
                             and message.function == "market_accept"
                             and message.tool_call_id == accepted.id
                             and message.text == accepted.result
                             for message in e.input)]
            self.assertTrue(later)
            serialized = asyncio.run(OpenRouterAPI.messages_to_openai(
                SimpleNamespace(model_family=lambda: "dots-3-note-preview"),
                later[0].input))
            self.assertTrue(any(m.get("role") == "tool"
                                and m.get("tool_call_id") == accepted.id
                                and m.get("content") == accepted.result for m in serialized))
            verify_ordered_model_sequence(raw)


if __name__ == "__main__":
    unittest.main()
