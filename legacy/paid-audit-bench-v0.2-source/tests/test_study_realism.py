"""Science and protocol boundary regression tests for v0.2 offline benchmark."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from paidaudit.model import digest, ProtocolViolation
from paidaudit.study_tasks import make_study_tasks
from paidaudit.study import (CASES, GUARDS,prepare_case,replay_guard,run_study)
from paidaudit.study_stats import _block_effect, factorial_estimands, reliability_metrics
from paidaudit.tasks import evaluate
from paidaudit.protocols import PROTOCOLS


class TestRealismStudy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks=make_study_tasks()
        cls.task=cls.tasks[0]

    def test_calibrated_tasks_include_service_receipts(self):
        self.assertEqual(len(self.tasks),10)
        for t in self.tasks:
            self.assertTrue(evaluate(t,t.good_work)[0],t.task_id)
            self.assertFalse(evaluate(t,t.bad_work)[0],t.task_id)
        self.assertIn("procurement",{t.family for t in self.tasks})
        self.assertIn("api_service",{t.family for t in self.tasks})

    def test_frozen_replay_not_resampling_policy(self):
        f=prepare_case(self.task,"mixed_influence","bad","economic",8)
        outcomes=[replay_guard(f,"erc8183_draft",g) for g in GUARDS]
        self.assertEqual(len({x['decision_digest'] for x in outcomes}),1)
        self.assertEqual(len({x['request_digest'] for x in outcomes}),1)
        self.assertEqual(len({x['original_audit_approve'] for x in outcomes}),1)
        self.assertEqual(len({x['original_audit_checked'] for x in outcomes}),1)
        self.assertEqual(len({x['trace_hash'] for x in outcomes}),len(GUARDS))
        for x in outcomes:
            self.assertEqual(digest({'trial':x['trial_id'],'events':x['trace']}),x['trace_hash'])
            self.assertTrue(x['simulator_only'])
            self.assertFalse(x['actual_sdk_used'])

    def test_hash_only_does_not_prove_quality(self):
        f=prepare_case(self.task,"mixed_influence","bad","captured",4)
        # Give auditor a conscious incentive positive control, not independent truth.
        # A matching commitment can still sign a semantically false artifact.
        x=replay_guard(f,'erc8183_draft','receipt_binding')
        self.assertTrue(x['original_audit_approve'])  # must use relationship to prompt captured

    def test_swap_has_no_model_misjudgment(self):
        f=prepare_case(self.task,"deliverable_swap","bad","truthful",1)
        self.assertTrue(evaluate(f.task,f.submitted)[0])
        self.assertFalse(evaluate(f.task,f.delivered)[0])
        for protocol in ("erc8183_draft","x402_v2","mpp"):
            none=replay_guard(f,protocol,'none')
            binding=replay_guard(f,protocol,'receipt_binding')
            self.assertFalse(none['semantic_misjudgment'])
            self.assertTrue(none['improper_payment'])
            self.assertEqual(binding['original_audit_approve'],none['original_audit_approve'])
            if protocol!='mpp':
                self.assertFalse(binding['improper_payment'])
            else:
                self.assertTrue(binding['improper_payment'])

    def test_x402_response_follows_settlement(self):
        f=prepare_case(self.task,'baseline','good','truthful',1)
        x=replay_guard(f,'x402_v2','none')
        a=[event['action'] for event in x['trace']]
        self.assertIn('RESOURCE_HANDLER_COMPLETED',a)
        self.assertIn('HTTP_200_resource_response',a)
        self.assertLess(a.index('RESOURCE_HANDLER_COMPLETED'),a.index('settle'))
        self.assertLess(a.index('settle'),a.index('HTTP_200_resource_response'))

    def test_distinct_job_duplicate_vs_nonce_replay(self):
        task=self.task
        duplicate=prepare_case(task,'duplicate_job','good','truthful',1)
        no=replay_guard(duplicate,'erc8183_draft','none')
        dedupe=replay_guard(duplicate,'erc8183_draft','obligation_dedupe')
        self.assertGreater(no['extra_duplicate_charge_credits'],0)
        self.assertEqual(dedupe['extra_duplicate_charge_credits'],0)
        self.assertTrue(any(e['action']=='SECOND_VALID_PAYMENT_FOR_SAME_JOB' for e in no['trace']))
        self.assertTrue(any(e['action']=='DUPLICATE_OBLIGATION_BLOCKED' for e in dedupe['trace']))
        replay=replay_guard(prepare_case(task,'payment_replay','good','truthful',1),'erc8183_draft','none')
        self.assertTrue(any(e['action']=='REPLAY_BLOCKED_BY_LEDGER' for e in replay['trace']))
        self.assertEqual(replay['extra_duplicate_charge_credits'],0)

    def test_aborted_work_no_delivery_and_separate_refund(self):
        f=prepare_case(self.task,'provider_aborts','good','truthful',1)
        escrow=replay_guard(f,'erc8183_draft','none')
        checkout=replay_guard(f,'mpp','none')
        self.assertFalse(escrow['deliverable_submitted'])
        self.assertFalse(escrow['provider_paid'])
        self.assertTrue(escrow['refunded'])
        self.assertTrue(checkout['provider_paid'])
        self.assertFalse(checkout['refunded'])
        self.assertTrue(checkout['improper_payment'])

    def test_factorial_conditions_are_complete(self):
        names=[n for n in CASES if n.startswith('factor_r')]
        self.assertEqual(len(names),8)
        self.assertEqual(len(set(names)),8)
        v={(r,s,p):float(r*s*p) for r in (0,1) for s in (0,1) for p in (0,1)}
        self.assertEqual(_block_effect(v,(0,1,2)),1)
        self.assertAlmostEqual(_block_effect(v,(0,)),0.25)

    def test_mock_data_valid_for_every_protocol(self):
        f=prepare_case(self.task,'same_identity_overcharge','good','truthful',3)
        self.assertLessEqual(f.requested_price,f.contract['buyer_spend_cap'])
        for protocol in PROTOCOLS:
            x=replay_guard(f,protocol,'none')
            self.assertGreater(x['overcharge_credits'],0,protocol)
            self.assertTrue(x['provider_paid'])
            self.assertEqual(digest({'trial':x['trial_id'],'events':x['trace']}),x['trace_hash'])

    def test_x402_three_flow_orderings_are_distinct(self):
        f=prepare_case(self.task,'baseline','good','truthful',1)
        def actions(p):return [e['action'] for e in replay_guard(f,p,'none')['trace']]
        base=actions('x402_v2')
        upfront=actions('x402_v2_upfront')
        escrow=actions('x402_v2_escrow')
        self.assertLess(base.index('verify_authorization'),base.index('RESOURCE_HANDLER_COMPLETED'))
        self.assertLess(base.index('RESOURCE_HANDLER_COMPLETED'),base.index('settle'))
        self.assertLess(upfront.index('settle_upfront'),upfront.index('RESOURCE_HANDLER_COMPLETED'))
        self.assertNotIn('verify_authorization',upfront)
        self.assertLess(escrow.index('settle_deposit'),escrow.index('RESOURCE_HANDLER_COMPLETED'))
        self.assertLess(escrow.index('RESOURCE_HANDLER_COMPLETED'),escrow.index('settle'))
        self.assertNotIn('verify_authorization',escrow)

    def test_x402_escrow_refunded_on_timeout(self):
        f=prepare_case(self.task,'provider_aborts','good','truthful',1)
        r=replay_guard(f,'x402_v2_escrow','none')
        self.assertTrue(r['refunded'])
        self.assertFalse(r['provider_paid'])
        self.assertTrue(any(e['action']=='SIMULATED_TIMEOUT_REFUND' for e in r['trace']))

    def test_binding_does_not_prove_semantic_truth(self):
        f=prepare_case(self.task,'mixed_influence','bad','captured',1)
        plain=replay_guard(f,'erc8183_draft','none')
        bound=replay_guard(f,'erc8183_draft','receipt_binding')
        self.assertTrue(plain['original_audit_approve'])
        self.assertFalse(plain['independently_verified_ground_truth'])
        self.assertTrue(bound['improper_payment'], 'consistent digest is not an objective correctness proof')
        self.assertTrue(any(e['action']=='RECEIPT_HASH_CHECK' and e['detail']['matched']
                            for e in bound['trace']))

    def test_small_end_to_end_study_validated(self):
        config={'protocols':['erc8183_draft','x402_v2'],
                'scenarios':['factor_r0_s0_p0','factor_r0_s0_p1','factor_r0_s1_p0','factor_r0_s1_p1',
                             'factor_r1_s0_p0','factor_r1_s0_p1','factor_r1_s1_p0','factor_r1_s1_p1'],
                'guards':['none','receipt_binding'],'policies':['truthful'],
                'qualities':['good','bad'],'tasks':[self.task.task_id], 'seeds':2}
        with tempfile.TemporaryDirectory() as d:
            m=run_study(config,Path(d))
            self.assertEqual(m['trial_count'],2*8*2*1*2*1*2)
            from csv import DictReader
            with (Path(d)/'factorial_effects.csv').open() as f:
                effects=list(DictReader(f))
            self.assertTrue(effects)
            with (Path(d)/'reliability.csv').open() as f:
                rel=list(DictReader(f))
            self.assertTrue(any(r['k']=='2' for r in rel))
            with (Path(d)/'trials.jsonl').open() as f:
                rows=[json.loads(x) for x in f]
            self.assertEqual(len(rows),m['trial_count'])
            self.assertTrue(all(digest({'trial':x['trial_id'],'events':x['trace']})==x['trace_hash'] for x in rows))
            self.assertFalse(any(x['actual_sdk_used'] for x in rows))

if __name__=='__main__':unittest.main()
