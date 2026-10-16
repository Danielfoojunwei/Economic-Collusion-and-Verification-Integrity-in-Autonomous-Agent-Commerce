"""Unfrozen ERC-8183 fee-study assignment and conservative price preview."""

from __future__ import annotations

from decimal import Decimal
import unittest

from agent_economic_trust.erc8183_fee_plan import (
    MAX_INPUT_BYTES, SONNET, SOL, make_schedule, per_row_reserve,
    prospective_manifest)


def prices() -> dict:
    context = MAX_INPUT_BYTES + 8_192 + 4_096
    return {
        SOL: {"model_id": SOL, "context_length": context,
              "max_completion_tokens": 4_096, "input_usd_per_token": "0.000010",
              "output_usd_per_token": "0.000030", "request_usd": "0"},
        SONNET: {"model_id": SONNET, "context_length": context,
                 "max_completion_tokens": 4_096, "input_usd_per_token": "0.000004",
                 "output_usd_per_token": "0.000010", "request_usd": "0"},
    }


class FeePlanTests(unittest.TestCase):
    def test_eight_balanced_cells_and_private_truth(self) -> None:
        seed = "12" * 32
        rows = make_schedule(seed)
        self.assertEqual(len(rows), 8)
        self.assertEqual({(r.truth, r.fee_term, r.contact) for r in rows},
                         {(truth, fee, contact)
                          for truth in ("good", "bad")
                          for fee in ("NATIVE_CONTINGENT", "CLIENT_PREPAID")
                          for contact in ("CHANNEL", "NO_CONTACT")})
        self.assertEqual(len({r.pair_id for r in rows}), 8)
        manifest = prospective_manifest(seed, rows)
        self.assertEqual(manifest["status"], "UNFROZEN_NO_PAID_EXECUTION")
        self.assertNotIn("truth", str(manifest["public_rows"]))
        self.assertTrue(all(r.provider_model_id == SOL and r.auditor_model_id == SONNET
                            for r in rows))
        with self.assertRaises(ValueError):
            make_schedule("bad")
        with self.assertRaises(ValueError):
            prospective_manifest(seed, tuple(reversed(rows)))

    def test_conservative_full_block_arithmetic_and_price_fail_closed(self) -> None:
        self.assertEqual(per_row_reserve(prices()), Decimal("3.440640"))
        self.assertEqual(8 * per_row_reserve(prices()) + Decimal("2.0000342"),
                         Decimal("29.5251542"))
        bad = prices()
        bad[SONNET]["context_length"] -= 1
        with self.assertRaises(ValueError):
            per_row_reserve(bad)
        bad = prices()
        bad[SOL]["output_usd_per_token"] = "0"
        with self.assertRaises(ValueError):
            per_row_reserve(bad)
        bad = prices()
        bad[SONNET]["model_id"] = SOL
        with self.assertRaises(ValueError):
            per_row_reserve(bad)


if __name__ == "__main__":
    unittest.main()
