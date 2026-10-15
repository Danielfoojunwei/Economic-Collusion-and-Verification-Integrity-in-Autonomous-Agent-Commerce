"""Fail-closed saved-score checks before W11 history is shown again."""

from types import SimpleNamespace
import unittest

from agent_economic_trust.w11_market_plan import make_market_schedule
from agent_economic_trust.w11_market_remote import _verify_saved_market_score


ROW = next(row for row in make_market_schedule("71" * 32)
           if row.fixture_id == "delivery-bad")


class SavedMarketScoreTests(unittest.TestCase):
    def test_private_oracle_and_verdict_binding(self):
        score = {
            "oracle_status": "FAIL", "Y": 0,
            "artifact_digest": ROW.artifact_digest,
            "V": "REJECT", "Q": True,
            "check_spent_units": ROW.check_cost_units,
        }
        saved = SimpleNamespace(samples=[SimpleNamespace(scores={
            "protected_receipt_score": SimpleNamespace(metadata=score),
        })])
        record = {"verdict": "REJECT", "checked": True,
                  "check_spent_units": ROW.check_cost_units,
                  "oracle_truth": 0}
        self.assertIs(_verify_saved_market_score(ROW, saved, record), score)
        for key, wrong in (("oracle_status", "PASS"), ("Y", 1),
                           ("artifact_digest", "0" * 64),
                           ("V", "ACCEPT"), ("Q", False),
                           ("check_spent_units", 0)):
            with self.subTest(key=key):
                altered = {**score, key: wrong}
                saved.samples[0].scores["protected_receipt_score"].metadata = altered
                with self.assertRaisesRegex(Exception, "private scorer"):
                    _verify_saved_market_score(ROW, saved, record)


if __name__ == "__main__":
    unittest.main()
