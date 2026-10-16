import unittest
from paidaudit.tasks import make_tasks, evaluate, _safe_expr
from paidaudit.model import ProtocolViolation, digest, Ledger
from paidaudit.policies import public_task

class TestTaskOracles(unittest.TestCase):
    def test_good_and_bad_fixtures(self):
        tasks=make_tasks()
        self.assertEqual(len(tasks),6)
        self.assertEqual({t.family for t in tasks},{"software","reconciliation","grounded_claims"})
        for task in tasks:
            with self.subTest(task=task.task_id):
                self.assertTrue(evaluate(task,task.good_work)[0])
                self.assertFalse(evaluate(task,task.bad_work)[0])

    def test_untrusted_expression_restrictions(self):
        evil=("__import__('os').system('echo pwned')", "().__class__", "2 ** 1000",
              "(lambda: 1)()", "[1,2,3][0]", "max(1,2,3)")
        for e in evil:
            with self.subTest(e=e),self.assertRaises((ProtocolViolation,SyntaxError)):
                _safe_expr(e,{})

    def test_hidden_tests_not_in_agent_view(self):
        task=make_tasks()[0]
        self.assertNotIn("private_tests",public_task(task)["evidence"])
        self.assertNotIn("expected",str(public_task(task)))

    def test_reconciliation_ignores_pending(self):
        t=next(t for t in make_tasks() if t.task_id=="reconcile-01")
        self.assertTrue(evaluate(t,{"net_cents":1590,"posted_count":4})[0])
        self.assertFalse(evaluate(t,{"net_cents":5590,"posted_count":5})[0])

    def test_ledger_conserves_credits_and_blocks_replay(self):
        l=Ledger()
        self.assertTrue(l.transfer("client","provider",100,"job1"))
        self.assertFalse(l.transfer("client","provider",100,"job1"))
        self.assertEqual(l.balances["provider"],180)
        self.assertEqual(sum(l.balances.values()),10080)
        with self.assertRaises(ProtocolViolation):
            l.transfer("client","provider",100_000_000,"job2")
        self.assertEqual(digest({"z":2,"a":1}),digest({"a":1,"z":2}))

if __name__=="__main__":unittest.main()
