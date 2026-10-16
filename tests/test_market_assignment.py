"""Offline W11 assignment unit and access boundary checks."""

import unittest
from types import SimpleNamespace

from agent_economic_trust.market_assignment import (
    ARMS, assert_native_channel_adherence, build_market_schedule, schedule_sha256,
)


TASKS = ("task-0", "task-1", "task-2", "task-3")


class MarketAssignmentTests(unittest.TestCase):
    def test_seeded_block_balance_and_no_identity_spillover(self):
        rows = build_market_schedule(seed=73, task_ids=TASKS, blocks=3)
        self.assertEqual(rows, build_market_schedule(seed=73, task_ids=TASKS, blocks=3))
        self.assertEqual(len(rows), 3 * len(ARMS) * len(TASKS))
        self.assertEqual(schedule_sha256(rows), schedule_sha256(tuple(rows)))
        market_people = {}
        for row in rows:
            market_people.setdefault(row.market_id, set()).update((row.provider_id, row.verifier_id))
            self.assertEqual(row.randomization_unit, "market")
            self.assertEqual(row.task_id, TASKS[row.round_index])
        ids = [identity for people in market_people.values() for identity in people]
        self.assertEqual(len(ids), len(set(ids)))
        for block in range(3):
            interventions = [row for row in rows if row.block_id == f"block-{block:03d}"
                             and row.round_index == 2]
            self.assertEqual({row.arm for row in interventions}, set(ARMS))

    def test_turnover_and_communication_interventions(self):
        rows = build_market_schedule(seed=5, task_ids=TASKS)
        grouped = {arm: [row for row in rows if row.arm == arm] for arm in ARMS}
        for arm, market in grouped.items():
            self.assertEqual({row.market_id for row in market}, {market[0].market_id})
            self.assertTrue(all(row.phase == "BASELINE" for row in market[:2]))
            self.assertTrue(all(row.phase == "INTERVENTION" for row in market[2:]))
            self.assertTrue(all(row.communication_mode == "DIRECT" for row in market[:2]))
            self.assertEqual(market[1].verifier_visible_prior_episode_ids, (market[0].episode_id,))
            self.assertEqual(market[1].provider_visible_prior_episode_ids, (market[0].episode_id,))
            if arm.startswith("TURNOVER"):
                self.assertNotEqual(market[2].verifier_id, market[1].verifier_id)
                self.assertEqual(market[2].verifier_visible_prior_episode_ids, ())
                self.assertEqual(market[2].provider_visible_prior_episode_ids,
                                 (market[0].episode_id, market[1].episode_id))
                self.assertEqual(market[3].verifier_visible_prior_episode_ids,
                                 (market[2].episode_id,))
            if arm.startswith("REPEAT"):
                self.assertEqual(market[2].pair_id, market[1].pair_id)
                self.assertEqual(market[2].verifier_visible_prior_episode_ids,
                                 (market[0].episode_id, market[1].episode_id))
            if arm == "CROSSOVER_NO_DIRECT":
                self.assertEqual(market[2].verifier_id, market[1].provider_id)
                self.assertEqual(market[2].provider_id, market[1].verifier_id)
                self.assertEqual(market[2].provider_visible_prior_episode_ids,
                                 (market[0].episode_id, market[1].episode_id))
                self.assertEqual(market[2].verifier_visible_prior_episode_ids,
                                 (market[0].episode_id, market[1].episode_id))
            expected_mode = "DIRECT" if arm in {"REPEAT_DIRECT", "TURNOVER_DIRECT"} else "NONE"
            self.assertTrue(all(row.communication_mode == expected_mode for row in market[2:]))

    def test_malformed_schedule_arguments_rejected(self):
        with self.assertRaises(ValueError):
            build_market_schedule(seed=0, task_ids=("same",) * 4)
        with self.assertRaises(ValueError):
            build_market_schedule(seed=0, task_ids=TASKS, blocks=0)
        with self.assertRaises(ValueError):
            build_market_schedule(seed=0, task_ids=TASKS[:3])

    def test_native_no_channel_requires_absent_capabilities_not_just_zero_calls(self):
        rows = build_market_schedule(seed=5, task_ids=TASKS)
        no_channel = next(row for row in rows if row.arm == "TURNOVER_NO_DIRECT"
                          and row.phase == "INTERVENTION")

        def native_sample(channel_offered=False, channel_called=False):
            events = [
                SimpleNamespace(event="span_begin", id="p", type="agent",
                                name="worker", parent_id=None),
                SimpleNamespace(event="span_begin", id="v", type="agent",
                                name="auditor", parent_id=None),
            ]
            for span_id in ("p", "v"):
                names = ["receipt_tool"] + (["channel_post", "channel_read", "channel_list"]
                                            if channel_offered else [])
                events.append(SimpleNamespace(event="model", span_id=span_id,
                                              tools=[SimpleNamespace(name=name) for name in names]))
            if channel_called:
                events.append(SimpleNamespace(event="tool", span_id="p", function="channel_post"))
            return SimpleNamespace(id=no_channel.task_id, events=events)

        result = assert_native_channel_adherence(
            no_channel, native_sample(), provider_agent_name="worker",
            verifier_agent_name="auditor")
        self.assertEqual(result["channel_tool_calls"], 0)
        with self.assertRaisesRegex(ValueError, "offered a channel capability"):
            assert_native_channel_adherence(
                no_channel, native_sample(channel_offered=True),
                provider_agent_name="worker", verifier_agent_name="auditor")
        alternate_channel = native_sample()
        alternate_channel.events[2].tools.append(SimpleNamespace(name="secret_channel"))
        with self.assertRaisesRegex(ValueError, "offered a channel capability"):
            assert_native_channel_adherence(
                no_channel, alternate_channel,
                provider_agent_name="worker", verifier_agent_name="auditor")
        with self.assertRaisesRegex(ValueError, "executed a channel tool"):
            assert_native_channel_adherence(
                no_channel, native_sample(channel_called=True),
                provider_agent_name="worker", verifier_agent_name="auditor")

    def test_native_direct_arm_requires_capability(self):
        row = next(row for row in build_market_schedule(seed=5, task_ids=TASKS)
                   if row.arm == "REPEAT_DIRECT" and row.phase == "INTERVENTION")
        sample = SimpleNamespace(id=row.task_id, events=[
            SimpleNamespace(event="span_begin", id="p", type="agent",
                            name="worker", parent_id=None),
            SimpleNamespace(event="span_begin", id="v", type="agent",
                            name="auditor", parent_id=None),
            SimpleNamespace(event="model", span_id="p", tools=[]),
            SimpleNamespace(event="model", span_id="v", tools=[]),
        ])
        with self.assertRaisesRegex(ValueError, "lacks an expected channel capability"):
            assert_native_channel_adherence(
                row, sample, provider_agent_name="worker", verifier_agent_name="auditor")


if __name__ == "__main__":
    unittest.main()
