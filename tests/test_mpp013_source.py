"""Pure MPP013 two-role stress design tests; no ORBIT evaluation."""
from __future__ import annotations

from dataclasses import replace
import unittest

from agent_economic_trust.mpp012_plan import (SOL, SONNET,
    make_schedule as mpp012_schedule)
from agent_economic_trust.mpp013_plan import (
    ADVERSARIAL, AUDITOR_STRESS, CELLS, CHANNEL, NO_CONTACT, PROMPTED,
    PROPER, PROPER_SENTENCE, make_schedule, preview_manifest,
    required_headroom, rewrite_auditor_policy, role_prompt_addenda,
    validate_rows,
)
SEED = "13" * 32
ROWS = make_schedule(SEED)
PRICES = {
    SOL: {"model_id": SOL, "context_length": 1_050_000,
          "max_completion_tokens": 128_000, "input_usd_per_token": "0.00001",
          "output_usd_per_token": "0.00003", "request_usd": "0"},
    SONNET: {"model_id": SONNET, "context_length": 1_000_000,
             "max_completion_tokens": 128_000, "input_usd_per_token": "0.000004",
             "output_usd_per_token": "0.00001", "request_usd": "0"},
}


class Mpp013SourceTests(unittest.TestCase):
    def test_fixed_two_role_cells_and_blinded_fresh_ids(self):
        self.assertEqual({(r.truth, r.provider_prompt, r.auditor_policy,
                           r.contact) for r in ROWS}, CELLS)
        self.assertEqual(len(ROWS), 4)
        self.assertEqual(len({r.pair_id for r in ROWS}), 4)
        self.assertTrue({r.native_episode_id for r in ROWS}.isdisjoint(
            {r.native_episode_id for r in mpp012_schedule(SEED)}))
        self.assertTrue(all("BAD" not in r.episode_id and "GOOD" not in r.episode_id
                            for r in ROWS))
        self.assertEqual(preview_manifest(SEED)["status"], "SOURCE_ONLY_UNFROZEN")
        self.assertEqual(make_schedule(SEED), ROWS)
        self.assertEqual(required_headroom(PRICES), "11.4857942")
        with self.assertRaises(ValueError):
            make_schedule("invalid")
        with self.assertRaises(ValueError):
            validate_rows(ROWS[:3])
        with self.assertRaises(ValueError):
            validate_rows((replace(ROWS[0], pair_id=ROWS[1].pair_id), *ROWS[1:]))

    def test_exact_native_terms_and_proper_blindness(self):
        for row in ROWS:
            native = row.native_row
            self.assertEqual(native.episode_id, row.native_episode_id)
            self.assertEqual((native.base_fee_atomic, native.acceptance_bonus_atomic,
                              native.check_price_atomic), (10000, 20000, 4000))
            addenda = role_prompt_addenda(row)
            if row.auditor_policy == PROPER:
                self.assertEqual(addenda["auditor"], "")
            else:
                self.assertEqual(row.truth, "BAD")
                self.assertIn("BAD", addenda["auditor"])
                self.assertIn("20000-unit", addenda["auditor"])
                self.assertIn("4000 units", addenda["auditor"])
            self.assertEqual(bool(addenda["provider"]), row.provider_prompt == PROMPTED)
            self.assertNotIn("unavailable_slots", str(addenda))
        with self.assertRaises(ValueError):
            role_prompt_addenda(replace(ROWS[0], check_price_atomic=9000))

    def test_adversarial_rule_replaces_inherited_proper_rule_once(self):
        proper = next(r for r in ROWS if r.truth == "BAD" and r.auditor_policy == PROPER)
        adversarial = next(r for r in ROWS if r.contact == CHANNEL and
                           r.auditor_policy == ADVERSARIAL)
        no_contact = next(r for r in ROWS if r.contact == NO_CONTACT)
        self.assertEqual(no_contact.auditor_policy, ADVERSARIAL)
        base = "Role: auditor. " + PROPER_SENTENCE + " Final schema applies."
        self.assertEqual(rewrite_auditor_policy(base, proper), base)
        rewritten = rewrite_auditor_policy(base, adversarial)
        self.assertNotIn(PROPER_SENTENCE, rewritten)
        self.assertIn(AUDITOR_STRESS, rewritten)
        with self.assertRaisesRegex(ValueError, "rule differs"):
            rewrite_auditor_policy("Role: auditor. No rule.", adversarial)
        with self.assertRaisesRegex(ValueError, "rule differs"):
            rewrite_auditor_policy(base + PROPER_SENTENCE, adversarial)


if __name__ == "__main__":
    unittest.main()
