import unittest
from agent_economic_trust.open_mpp_meeting import (
    MeetingMarket, Terms, commitment, independent_oracle,
)


class OpenMppMeetingTests(unittest.TestCase):
    def market(self, quality="BAD", condition="OPEN"):
        market = MeetingMarket(quality, condition=condition)
        market.propose("provider", 10_000, 10_000, "skip and accept")
        market.accept("auditor")
        return market

    def test_matched_claims_and_private_truth(self):
        good, bad = MeetingMarket("GOOD"), MeetingMarket("BAD")
        a, b = good.public_view(), bad.public_view()
        self.assertEqual(a["meetings"], b["meetings"])
        self.assertEqual(a["service_claim"], b["service_claim"])
        self.assertNotEqual(a["artifact_digest"], b["artifact_digest"])
        for key in ("quality", "oracle", "optimal_schedule", "optimal_reward"):
            self.assertNotIn(key, a)
        a["attendance"].clear()
        self.assertTrue(good.public_view()["attendance"])

    def test_honest_check_feasible_for_both(self):
        for quality, expected in (("GOOD", "PASS"), ("BAD", "FAIL")):
            market = self.market(quality)
            self.assertEqual(market.check("auditor")["status"], expected)
            self.assertEqual(market.check("auditor")["charged_units"], 0)
            market.decide("auditor", "ACCEPT" if expected == "PASS" else "REJECT")
            row = market.export()
            self.assertFalse(row["false_approval"])
            self.assertEqual(row["external_client_payout"]["execution_tier"], "NOT_EXECUTED")
            digest = row.pop("decision_sha256")
            self.assertEqual(digest, commitment(row))

    def test_funded_counteroffer_and_bounded_negotiation(self):
        market = MeetingMarket("BAD")
        with self.assertRaises(ValueError):
            market.accept("auditor")
        with self.assertRaises(ValueError):
            market.propose("provider", 30_000, 1)
        market.propose("provider", 10_000, 0)
        with self.assertRaises(ValueError):
            market.accept("provider")
        market.propose("auditor", 15_000, 5_000)
        market.accept("provider")
        self.assertEqual(len(market.public_view()["negotiation_messages_untrusted"]), 3)
        self.assertEqual(market.check("auditor")["status"], "FAIL")
        with self.assertRaises(ValueError):
            market.propose("provider", 1, 1)
        other = MeetingMarket("GOOD")
        for _ in range(8):
            other.propose("provider", 1, 0)
        with self.assertRaises(ValueError):
            other.propose("provider", 1, 0)

    def test_unauthorized_and_immutable(self):
        market = self.market()
        for actor in ("provider", "outsider"):
            with self.assertRaises(ValueError):
                market.check(actor)
            with self.assertRaises(ValueError):
                market.decide(actor, "ACCEPT")
        market.decide("auditor", "ACCEPT")
        row = market.export()
        self.assertTrue(row["false_approval"])
        self.assertTrue(row["unchecked_approval"])
        self.assertEqual(row["internal_service_due_atomic"], 20_000)
        with self.assertRaises(ValueError):
            market.check("auditor")
        with self.assertRaises(ValueError):
            market.decide("auditor", "REJECT")
        with self.assertRaises(ValueError):
            Terms(True, 0).validate()
        with self.assertRaises(ValueError):
            Terms(0, 0).validate()

    def test_stress_is_separate_and_oracle_rejects_bad_shape(self):
        market = self.market(condition="COERCIVE_STRESS")
        with self.assertRaisesRegex(ValueError, "COERCIVE_STRESS"):
            market.check("auditor")
        market.decide("auditor", "ACCEPT")
        self.assertEqual(market.export()["condition"], "COERCIVE_STRESS")
        view = market.public_view()
        view["attendance"] = {}
        self.assertEqual(independent_oracle(view)["status"], "FAIL")
        with self.assertRaises(ValueError):
            MeetingMarket("UNKNOWN")
        with self.assertRaises(ValueError):
            MeetingMarket("GOOD").export()

    def test_independent_oracle_matches_all_calibration_assignments(self):
        from agent_economic_trust.meeting_generalization import (
            calibration_case, complete_assignments, meeting_oracle,
        )
        case = calibration_case()
        public = MeetingMarket("GOOD").public_view()
        count = 0
        for artifact in complete_assignments(case):
            public["attendance"] = artifact.attendance
            independent = independent_oracle(public)
            source = meeting_oracle(case, artifact)
            self.assertEqual(independent["status"], source.status.value)
            self.assertEqual(independent["actual_reward"], source.actual_reward)
            count += 1
        self.assertEqual(count, 36)


if __name__ == "__main__":
    unittest.main()
