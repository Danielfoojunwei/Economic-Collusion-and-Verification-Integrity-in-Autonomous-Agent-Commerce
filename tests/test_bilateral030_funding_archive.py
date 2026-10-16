"""Public-only pre-view funding archives, with no models or real assets."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from agent_economic_trust.bilateral030_funding_archive import (
    BASE_STEPS, BONUS_STEPS, FundingArchiveError, make_funding_archive,
    write_funding_archive,
)
from agent_economic_trust.bilateral030_native import Bilateral030NativeBridge
from agent_economic_trust.bilateral030_plan import (
    GOOD_ANCHOR, HIGH_RISK, SOL, SONNET, canonical, make_schedule,
)


ROWS = make_schedule("c7" * 32)


class Bilateral030FundingArchiveTest(unittest.TestCase):
    def test_public_only_pre_view_archive_for_bonus_and_absence(self):
        cases = [(HIGH_RISK, SOL, True), (GOOD_ANCHOR, SONNET, False)]
        for group, provider_model, has_bonus in cases:
            with self.subTest(group=group), TemporaryDirectory(
                    prefix="bilateral030-funding-", dir="/tmp") as temp:
                row = next(r for r in ROWS if r.group == group
                           and r.provider_model_id == provider_model)
                directory = Path(temp) / "native"
                with Bilateral030NativeBridge(row, directory) as bridge:
                    target = write_funding_archive(bridge, directory / "public-funding.json")
                    raw = target.read_bytes()
                    archive = json.loads(raw)
                    self.assertEqual(archive["schema"], "erc8183-bilateral030-funding-v1")
                    self.assertEqual(archive["model_behavior_tier"], "NO_MODEL_VIEW_YET")
                    self.assertFalse(archive["independent_funding_replay"])
                    self.assertEqual(archive["public_assignment"]["assigned_bonus_minor"],
                                     row.accept_bonus_minor)
                    self.assertEqual(tuple(tx["step"] for tx in archive["transactions"]),
                                     BASE_STEPS + (BONUS_STEPS if has_bonus else ()))
                    self.assertEqual(archive["public_prefix_sha256"],
                                     sha256(canonical(archive["public_prefix"])).hexdigest())
                    self.assertEqual(archive["job_funding_receipt_sha256"],
                                     sha256(canonical(next(tx["raw_receipt"]
                                         for tx in archive["transactions"]
                                         if tx["step"] == "job.fund"))).hexdigest())
                    self.assertEqual(archive["public_prefix"]["bonus_funded"], has_bonus)
                    if has_bonus:
                        self.assertEqual(archive["hook_state"], 2)
                        self.assertEqual(archive["funded"]["balances_minor_units"]["bonus_escrow"],
                                         5_000_000)
                    else:
                        self.assertEqual(archive["hook_state"], 1)
                        self.assertIsNone(archive["bonus_funding_receipt_sha256"])
                    for forbidden in (b'"truth"', b'"group"', b'"protected_oracle"',
                                      b'"buyer_records"', b'"purchase_order_amount_cents"',
                                      b'"credit_note_amount_cents"', b'"net_amount_cents"',
                                      b'"bad"', b'"good"'):
                        self.assertNotIn(forbidden, raw)
                    with self.assertRaises(FileExistsError):
                        write_funding_archive(bridge, target)
                    bridge.choose_claim(row, "WAIT")
                    with self.assertRaises(FundingArchiveError):
                        make_funding_archive(bridge)


if __name__ == "__main__":
    unittest.main()
