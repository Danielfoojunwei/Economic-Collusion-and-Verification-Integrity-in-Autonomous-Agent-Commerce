"""Saved-log ORBIT plumbing controls; no model network calls or paid evidence."""
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ['PYTHON_DOTENV_DISABLED'] = '1'
os.environ['XDG_DATA_HOME'] = '/workspace/.local/share'
os.environ['XDG_CACHE_HOME'] = '/workspace/.cache'
os.environ['XDG_CONFIG_HOME'] = '/workspace/.config'

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log
from inspect_ai.model import ModelOutput, get_model
from agent_economic_trust.open_mpp_orbit import (
    OpenMppLogError, dispatch, inspect_open_mpp_log, open_mpp_orbit,
)
from agent_economic_trust.open_mpp_meeting import MeetingMarket, commitment

from agent_economic_trust.open_mpp_smoke import MODEL, scripted_model


class OpenMppOrbitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='open-mpp-orbit-', dir='/tmp')
    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()
    def run_log(self, quality, label, *, checked=True, flow='charge', condition='OPEN', counteroffer=False):
        [log] = inspect_eval(open_mpp_orbit(quality, condition=condition, trial_id=label,
                            scheduler_seconds=60, task_token_limit=15000),
                model=scripted_model(checked=checked, flow=flow, counteroffer=counteroffer),
                log_dir=str(Path(self.temp.name) / label), display='none', log_realtime=False,
                max_retries=0, retry_on_error=0)
        self.assertEqual(log.status, 'success', log.error)
        return read_eval_log(log.location, resolve_attachments=True)
    def test_saved_good_and_bad_checked_and_unchecked_controls(self):
        for quality, checked, flow, verdict, false in [
            ('GOOD', True, 'charge', 'ACCEPT', False),
            ('BAD', True, 'session', 'REJECT', False),
            ('BAD', False, 'charge', 'ACCEPT', True)]:
            log = self.run_log(quality, f'trial-{flow}-{checked}', checked=checked, flow=flow)
            decision = inspect_open_mpp_log(log, quality=quality, expected_model=MODEL)
            self.assertEqual(decision['selected_flow'], flow)
            self.assertEqual(decision['verdict'], verdict)
            self.assertEqual(decision['false_approval'], false)
            self.assertEqual(decision['checked'], checked)
            self.assertEqual(decision['model_execution_tier'], 'SCRIPTED_SIMULATION')
            self.assertEqual(decision['transaction_execution_tier'], 'NOT_EXECUTED')
            self.assertEqual(decision['external_client_payout']['execution_tier'], 'NOT_EXECUTED')
            digest = decision.pop('decision_sha256')
            self.assertEqual(digest, commitment(decision))
    def test_counteroffer_and_coercive_stress_are_separate(self):
        log = self.run_log('BAD', 'counteroffer', counteroffer=True)
        decision = inspect_open_mpp_log(log, quality='BAD', expected_model=MODEL)
        self.assertEqual(decision['terms']['fee_atomic'], 20000)
        self.assertEqual(decision['verdict'], 'REJECT')
        log = self.run_log('BAD', 'stress', checked=False, condition='COERCIVE_STRESS')
        decision = inspect_open_mpp_log(log, quality='BAD', condition='COERCIVE_STRESS', expected_model=MODEL)
        self.assertEqual(decision['condition'], 'COERCIVE_STRESS')
        self.assertFalse(decision['checked'])
    def test_raw_action_truth_store_and_model_tampering_fail(self):
        log = self.run_log('BAD', 'tamper')
        with self.assertRaises(OpenMppLogError):
            inspect_open_mpp_log(log, quality='BAD', expected_model=MODEL, require_real_model=True)
        with self.assertRaises(OpenMppLogError):
            inspect_open_mpp_log(log, quality='GOOD', expected_model=MODEL)
        action = next(e for e in log.samples[0].events if e.event == 'tool' and e.function == 'market_decide')
        action.arguments['verdict'] = 'ACCEPT'
        with self.assertRaisesRegex(OpenMppLogError, 'raw model action'):
            inspect_open_mpp_log(log, quality='BAD', expected_model=MODEL)
    def test_private_payload_and_store_tampering_fail(self):
        log = self.run_log('BAD', 'private-payload')
        event = next(e for e in log.samples[0].events if e.event == 'model')
        event.input[0].content += '\n{"quality":"BAD"}'
        with self.assertRaisesRegex(OpenMppLogError, 'private state'):
            inspect_open_mpp_log(log, quality='BAD', expected_model=MODEL)
        log = self.run_log('BAD', 'private-store')
        log.samples[0].store['OpenMppStore:decision']['selected_flow'] = 'session'
        with self.assertRaisesRegex(OpenMppLogError, 'trusted store'):
            inspect_open_mpp_log(log, quality='BAD', expected_model=MODEL)

    def test_roles_flow_and_blind_trial_id_guard(self):
        market = MeetingMarket('BAD')
        for actor, name, arguments in [('provider', 'market_check', {}),
                ('auditor', 'select_mpp_flow', {'flow': 'charge'}),
                ('intruder', 'market_view', {}),
                ('provider', 'select_mpp_flow', {'flow': 'mainnet'})]:
            with self.assertRaises(ValueError):
                dispatch(market, None, actor, name, arguments)
        with self.assertRaises(ValueError):
            open_mpp_orbit('BAD', trial_id='bad-trial')


if __name__ == '__main__':
    unittest.main()
