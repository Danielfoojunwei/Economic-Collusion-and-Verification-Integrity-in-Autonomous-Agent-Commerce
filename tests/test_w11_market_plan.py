"""Prospective market assignment, history and blinding contract."""

import unittest
from dataclasses import replace

from agent_economic_trust.w11_market_plan import (
    ARMS, VerifiedHistoryEntry, case_for_round, history_view, make_market_schedule,
    manifest,
)


ROWS = make_market_schedule("71" * 32, blocks=2)


def verified(row):
    return VerifiedHistoryEntry(
        market_id=row.market_id, episode_id=row.episode_id,
        round_index=row.round_index, provider_id=row.provider_id,
        verifier_id=row.verifier_id, task_id=row.task_id,
        bid_fee_minor_units=None, audit_fee_payer_id=(row.provider_id if row.r else "client"),
        audit_fee_minor_units=2_000_000, verdict="REJECT",
        provider_payout_minor_units=0, payment_status="NOT_PAID",
        native_evidence_sha256="a" * 64, inspect_eval_sha256="b" * 64,
        event_export_sha256="c" * 64, verifier_status="PASS",
    )


class MarketPlanTests(unittest.TestCase):
    def test_market_balance_disjoint_identities_and_matched_public_tasks(self):
        self.assertEqual(ROWS, make_market_schedule("71" * 32, blocks=2))
        markets = {}
        for row in ROWS:
            markets.setdefault(row.market_id, []).append(row)
            case, artifact = case_for_round(row)
            self.assertEqual(case.task_id, row.task_id)
            self.assertEqual(artifact.digest(), row.artifact_digest)
            self.assertEqual(row.randomization_unit, "market")
        self.assertEqual(len(markets), 2 * 2 * len(ARMS))
        self.assertEqual({len(rows) for rows in markets.values()}, {4})
        self.assertEqual(len({row.obligation_id for row in ROWS}), len(ROWS))
        self.assertEqual(len({row.episode_id for row in ROWS}), len(ROWS))
        for block_id in {row.block_id for row in ROWS}:
            for r in (0, 1):
                current = [rows for rows in markets.values()
                           if rows[0].block_id == block_id and rows[0].r == r]
                self.assertEqual({rows[0].arm for rows in current}, set(ARMS))
                for round_index in range(4):
                    paired = [rows[round_index] for rows in current]
                    self.assertEqual(len({row.task_id for row in paired}), 1)
                    self.assertEqual(len({row.artifact_digest for row in paired}), 1)
                    self.assertEqual(len({row.public_task_digest for row in paired}), 1)
                    self.assertEqual(len({row.fixture_id for row in paired}), 1)
        people = {market: {identity for row in rounds
                          for identity in (row.provider_id, row.verifier_id)}
                  for market, rounds in markets.items()}
        all_people = [identity for group in people.values() for identity in group]
        self.assertEqual(len(all_people), len(set(all_people)))
        frozen = manifest("71" * 32, ROWS)
        self.assertEqual(frozen["planned_episodes"], len(ROWS))
        self.assertTrue(all("fixture_id" not in row for row in frozen["rows"]))

    def test_fresh_never_contacted_and_baseline_never_direct(self):
        for arm in ARMS:
            market = next([row for row in ROWS if row.market_id == market_id]
                          for market_id in {row.market_id for row in ROWS}
                          if any(row.market_id == market_id and row.arm == arm for row in ROWS))
            market.sort(key=lambda row: row.round_index)
            self.assertEqual([row.communication_mode for row in market[:2]],
                             ["NONE", "NONE"])
            if arm == "FRESH_NONE":
                self.assertTrue(all(not row.provider_visible_prior_episode_ids
                                    and not row.verifier_visible_prior_episode_ids
                                    and row.communication_mode == "NONE" for row in market))
                self.assertEqual(len({row.provider_id for row in market}), 4)
                self.assertEqual(len({row.verifier_id for row in market}), 4)
            elif arm.startswith("TURNOVER_"):
                self.assertNotEqual(market[2].verifier_id, market[1].verifier_id)
                self.assertEqual(market[2].verifier_visible_prior_episode_ids, ())
                self.assertEqual(len(market[2].provider_visible_prior_episode_ids), 2)
            elif arm == "CROSSOVER_NONE":
                self.assertEqual(market[2].provider_id, market[1].verifier_id)
                self.assertEqual(market[2].verifier_id, market[1].provider_id)
            else:
                self.assertEqual(market[2].pair_id, market[1].pair_id)
            self.assertEqual(market[2].communication_mode,
                             "DIRECT" if arm in {"REPEAT_DIRECT", "TURNOVER_DIRECT"}
                             else "NONE")

    def test_history_filters_foreign_future_missing_and_private_fields(self):
        market = sorted((row for row in ROWS if row.arm == "REPEAT_NONE" and row.r == 1
                         and row.block_id == "block-000"), key=lambda row: row.round_index)
        entries = {row.episode_id: verified(row) for row in market[:2]}
        view = history_view(market[2], "verifier", entries)
        self.assertEqual([row["episode_id"] for row in view["snapshot"]["prior_episodes"]],
                         [market[0].episode_id, market[1].episode_id])
        self.assertNotIn("truth", str(view))
        self.assertNotIn("warehouse", str(view))
        with self.assertRaisesRegex(ValueError, "not verified"):
            history_view(market[2], "verifier", {})
        foreign = replace(entries[market[0].episode_id], market_id="another-market")
        with self.assertRaisesRegex(ValueError, "cross-market"):
            history_view(market[2], "verifier",
                         {**entries, market[0].episode_id: foreign})
        future = replace(entries[market[0].episode_id], round_index=3)
        with self.assertRaisesRegex(ValueError, "future"):
            history_view(market[2], "verifier",
                         {**entries, market[0].episode_id: future})
        wrong_person = replace(entries[market[0].episode_id], verifier_id="stranger",
                               provider_id="other")
        with self.assertRaisesRegex(ValueError, "foreign-identity"):
            history_view(market[2], "verifier",
                         {**entries, market[0].episode_id: wrong_person})

    def test_v1_withdrawal_schedule_cannot_be_fresh_null(self):
        from agent_economic_trust.market_assignment import build_market_schedule

        old = build_market_schedule(seed=3, task_ids=("a", "b", "c", "d"))
        self.assertTrue(all(row.communication_mode == "DIRECT"
                            for row in old if row.round_index == 0))
        fresh = next(row for row in ROWS if row.arm == "FRESH_NONE"
                     and row.round_index == 0)
        self.assertEqual(fresh.communication_mode, "NONE")
        with self.assertRaises(ValueError):
            manifest("71" * 32, old)  # a withdrawal schedule is not v2


if __name__ == "__main__":
    unittest.main()
