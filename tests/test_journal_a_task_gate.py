"""A0.1 fixture preflight against the existing synthetic booking task."""
import unittest

from agent_economic_trust.meeting_booking_market import BookingMarket, booking_oracle, calendar_record


class TaskGateTests(unittest.TestCase):
    def test_public_booking_is_identical_and_oracle_separates_truth(self):
        good = BookingMarket('GOOD').public_view()
        bad = BookingMarket('BAD').public_view()
        self.assertEqual(good, bad)
        self.assertEqual(booking_oracle(good, calendar_record('GOOD'))['status'], 'PASS')
        self.assertEqual(booking_oracle(bad, calendar_record('BAD'))['status'], 'FAIL')

    def test_broken_calendar_is_not_accepted_as_truth(self):
        public = BookingMarket('GOOD').public_view()
        broken = calendar_record('BAD')
        del broken['unavailable_slots']['agent_1']
        with self.assertRaises(ValueError):
            booking_oracle(public, broken)


if __name__ == '__main__':
    unittest.main()
