import tempfile
import unittest
from pathlib import Path
from paidaudit.tasks import make_tasks
from paidaudit.protocols import PROTOCOLS
from paidaudit.runtime import make_condition, run_trial, SCENARIOS
from paidaudit.policies import stable_seed,local_llm_verdict
from paidaudit.model import ProtocolViolation, digest
from paidaudit.market import select_roles,run_market
from paidaudit.cli import main

class TestExperiments(unittest.TestCase):
    def setUp(self):self.t=make_tasks()[0]

    def test_determinism(self):
        c=make_condition("mixed_pressure","bad")
        x=run_trial("erc8183_draft",self.t,c,"economic","none",seed=15)
        y=run_trial("erc8183_draft",self.t,c,"economic","none",seed=15)
        self.assertEqual(x.trace_hash,y.trace_hash)
        self.assertEqual(x.wrong_payment,y.wrong_payment)

    def test_matched_policy_across_protocol_adapters(self):
        c=make_condition("provider_dependence","bad")
        a=run_trial("erc8183_draft",self.t,c,"economic","none",seed=8)
        b=run_trial("x402_v2",self.t,c,"economic","none",seed=8)
        self.assertEqual(a.verdict,b.verdict)
        self.assertEqual(a.checks,b.checks)

    def test_scarcity_still_permits_verification(self):
        c=make_condition("scarce_audit","bad")
        self.assertEqual(c.budget,c.check_cost)
        r=run_trial("erc8183_draft",self.t,c,"truthful","none")
        self.assertEqual(r.checks,1)
        self.assertFalse(r.paid)

    def test_unaffordable_audit_is_explicit_negative_control(self):
        c=make_condition("unaffordable_audit","bad")
        self.assertLess(c.budget,c.check_cost)
        r=run_trial("erc8183_draft",self.t,c,"truthful","none")
        self.assertEqual(r.checks,0)
        self.assertFalse(r.paid)

    def test_authentic_side_payment_executes_only_on_accept(self):
        c=make_condition("authenticated_offer","good")
        r=run_trial("mpp",self.t,c,"truthful","none")
        self.assertTrue(r.side_payment)
        self.assertTrue(any(e["action"]=="SANDBOX_SIDE_PAYMENT" for e in r.trace))

    def test_spoofed_offer_does_not_transfer(self):
        r=run_trial("mpp",self.t,make_condition("spoofed_offer","good"),"truthful","none")
        self.assertFalse(r.side_payment)
        self.assertTrue(any(e["action"]=="SPOOFED_OFFER_NOT_PAID" for e in r.trace))

    def test_three_auditors_are_aggregated(self):
        r=run_trial("erc8183_draft",self.t,make_condition("committee_3","good"),"truthful","none")
        self.assertEqual(r.checks,3)
        self.assertTrue(r.verdict)
        self.assertTrue(any(e["action"]=="AGGREGATE_VOTE" for e in r.trace))

    def test_local_model_endpoint_does_not_allow_cloud(self):
        with self.assertRaises(ProtocolViolation):
            local_llm_verdict(self.t,self.t.good_work,make_condition("baseline","good"),
                              8,"testmodel","https://api.openai.com/v1/chat/completions")

    def test_market_reciprocal_edges_emerge(self):
        self.assertEqual(select_roles("reciprocal",1),("agent-A","agent-B"))
        self.assertEqual(select_roles("reciprocal",2),("agent-B","agent-A"))
        rows,graph=run_market("erc8183_draft",policy="captured",pattern="reciprocal",episodes=4)
        self.assertTrue(rows[1]["market_meta"]["relationship_emerged_from_prior_transfers"])
        self.assertGreater(graph["agent-A->agent-B"]["credits"],0)
        self.assertGreater(graph["agent-B->agent-A"]["credits"],0)

    def test_paired_randomness_identical_across_treatments(self):
        self.assertEqual(stable_seed(1,"task",2,"verifier"),stable_seed(1,"task",2,"verifier"))

    def test_cli_generation_and_verify(self):
        with tempfile.TemporaryDirectory() as d:
            main(["run","--out",d,"--protocols","erc8183_draft,mpp",
                  "--tasks","code-tax-01","--scenarios","baseline,mixed_pressure",
                  "--seeds","1","--policies","truthful","--guards","none"])
            self.assertTrue((Path(d)/"trials.jsonl").exists())
            self.assertTrue((Path(d)/"summary.csv").exists())
            self.assertTrue((Path(d)/"manifest.json").exists())
            main(["verify-log",str(Path(d)/"trials.jsonl")])

if __name__=="__main__":unittest.main()
