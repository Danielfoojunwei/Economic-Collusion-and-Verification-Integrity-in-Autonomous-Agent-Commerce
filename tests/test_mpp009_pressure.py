"""Zero-model controls for the prospective MPP009 assignment and signer input."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from agent_economic_trust.meeting_booking_market import booking_oracle, calendar_record
from agent_economic_trust.mpp009_market import PressureBookingMarket
from agent_economic_trust.mpp008_budget import (CONDITIONAL_EVIDENCE_REF,
    MPP006_STOPPED_RUN_ID)
from agent_economic_trust.mpp009_budget import budget_preflight
from agent_economic_trust.mpp009_native_service import NativeMeetingService
from agent_economic_trust.mpp009_orbit import dispatch
from agent_economic_trust.mpp009_plan import (CALL_SCHEDULE, MAX_INPUT_BYTES, ROLE_DIRECTIONS,
    full_block_reserve, make_schedule, manifest, reserve_pair)
from agent_economic_trust.mpp009_task import PROVIDER_NOTICE, native_pressure_task
from agent_economic_trust.open_mpp_meeting import commitment


ROOT = Path(__file__).resolve().parents[1]
ROWS = make_schedule("ab" * 32)


class AssignmentTests(unittest.TestCase):
    def test_factorial_and_fresh_agents(self):
        self.assertEqual(len(ROWS), 10)
        self.assertEqual({(r.provider_model_id, r.auditor_model_id) for r in ROWS},
                         set(ROLE_DIRECTIONS))
        self.assertEqual(len([r for r in ROWS if r.truth == "BAD"]), 8)
        self.assertEqual(len([r for r in ROWS if r.truth == "GOOD"]), 2)
        for field in ("episode_id", "trial_id", "pair_id", "provider_id", "auditor_id"):
            self.assertEqual(len({getattr(r, field) for r in ROWS}), 10)
        for direction in ROLE_DIRECTIONS:
            bad = [r for r in ROWS if r.truth == "BAD" and
                   (r.provider_model_id, r.auditor_model_id) == direction]
            self.assertEqual({(r.acceptance_bonus_atomic, r.check_price_atomic) for r in bad},
                             {(0, 2000), (0, 4000), (20000, 2000), (20000, 4000)})
            good = [r for r in ROWS if r.truth == "GOOD" and
                    (r.provider_model_id, r.auditor_model_id) == direction]
            self.assertEqual([(r.acceptance_bonus_atomic, r.check_price_atomic) for r in good],
                             [(0, 2000)])

    def test_seeded_order_and_full_budget(self):
        frozen = manifest("ab" * 32, ROWS)
        self.assertEqual(frozen["execution_order"][0], next(r.episode_id for r in ROWS if
            r.truth == "GOOD" and r.provider_model_id == ROLE_DIRECTIONS[0][0]))
        self.assertEqual(len(set(frozen["execution_order"])), 10)
        self.assertEqual(len(CALL_SCHEDULE), 8)
        self.assertEqual(CALL_SCHEDULE.count("provider"), 3)
        self.assertEqual(CALL_SCHEDULE.count("auditor"), 5)
        self.assertNotIn("truth", frozen["rows"][0])
        self.assertNotEqual(ROWS, make_schedule("cd" * 32))
        prices = {model: {"model_id": model, "input_usd_per_token": "0",
                          "output_usd_per_token": "0",
                          "request_usd": cost, "context_length": 200000,
                          "max_completion_tokens": 8192}
                  for model, cost in zip((ROLE_DIRECTIONS[0][0], ROLE_DIRECTIONS[0][1]),
                                         ("0.450560", "0.172032"), strict=True)}
        self.assertEqual(str(full_block_reserve(prices, ROWS)), "24.903680")
        self.assertEqual(MAX_INPUT_BYTES, 32768)
        catalog_rates = {
            ROLE_DIRECTIONS[0][0]: {"model_id": ROLE_DIRECTIONS[0][0],
                "input_usd_per_token": "0.00001", "output_usd_per_token": "0.00003",
                "request_usd": "0", "context_length": 200000,
                "max_completion_tokens": 8192},
            ROLE_DIRECTIONS[0][1]: {"model_id": ROLE_DIRECTIONS[0][1],
                "input_usd_per_token": "0.000004", "output_usd_per_token": "0.00001",
                "request_usd": "0", "context_length": 200000,
                "max_completion_tokens": 8192}}
        self.assertEqual(str(full_block_reserve(catalog_rates, ROWS)), "29.491200")
        with self.assertRaisesRegex(ValueError, "context"):
            reserve_pair({**catalog_rates, ROLE_DIRECTIONS[0][0]: {
                **catalog_rates[ROLE_DIRECTIONS[0][0]], "context_length": 45055}},
                *ROLE_DIRECTIONS[0])

    def test_invalid_seed_or_cell_rejected(self):
        with self.assertRaises(ValueError):
            make_schedule("not-hex")
        with self.assertRaises(ValueError):
            manifest("cd" * 32, ROWS)
        prices = {model: {"model_id": model, "input_usd_per_token": "0",
                          "output_usd_per_token": "0", "request_usd": "0.1",
                          "context_length": 200000, "max_completion_tokens": 8192}
                  for model in {r.provider_model_id for r in ROWS}}
        with self.assertRaises(ValueError):
            full_block_reserve(prices, ROWS[:-1])

    def test_first_class_contingent_hold_is_subtracted_only_once(self):
        prices = {model: {"model_id": model, "input_usd_per_token": "0",
                          "output_usd_per_token": "0", "request_usd": cost,
                          "context_length": 200000, "max_completion_tokens": 8192}
                  for model, cost in zip((ROLE_DIRECTIONS[0][0], ROLE_DIRECTIONS[0][1]),
                                         ("0.450560", "0.172032"), strict=True)}
        reserves = {r.episode_id: reserve_pair(prices, r.provider_model_id,
                                               r.auditor_model_id) for r in ROWS}
        snapshot = {"cap_usd": "50", "available_usd": "44.68678",
            "reserved_usd": "6.30784", "blocked": False, "unknown_run_ids": [],
            "contingent_run_ids": [MPP006_STOPPED_RUN_ID],
            "runs": {MPP006_STOPPED_RUN_ID: {"status": "CONTINGENT",
                "reserved_usd": "6.30784", "evidence_ref": CONDITIONAL_EVIDENCE_REF,
                "contingent_evidence_ref": CONDITIONAL_EVIDENCE_REF}}}
        answer = budget_preflight(snapshot, reserves)
        self.assertEqual(answer["required_headroom_usd"], "26.9037142")
        self.assertEqual(answer["prior_mpp006_reserved_once_usd"], "6.307840")
        with self.assertRaises(ValueError):
            budget_preflight({**snapshot, "available_usd": "26.9"}, reserves)
        with self.assertRaises(ValueError):
            budget_preflight({**snapshot, "unknown_run_ids": ["other"], "blocked": True}, reserves)
        with self.assertRaises(ValueError):
            budget_preflight({**snapshot, "contingent_run_ids": []}, reserves)


class MarketTests(unittest.TestCase):
    @staticmethod
    def market(row):
        return PressureBookingMarket(row.truth, base_fee_atomic=row.base_fee_atomic,
            acceptance_bonus_atomic=row.acceptance_bonus_atomic,
            check_price_atomic=row.check_price_atomic, episode_id=row.episode_id)

    def test_good_bad_same_public_schedule_private_oracle(self):
        good = next(r for r in ROWS if r.truth == "GOOD")
        bad = next(r for r in ROWS if r.truth == "BAD" and
                   r.provider_model_id == good.provider_model_id and r.check_price_atomic == 2000
                   and r.acceptance_bonus_atomic == 0)
        gp, bp = self.market(good).public_view(), self.market(bad).public_view()
        self.assertEqual(gp["attendance"], bp["attendance"])
        self.assertNotIn("buyer_calendar", json.dumps(gp))
        self.assertEqual(booking_oracle(gp, calendar_record("GOOD"))["status"], "PASS")
        self.assertEqual(booking_oracle(bp, calendar_record("BAD"))["status"], "FAIL")

    def test_terms_price_and_charge_bound_to_controller(self):
        row = next(r for r in ROWS if r.truth == "BAD" and
                   r.check_price_atomic == 4000 and r.acceptance_bonus_atomic == 20000)
        market = self.market(row)
        self.assertEqual(market.public_view()["assigned_check_price_atomic"], 4000)
        with self.assertRaisesRegex(ValueError, "charge"):
            dispatch(market, None, "provider", "select_mpp_flow", {"flow": "session"})
        _, flow = dispatch(market, None, "provider", "select_mpp_flow", {"flow": "charge"})
        with self.assertRaisesRegex(ValueError, "controller-assigned"):
            dispatch(market, flow, "provider", "market_propose", {
                "fee_atomic": 10000, "acceptance_bonus_atomic": 0, "message": "lower bonus"})
        dispatch(market, flow, "provider", "market_propose", {
            "fee_atomic": 10000, "acceptance_bonus_atomic": 20000, "message": "my own proposal"})
        dispatch(market, flow, "auditor", "market_accept", {})
        result, _ = dispatch(market, flow, "auditor", "market_check", {})
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["charged_units"], 4000)
        self.assertEqual(result["remaining_budget_units"], 2000)
        repeat, _ = dispatch(market, flow, "auditor", "market_check", {})
        self.assertEqual(repeat["charged_units"], 0)
        dispatch(market, flow, "auditor", "market_decide", {
            "verdict": "REJECT", "message": "conflict"})
        self.assertEqual(market.export()["internal_service_due_atomic"], 10000)
        self.assertFalse(market.export()["false_approval"])

    def test_inadmissible_price_rejected(self):
        row = ROWS[0]
        with self.assertRaises(ValueError):
            self.market(replace(row, check_price_atomic=3000))


class TaskAndPreflightTests(unittest.TestCase):
    def test_native_request_guard_rejects_price_bonus_calendar_and_wrong_release(self):
        row = next(r for r in ROWS if r.truth == "BAD" and
                   r.acceptance_bonus_atomic == 20000 and r.check_price_atomic == 4000)
        with tempfile.TemporaryDirectory() as temporary:
            service = NativeMeetingService(Path(temporary).resolve(), row)
            prepared = Path(temporary) / "prepare-evidence.json"
            prepared.write_text(json.dumps({"request": service.economics()}))
            market = service.market_factory()(row.truth)
            market.propose("provider", 10000, 20000, "my own words")
            market.accept("auditor")
            request = {"public_service": market.public_view(),
                "buyer_calendar": calendar_record(row.truth),
                "amount_atomic": 4000,
                "prepare_sha256": sha256(prepared.read_bytes()).hexdigest()}
            service.validate_request("check", request)
            for change in (
                {"amount_atomic": 2000},
                {"buyer_calendar": calendar_record("GOOD")},
                {"prepare_sha256": "a" * 64},
                {"public_service": {**request["public_service"], "assigned_check_price_atomic": 2000}},
                {"public_service": {**request["public_service"], "assigned_terms": {
                    "fee_atomic": 10000, "acceptance_bonus_atomic": 0}}},
            ):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    service.validate_request("check", {**request, **change})
            with self.assertRaises(ValueError):
                service.validate_request("release", {"public_service": market.public_view(),
                    "prepare_sha256": request["prepare_sha256"],
                    "amount_atomic": 100000, "verdict": "REJECT"})

    def test_native_task_uses_assigned_price_without_private_notice_leak(self):
        row = next(r for r in ROWS if r.truth == "BAD" and r.check_price_atomic == 4000)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            service = NativeMeetingService(directory, row)
            (directory / "prepare-evidence.json").write_text(json.dumps({
                "request": service.economics(), "balances": {"provider": "50000"}}))
            task = native_pressure_task(row, service=service)
            sample = task.dataset[0]
            agents = sample.metadata["experiment"]["setup"]["agents"]
            self.assertEqual([step["agents"] for step in
                sample.metadata["experiment"]["execution"]["plan"]["steps"]],
                [[role] for role in CALL_SCHEDULE])
            self.assertIn(PROVIDER_NOTICE["BAD"], agents[0]["system_prompt"])
            self.assertNotIn(PROVIDER_NOTICE["BAD"], agents[1]["system_prompt"])
            self.assertNotIn("unavailable_slots", sample.input)
            self.assertEqual(json.loads(sample.input)["native_service_terms"]["check_price_atomic"], 4000)
            with self.assertRaises(ValueError):
                native_pressure_task(replace(row, check_price_atomic=2000), service=service)

    def test_node_live_preflight_rejects_price_and_role_swap(self):
        row = next(r for r in ROWS if r.truth == "BAD" and
                   r.acceptance_bonus_atomic == 20000 and r.check_price_atomic == 4000)
        with tempfile.TemporaryDirectory() as temporary:
            service = NativeMeetingService(Path(temporary).resolve(), row)
            public = service.market_factory()(row.truth).public_view()
            native_terms = {**service.economics(), "prepared_provider_balance_atomic": "50000"}
            decision = {"component": "OPEN_MPP_MEETING", "condition": "OPEN",
                "public_service": public, "terms": public["assigned_terms"],
                "model_execution_tier": "REAL_LLM_REMOTE_APPROVED",
                "native_evidence_verified": True,
                "native_service_terms": native_terms,
                "flow_selection_origin": "MODEL_TOOL_CALL", "selected_flow": "charge",
                "model_provenance": {"raw_actions_audited": True, "reasoning_effort": "high",
                    "reasoning_effort_by_role": {"provider": "high", "auditor": "high"},
                    "expected_models_by_role": {
                        "provider": "openrouter/" + row.provider_model_id,
                        "auditor": "openrouter/" + row.auditor_model_id},
                    "raw_model_events_sha256": "a" * 64},
                "controller_actions": [{"actor": "provider", "function": "select_mpp_flow",
                                        "arguments": {"flow": "charge"}}],
                "verdict": "REJECT", "internal_service_due_atomic": 10000}

            def run(payload):
                body = {**payload, "decision_sha256": commitment(payload)}
                path = Path(temporary) / "decision.json"
                path.write_text(json.dumps(body))
                return subprocess.run(["node", str(ROOT / "protocols/mpp/mpp009-decision-preflight.mjs"),
                    str(path), "charge"], cwd=ROOT, capture_output=True, text=True, timeout=10)

            self.assertEqual(run(decision).returncode, 0)
            altered = json.loads(json.dumps(decision))
            altered["native_service_terms"]["check_price_atomic"] = 2000
            self.assertNotEqual(run(altered).returncode, 0)
            altered = json.loads(json.dumps(decision))
            altered["model_provenance"]["expected_models_by_role"]["auditor"] = (
                altered["model_provenance"]["expected_models_by_role"]["provider"])
            self.assertNotEqual(run(altered).returncode, 0)
            altered = json.loads(json.dumps(decision))
            altered["terms"]["acceptance_bonus_atomic"] = 0
            self.assertNotEqual(run(altered).returncode, 0)


if __name__ == "__main__":
    unittest.main()
