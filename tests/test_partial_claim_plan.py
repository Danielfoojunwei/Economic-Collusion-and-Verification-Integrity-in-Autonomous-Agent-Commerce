"""Prospective partial-claim row and worst-case budget bounds."""

from dataclasses import replace
from decimal import Decimal
import unittest

from agent_economic_trust.partial_claim_plan import (
    CLIENT_PREPAID, NATIVE_CONTINGENT, SOL, SONNET, ROWS,
    full_block_headroom, make_schedule, per_row_reserve, terms, validate_rows)


def sample_catalog():
    common = {"context_length": 1_000_000, "max_completion_tokens": 128_000,
              "request_usd": "0"}
    return {SOL: {**common, "model_id": SOL, "input_usd_per_token": "0.00001",
                  "output_usd_per_token": "0.00003"},
            SONNET: {**common, "model_id": SONNET,
                     "input_usd_per_token": "0.000004",
                     "output_usd_per_token": "0.00001"}}


class PartialClaimPlanTests(unittest.TestCase):
    def test_five_row_bad_factorial_and_one_native_good_anchor(self):
        rows = make_schedule("a7" * 32)
        self.assertEqual(len(rows), ROWS)
        self.assertEqual([r.truth for r in rows], ["bad"] * 4 + ["good"])
        self.assertEqual({(r.fee_term, r.contact) for r in rows[:4]},
                         {(f, c) for f in (NATIVE_CONTINGENT, CLIENT_PREPAID)
                          for c in ("CHANNEL", "NO_CONTACT")})
        self.assertEqual((rows[-1].fee_term, rows[-1].contact),
                         (NATIVE_CONTINGENT, "NO_CONTACT"))
        self.assertNotEqual(make_schedule("a7" * 32), make_schedule("b8" * 32))
        with self.assertRaises(ValueError):
            validate_rows((*rows[:4], replace(rows[-1], fee_term=CLIENT_PREPAID)))

    def test_native_interim_and_full_payment_terms(self):
        rows = make_schedule("a7" * 32)
        native = terms(next(r for r in rows if r.fee_term == NATIVE_CONTINGENT))
        prepaid = terms(next(r for r in rows if r.fee_term == CLIENT_PREPAID))
        self.assertEqual(native["claim_cumulative_minor"], 10_000_000)
        self.assertEqual(prepaid["claim_cumulative_minor"], 9_000_000)
        self.assertEqual(native["provider_interim_payout_minor"],
                         prepaid["provider_interim_payout_minor"])
        self.assertEqual(native["claim_cumulative_minor"],
                         native["provider_interim_payout_minor"] +
                         native["evaluator_interim_native_fee_minor"])
        self.assertEqual(native["provider_full_accept_payout_minor"],
                         prepaid["provider_full_accept_payout_minor"])

    def test_historical_price_preview_and_negative_catalog(self):
        prices = sample_catalog()
        self.assertEqual(per_row_reserve(prices), Decimal("3.981312"))
        self.assertEqual(full_block_headroom(prices), Decimal("21.9065942"))
        with self.assertRaises(ValueError):
            per_row_reserve({SOL: prices[SOL]})
        with self.assertRaises(ValueError):
            per_row_reserve({**prices, SONNET: {**prices[SONNET],
                                                "input_usd_per_token": "NaN"}})
        with self.assertRaises(ValueError):
            per_row_reserve({**prices, SOL: {**prices[SOL], "context_length": 100}})


if __name__ == "__main__":
    unittest.main()
