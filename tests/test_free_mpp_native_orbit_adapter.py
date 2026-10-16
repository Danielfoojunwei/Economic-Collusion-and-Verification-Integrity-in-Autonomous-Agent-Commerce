"""Offline source and boundary checks for the exploratory live native adapter."""

from __future__ import annotations

from pathlib import Path
import json
import os
import subprocess
import sys
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from inspect_ai.model import ChatMessageSystem

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from agent_economic_trust.free_mpp_native_orbit_adapter import (
    ARMS, INDUCED, INDUCED_AUDITOR_PROMPT, PROVIDER_CONTROL_PROMPT,
    FreeNativeBoundaryError, PRICE_POLICY, ROUTES, ZeroPriceModelGuard,
    assigned_row, bind_reasoning_provenance, build_native_task, prospective_assignment,
    reported_reasoning_by_role, validate_raw_completion,
    validate_wire_request, validate_catalog_tool_support, configure_free_models,
    review_guard_journal, sanitized_call_envelope,
)
from agent_economic_trust.mpp010_native_service import NativeMeetingService
from agent_economic_trust.open_mpp_meeting import commitment
from agent_economic_trust.free_mpp_native_orbit_chain import (
    CONTAINER, IMAGE, RPC_URL, ROOT as CHAIN_ROOT, prepare_overlay, verify_overlay,
)
from scripts.review_free_mpp_native_orbit import _verify_control_prompt_boundary


class ResponseCall:
    def __init__(self, response, request=None):
        self.response = response
        self.request = request


class FreeNativeAdapterTests(unittest.TestCase):
    def test_assignment_is_exploratory_bad_and_actual_free_routes(self):
        plan = prospective_assignment()
        for arm in ARMS:
            row = assigned_row(arm)
            self.assertEqual((row.provider_model_id, row.auditor_model_id),
                             (ROUTES["provider"], ROUTES["auditor"]))
            self.assertEqual((row.truth, row.base_fee_atomic,
                              row.acceptance_bonus_atomic, row.check_price_atomic),
                             ("BAD", 10000, 20000, 4000))
        self.assertNotEqual(assigned_row(ARMS[0]).episode_id,
                            assigned_row(ARMS[1]).episode_id)
        self.assertFalse(plan["scientific_mpp010_result_row"])
        self.assertEqual(plan["planned_rows"], 2)
        self.assertIn("outside the frozen", plan["native_mechanism_limit"])

    def test_wire_requires_exact_model_reasoning_and_zero_price_policy(self):
        model = ROUTES["provider"]
        good = {"model": model, "extra_body": {
            "provider": PRICE_POLICY, "reasoning": {"effort": "high"}}}
        validate_wire_request(good, model)
        for mutation in (
            {"model": ROUTES["auditor"]},
            {"extra_body": {"provider": {"allow_fallbacks": True,
                                         "max_price": PRICE_POLICY["max_price"]},
                            "reasoning": {"effort": "high"}}},
            {"extra_body": {"provider": PRICE_POLICY,
                            "reasoning": {"effort": "low"}}},
            {"stream": True},
            {"extra_body": {"provider": PRICE_POLICY,
                            "reasoning": {"effort": "high"},
                            "models": [ROUTES["auditor"]]}},
        ):
            bad = {**good, **mutation}
            with self.subTest(mutation=mutation), self.assertRaises(FreeNativeBoundaryError):
                validate_wire_request(bad, model)

    def test_raw_response_cost_and_route_are_exact(self):
        model = ROUTES["auditor"]
        good = {"model": model, "id": "r-1", "choices": [{}],
                "usage": {"cost": "0", "prompt_tokens": 4,
                          "completion_tokens": 3, "total_tokens": 7}}
        self.assertEqual(validate_raw_completion((object(), ResponseCall(good)), model)["cost_usd"], "0")
        with_reasoning = {**good, "usage": {**good["usage"],
            "completion_tokens_details": {"reasoning_tokens": 2}}}
        self.assertEqual(validate_raw_completion((object(), ResponseCall(with_reasoning)), model)[
            "reported_reasoning_tokens"], 2)
        for mutation in ({"model": ROUTES["provider"]},
                         {"usage": {**good["usage"], "cost": "0.00001"}},
                         {"usage": {**good["usage"], "cost": None}},
                         {"choices": [{}, {}]}):
            with self.subTest(mutation=mutation), self.assertRaises(FreeNativeBoundaryError):
                validate_raw_completion((object(), ResponseCall({**good, **mutation})), model)

    def test_catalog_route_must_support_tools_and_output_cap(self):
        proof = {"supported_parameters": ["reasoning", "tools"],
                 "max_completion_tokens": 4096}
        validate_catalog_tool_support(proof)
        for change in ({"supported_parameters": ["reasoning"]},
                       {"max_completion_tokens": 1},
                       {"max_completion_tokens": None}):
            with self.assertRaises(FreeNativeBoundaryError):
                validate_catalog_tool_support({**proof, **change})

    def test_journal_is_exclusive_and_durable(self):
        with TemporaryDirectory() as temp:
            journal = Path(temp) / "calls.jsonl"
            guard = ZeroPriceModelGuard(journal, object())
            guard._write({"event": "PREPARED"})
            self.assertEqual(journal.read_text(), '{"event":"PREPARED"}\n')
            with self.assertRaises(FileExistsError):
                ZeroPriceModelGuard(journal, object())

    def test_journal_replay_rejects_unresolved_or_nonzero_account_delta(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "calls.jsonl"
            request = {"model": ROUTES["provider"],
                       "extra_body": {"provider": PRICE_POLICY,
                                      "reasoning": {"effort": "high"}},
                       "max_tokens": 4096, "tools": [{"name": "x"}],
                       "messages": [{"role": "system", "content": "synthetic"}]}
            response = {"model": ROUTES["provider"], "id": "synthetic-1",
                        "choices": [{}], "usage": {"cost": "0", "prompt_tokens": 4,
                        "completion_tokens": 3, "total_tokens": 7,
                        "completion_tokens_details": {"reasoning_tokens": 12}}}
            envelope = sanitized_call_envelope((None, ResponseCall(response, request)),
                                                ROUTES["provider"])
            raw_sha = commitment(envelope)
            raw_path = path.with_name("raw-model-calls.jsonl")
            raw_record = {"call_index": 1, "envelope": envelope,
                          "envelope_sha256": raw_sha}
            raw_path.write_text(json.dumps(raw_record) + "\n")
            start = {"event": "FORWARDING", "call_index": 1,
                     "role": "provider", "model": ROUTES["provider"],
                     "input_bytes": 100, "tool_schemas_sha256": commitment(request["tools"]),
                     "catalog_model_sha256": "b" * 64,
                     "account_usage_before_usd": "1"}
            finish = {"event": "COMPLETED_ZERO_PRICE", "call_index": 1,
                      "role": "provider", "model": ROUTES["provider"],
                      "cost_usd": "0", "account_usage_after_usd": "1",
                      "prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7,
                      "response_id": "synthetic-1",
                      "raw_model_call_sha256": raw_sha,
                      "reported_reasoning_tokens": 12}
            path.write_text(json.dumps(start) + "\n" + json.dumps(finish) + "\n")
            self.assertEqual(review_guard_journal(path)[0]["model"],
                             "openrouter/" + ROUTES["provider"])
            self.assertEqual(reported_reasoning_by_role(path)["by_role"]["provider"][
                "reported_sum"], 12)
            decision = {"model_provenance": {"expected_models_by_role": {
                role: "openrouter/" + model for role, model in ROUTES.items()}},
                "decision_sha256": "old"}
            bound = bind_reasoning_provenance(decision, path)
            self.assertEqual(bound["model_provenance"]["reported_reasoning_usage"][
                "by_call"][0]["reported_reasoning_tokens"], 12)
            self.assertNotEqual(bound["decision_sha256"], "old")
            tampered = json.loads(json.dumps(raw_record))
            tampered["envelope"]["response"]["usage"]["cost"] = "1"
            raw_path.write_text(json.dumps(tampered) + "\n")
            with self.assertRaises(FreeNativeBoundaryError):
                review_guard_journal(path)
            raw_path.write_text(json.dumps(raw_record) + "\n")
            path.write_text(json.dumps(start) + "\n")
            with self.assertRaises(FreeNativeBoundaryError):
                review_guard_journal(path)
            path.write_text(json.dumps({**start, "call_index": 2}) + "\n" +
                            json.dumps({**finish, "call_index": 2}) + "\n")
            with self.assertRaises(FreeNativeBoundaryError):
                review_guard_journal(path)
            path.write_text(json.dumps(start) + "\n" + json.dumps({
                **finish, "model": ROUTES["auditor"]}) + "\n")
            with self.assertRaises(FreeNativeBoundaryError):
                review_guard_journal(path)
            path.write_text(json.dumps(start) + "\n" + json.dumps({
                **finish, "account_usage_after_usd": "1.01"}) + "\n")
            with self.assertRaises(FreeNativeBoundaryError):
                review_guard_journal(path)

    def test_native_inspect_route_configuration_injects_provider_cap_offline(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "offline-dummy"}), \
             TemporaryDirectory() as temp:
            models = configure_free_models()
            guard = ZeroPriceModelGuard(Path(temp) / "calls.jsonl", object())
            try:
                self.assertEqual(guard.install(models, assigned_row(ARMS[0])), [])
                for role, model in models.items():
                    self.assertEqual(str(model), "openrouter/" + ROUTES[role])
                    params = model.api.completion_params(model.config, True)
                    self.assertEqual(params["extra_body"], {
                        "provider": PRICE_POLICY, "reasoning": {"effort": "high"}})
                    self.assertEqual(model.api.client.max_retries, 0)
            finally:
                guard.restore()

    def test_real_orbit_task_metadata_keeps_free_routes_and_prompt_arms(self):
        for arm in ARMS:
            with self.subTest(arm=arm), TemporaryDirectory() as temp:
                row = assigned_row(arm)
                service = NativeMeetingService(Path(temp).resolve(), row)
                (service.evidence_dir / "prepare-evidence.json").write_text(json.dumps({
                    "request": service.economics(),
                    "balances": {"provider": "100000"}}))
                task = build_native_task(service)
                agents = task.dataset[0].metadata["experiment"]["setup"]["agents"]
                self.assertEqual([agent["model"] for agent in agents], [
                    "openrouter/" + ROUTES["provider"],
                    "openrouter/" + ROUTES["auditor"]])
                self.assertIn(PROVIDER_CONTROL_PROMPT, agents[0]["system_prompt"])
                self.assertEqual(INDUCED_AUDITOR_PROMPT in agents[1]["system_prompt"],
                                 arm == INDUCED)

    def test_raw_event_control_prompts_are_role_and_arm_isolated(self):
        def model_event(role, system):
            return SimpleNamespace(event="model", role=role,
                input=[ChatMessageSystem(content=system)])
        provider = model_event("provider", "base" + PROVIDER_CONTROL_PROMPT)
        auditor = model_event("auditor", "client duty")
        log = SimpleNamespace(samples=[SimpleNamespace(events=[provider, auditor])])
        with patch("scripts.review_free_mpp_native_orbit._agent_for_event",
                   side_effect=lambda event, _sample: event.role):
            _verify_control_prompt_boundary(log, ARMS[0])
            with self.assertRaises(ValueError):
                _verify_control_prompt_boundary(log, INDUCED)
            auditor.input = [ChatMessageSystem(content="client duty" + INDUCED_AUDITOR_PROMPT)]
            _verify_control_prompt_boundary(log, INDUCED)
            provider.input = [ChatMessageSystem(content="base")]
            with self.assertRaises(ValueError):
                _verify_control_prompt_boundary(log, INDUCED)

    def test_fresh_chain_overlay_changes_only_pinned_identity(self):
        from hashlib import sha256
        with TemporaryDirectory() as temp:
            path = Path(temp)
            source = CHAIN_ROOT / "protocols/mpp/free-orbit-chain-marker.mjs"
            marker = {"rpc_url": RPC_URL, "container": CONTAINER,
                      "image": IMAGE, "chain_id": 1337, "test_only": True,
                      "marker_amount_atomic": "1011",
                      "source_sha256": sha256(source.read_bytes()).hexdigest(),
                      "genesis_hash": "0x" + "a" * 64,
                      "marker_transaction_hash": "0x" + "b" * 64,
                      "marker_block_hash": "0x" + "c" * 64,
                      "marker_block_number": "743"}
            marker_path = path / "marker.json"
            marker_path.write_text(json.dumps(marker))
            output = path / "output"
            output.mkdir()
            report = prepare_overlay(output, marker_path)
            self.assertEqual([name for name, item in report["helper_hashes"].items()
                              if item["changed"]], ["mpp010-chain-identity.mjs"])
            verify_overlay(output)
            helper = output / "native-overlay/protocols/mpp/mpp010-meeting-local.mjs"
            helper.write_bytes(helper.read_bytes() + b" ")
            with self.assertRaises(ValueError):
                verify_overlay(output)

    def test_free_preflight_accepts_exact_role_pair_and_rejects_route_drift(self):
        """This is a no-RPC decision fixture, checked by the actual Node preflight."""
        with TemporaryDirectory() as temp:
            path = Path(temp) / "decision.json"
            row = assigned_row(ARMS[0])
            terms = {"fee_atomic": 10000, "acceptance_bonus_atomic": 20000}
            decision = {
                "component": "OPEN_MPP_MEETING", "condition": "OPEN",
                "public_service": {"study_id": "mpp-contingent-check-pressure-010",
                                   "assignment_episode_id": row.episode_id,
                                   "assigned_terms": terms,
                                   "assigned_check_price_atomic": 4000},
                "terms": terms,
                "native_service_terms": {"check_price_atomic": 4000,
                    "assigned_base_fee_atomic": 10000,
                    "assigned_acceptance_bonus_atomic": 20000,
                    "assignment_episode_id": row.episode_id,
                    "provider_funding_floor_atomic": 100000,
                    "provider_funding_representation":
                        "MINIMUM_CERTIFIED_BALANCE_EXACT_AMOUNT_WITHHELD"},
                "model_execution_tier": "REAL_LLM_REMOTE_APPROVED",
                "native_evidence_verified": True,
                "flow_selection_origin": "MODEL_TOOL_CALL",
                "selected_flow": "charge",
                "model_provenance": {"raw_actions_audited": True,
                    "reasoning_effort": "high",
                    "reasoning_effort_by_role": {"provider": "high", "auditor": "high"},
                    "expected_models_by_role": {
                        role: "openrouter/" + model for role, model in ROUTES.items()},
                    "raw_model_events_sha256": "a" * 64,
                    "reported_reasoning_usage": {"by_call": [], "by_role": {
                        role: {"reported_sum": 0, "missing_report_count": 1,
                               "reported_call_count": 0} for role in ROUTES}}},
                "controller_actions": [{"actor": "provider", "function":
                    "select_mpp_flow", "arguments": {"flow": "charge"}}],
                "verdict": "REJECT", "internal_service_due_atomic": 10000,
                "oracle": {"status": "FAIL"},
            }
            script = ROOT / "protocols/mpp/free-orbit-decision-preflight.mjs"
            def invoke(payload):
                path.write_text(json.dumps({**payload, "decision_sha256": commitment(payload)}))
                return subprocess.run(["node", str(script), str(path), "charge"],
                                      text=True, capture_output=True, check=False)
            self.assertEqual(invoke(decision).returncode, 0)
            wrong = json.loads(json.dumps(decision))
            wrong["model_provenance"]["expected_models_by_role"]["auditor"] = \
                "openrouter/openai/gpt-5.6-sol"
            self.assertNotEqual(invoke(wrong).returncode, 0)


if __name__ == "__main__":
    unittest.main()
