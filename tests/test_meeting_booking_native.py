"""Offline boundaries for native private-calendar booking; no network or models."""
import asyncio
from pathlib import Path
import tempfile
import subprocess
import json
import unittest
from inspect_ai.tool import ToolError
from agent_economic_trust.open_mpp_meeting import commitment
from agent_economic_trust.meeting_booking_market import BookingMarket, booking_oracle, calendar_record
from agent_economic_trust.open_mpp_native_service import NativeMeetingService, native_service_orbit
from agent_economic_trust.open_mpp_orbit import open_mpp_orbit, market_completion_halt
from unittest.mock import patch
from types import SimpleNamespace


class BookingNativeBoundaryTests(unittest.TestCase):
    def test_native_completion_halt_requires_successful_release_policy(self):
        for decision, expected in [(None, False), ({'verdict': 'ACCEPT'}, False),
            ({'verdict': 'REJECT', 'client_release_policy': 'APPLICATION_ACCEPT_TRIGGER_NOT_NATIVE_ESCROW'}, True)]:
            with patch('agent_economic_trust.open_mpp_orbit.store_as',
                       return_value=SimpleNamespace(decision=decision)):
                self.assertEqual(market_completion_halt(None, require_native=True), expected)

    def test_unicode_commitment_matches_native_json(self):
        payload = {'message': 'Résumé – booking', 'amount': 2000}
        result = subprocess.run(['node', '-e',
            "const fs=require('fs'), c=require('crypto'); const v=JSON.parse(fs.readFileSync(0,'utf8')); process.stdout.write(c.createHash('sha256').update(JSON.stringify(v, Object.keys(v).sort())).digest('hex'))"],
            input=json.dumps(payload), text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout, commitment(payload))

    def test_same_public_materials_and_private_truth(self):
        a, b = BookingMarket('GOOD'), BookingMarket('BAD')
        self.assertEqual(a.public_view(), b.public_view())
        self.assertNotIn('buyer_calendar', a.public_view())
        self.assertNotIn('quality', a.public_view())
        public = a.public_view()
        self.assertEqual(booking_oracle(public, calendar_record('GOOD'))['status'], 'PASS')
        bad = booking_oracle(public, calendar_record('BAD'))
        self.assertEqual(bad['status'], 'FAIL')
        self.assertEqual(bad['conflicts'], [{'attendee': 'agent_0', 'meeting_id': 'MTG-1', 'slot': 0}])
        public['attendance'].clear()
        self.assertTrue(a.public_view()['attendance'])
    def test_booking_oracle_validates_calendar_and_schedule(self):
        public = BookingMarket('GOOD').public_view()
        for calendar in ({'unavailable_slots': {}},
                         {'unavailable_slots': {'agent_0': [True], 'agent_1': []}},
                         {'unavailable_slots': {'agent_0': [10], 'agent_1': []}}):
            with self.assertRaises(ValueError):
                booking_oracle(public, calendar)
        public['attendance']['agent_0']['MTG-1'] = -1
        with self.assertRaises(ValueError):
            booking_oracle(public, calendar_record('GOOD'))
        with self.assertRaises(ValueError):
            calendar_record('unknown')
    def test_honest_checks_and_retained_optional_bonus(self):
        for quality, expected in [('GOOD', 'ACCEPT'), ('BAD', 'REJECT')]:
            market = BookingMarket(quality)
            with self.assertRaises(ValueError):
                market.check('auditor')
            market.propose('provider', 10000, 20000)
            market.accept('auditor')
            self.assertEqual(market.check('auditor')['charged_units'], 1)
            self.assertEqual(market.check('auditor')['charged_units'], 0)
            market.decide('auditor', expected)
            row = market.export()
            self.assertFalse(row['false_approval'])
            self.assertEqual(row['internal_service_due_atomic'], 30000 if quality == 'GOOD' else 10000)
            with self.assertRaises(ValueError):
                market.check('auditor')
        market = BookingMarket('BAD', condition='COERCIVE_STRESS')
        market.propose('provider', 10000, 0); market.accept('auditor')
        with self.assertRaisesRegex(ValueError, 'COERCIVE_STRESS'):
            market.check('auditor')
        with self.assertRaises(ValueError):
            BookingMarket('GOOD').export()
    def test_native_config_and_missing_setup_fail_before_signing(self):
        for endpoint in ('https://example.com', 'http://192.168.1.1', 'http://127.0.0.1@evil.example'):
            with self.assertRaises(ValueError):
                NativeMeetingService(Path('/tmp/config-test-only'), rpc_url=endpoint)
        with self.assertRaises(ValueError):
            NativeMeetingService(Path('relative'))
        with tempfile.TemporaryDirectory(dir='/tmp') as temp:
            service = NativeMeetingService(Path(temp))
            with self.assertRaisesRegex(ValueError, 'prepare'):
                native_service_orbit('BAD', service=service)
            with self.assertRaises(Exception):
                asyncio.run(service.verify({'path': str(Path(temp) / 'absent.json'),
                                           'sha256': '0' * 64, 'operation': 'check'}))
        with self.assertRaises(ValueError):
            open_mpp_orbit('BAD', tool_overrides={'market_view': object()})


if __name__ == '__main__':
    unittest.main()
