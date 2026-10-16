import unittest
from paidaudit.tasks import make_tasks
from paidaudit.protocols import PROTOCOLS, Session
from paidaudit.model import ProtocolViolation, Judgment
from paidaudit.runtime import make_condition, run_trial

class TestAllLocalProtocolAdapters(unittest.TestCase):
    def setUp(self):
        self.task=make_tasks()[0]

    def test_all_adapters_have_distinct_source_and_run(self):
        self.assertGreaterEqual(len(PROTOCOLS),10)
        for name,p in PROTOCOLS.items():
            with self.subTest(protocol=name):
                self.assertTrue(p.source.startswith("https://"))
                r=run_trial(name,self.task,make_condition("baseline","good"),"truthful","none")
                self.assertTrue(r.work_submitted)
                self.assertTrue(r.paid)
                self.assertFalse(r.wrong_payment)
                self.assertGreater(r.event_count,5)
                self.assertIn("simulation",r.fidelity)

    def test_no_native_semantic_truth_guarantee(self):
        for name,p in PROTOCOLS.items():
            with self.subTest(protocol=name):
                # Auditors are explicitly compromised: guaranteed false ACCEPT.
                c=make_condition("provider_dependence","bad")
                r=run_trial(name,self.task,c,"captured","none")
                self.assertTrue(r.verdict)
                self.assertTrue(r.wrong_payment, "evaluator-approved bad work pays in this model")

    def test_independent_recheck_escrow_and_x402(self):
        for name,p in PROTOCOLS.items():
            r=run_trial(name,self.task,make_condition("provider_dependence","bad"),
                        "captured","objective_recheck")
            if p.payment_stage in ("after_service","on_evaluator_approval"):
                self.assertFalse(r.wrong_payment,name)
            else:
                self.assertTrue(r.wrong_payment, "cannot undo a prior purchase")

    def test_incorrect_payee_or_amount_does_not_charge(self):
        for name in PROTOCOLS:
            for fault in ("payee_tamper","amount_tamper"):
                r=run_trial(name,self.task,make_condition(fault,"good"),"truthful","none")
                with self.subTest(protocol=name,scenario=fault):
                    self.assertFalse(r.paid)
                    self.assertTrue(r.blocked)
                    self.assertFalse(r.work_submitted)
                    self.assertFalse(r.good_work_unpaid)

    def test_deadline_expiry_no_payment(self):
        for name in PROTOCOLS:
            r=run_trial(name,self.task,make_condition("deadline_expiry","good"),"truthful","none")
            with self.subTest(protocol=name):
                self.assertTrue(r.blocked)
                self.assertFalse(r.paid)

    def test_mock_nonce_replay_never_pays_twice(self):
        for name in PROTOCOLS:
            r=run_trial(name,self.task,make_condition("nonce_replay","good"),"truthful","none")
            with self.subTest(protocol=name):
                self.assertTrue(r.paid)
                self.assertTrue(any(e["action"]=="REPLAY_BLOCKED_BY_LEDGER" for e in r.trace))

    def test_escrow_refunds_on_rejection(self):
        for name,p in PROTOCOLS.items():
            if p.payment_stage!="on_evaluator_approval":continue
            r=run_trial(name,self.task,make_condition("baseline","bad"),"truthful","none")
            self.assertTrue(r.refunded,name)
            self.assertEqual(r.protocol_status,"Rejected")

    def test_role_restrictions_and_double_terminal(self):
        sess=Session("erc8183_draft",self.task,"role-test")
        sess.begin()
        with self.assertRaises(ProtocolViolation): sess.submit(self.task.good_work,caller="client")
        sess.submit(self.task.good_work)
        j=Judgment(verdict=True,performed_check=True,claimed_evidence="harness_private_oracle")
        with self.assertRaises(ProtocolViolation): sess.settle(j,self.task.good_work,caller="provider")
        self.assertEqual(sess.state,"submitted")
        res=sess.settle(j,self.task.good_work,caller="verifier")
        self.assertTrue(res.paid)
        self.assertEqual(sess.ledger.balances["escrow"],0)
        with self.assertRaises(ProtocolViolation):sess.settle(j,self.task.good_work)

    def test_receipt_swap_caught_by_extra_binding(self):
        for name,p in PROTOCOLS.items():
            if p.payment_stage!="on_evaluator_approval":continue
            case=make_condition("receipt_swap","bad")
            baseline=run_trial(name,self.task,case,"truthful","none")
            guarded=run_trial(name,self.task,case,"truthful","objective_recheck")
            self.assertTrue(baseline.wrong_payment,name)
            self.assertFalse(guarded.wrong_payment,name)
            self.assertTrue(any(e["action"]=="OBJECTIVE_RECHECK" for e in guarded.trace))

if __name__=="__main__":unittest.main()
