"""Static ORBIT task gates; construction never invokes a remote model."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
import unittest

from agent_economic_trust.ap2_live_fixture import invoice_case
from agent_economic_trust.erc8183_fee_plan import SONNET, SOL, make_schedule
from agent_economic_trust.erc8183_fee_task import erc8183_fee_invoice_orbit


def prefix(row) -> dict:
    fixture, artifact = invoice_case(row.truth)
    public = json.dumps({"task_prompt": fixture.public_task()["task_prompt"],
                         "submitted_amount_cents": artifact.submitted_amount_cents},
                        sort_keys=True, separators=(",", ":"))
    native = row.fee_term == "NATIVE_CONTINGENT"
    return {"status": "FUNDED_SUBMITTED", "obligation_id": row.obligation_id,
            "job_id": 1, "job_funding_tx_hash": "0x" + "11" * 32,
            "auditor_endowment_tx_hash": "0x" + "22" * 32,
            "submitted_report_digest": sha256(public.encode()).hexdigest(),
            "client_prepay_tx_hash": None if native else "0x" + "33" * 32,
            "job_budget_minor": 20_000_000 if native else 18_000_000,
            "evaluator_fee_bp": 1000 if native else 0,
            "client_prepay_minor": 0 if native else 2_000_000,
            "prior_settled_amount_minor": 0}


class FeeTaskScaffoldTests(unittest.TestCase):
    def test_two_role_models_equal_public_claim_and_real_no_contact(self) -> None:
        rows = make_schedule("12" * 32)
        by_cell = {}
        for row in rows:
            task = erc8183_fee_invoice_orbit(
                row, native_prefix=prefix(row), native_check=lambda *_: {},
                native_settle=lambda *_: {})
            self.assertEqual(len(task.dataset), 1)
            self.assertEqual(task.config.reasoning_effort, "high")
            self.assertEqual(task.config.reasoning_history, "none")
            self.assertEqual(task.config.max_retries, 0)
            sample = task.dataset[0]
            setup = sample.metadata["experiment"]["setup"]
            agents = {agent["name"]: agent for agent in setup["agents"]}
            self.assertEqual(agents["provider"]["model"], "openrouter/" + SOL)
            self.assertEqual(agents["auditor"]["model"], "openrouter/" + SONNET)
            self.assertIn("report is " + row.truth.upper(), agents["provider"]["system_prompt"])
            self.assertNotIn("report is " + row.truth.upper(), agents["auditor"]["system_prompt"])
            self.assertEqual(agents["provider"]["tools"], ["acknowledge_frozen_invoice"])
            self.assertEqual(set(agents["auditor"]["tools"]),
                             {"view_frozen_invoice", "buy_independent_invoice_check",
                              "issue_fee_invoice_verdict"})
            communication = sample.metadata["experiment"]["communication"]
            self.assertEqual(communication is None, row.contact == "NO_CONTACT")
            if communication is not None:
                self.assertEqual(len(communication["channels"]), 1)
            public = json.loads(sample.input)
            self.assertEqual(public["public_claim_cents"], 350)
            self.assertNotIn("truth", public)
            public.pop("obligation_id")
            by_cell[(row.fee_term, row.contact, row.truth)] = (public,
                agents["auditor"]["system_prompt"])
        for fee in ("NATIVE_CONTINGENT", "CLIENT_PREPAID"):
            for contact in ("CHANNEL", "NO_CONTACT"):
                self.assertEqual(by_cell[(fee, contact, "good")],
                                 by_cell[(fee, contact, "bad")])

    def test_public_native_prefix_rejects_truth_and_prior_claim_leaks(self) -> None:
        row = make_schedule("12" * 32)[0]
        base = prefix(row)
        for mutation in (
            {"prior_settled_amount_minor": 5_000_000},
            {"submitted_report_digest": "0" * 64},
            {"client_prepay_tx_hash": "0x" + "33" * 32 if row.fee_term == "NATIVE_CONTINGENT" else None},
            {"private_truth": row.truth},
        ):
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):
                    erc8183_fee_invoice_orbit(
                        row, native_prefix={**base, **mutation},
                        native_check=lambda *_: {}, native_settle=lambda *_: {})
        with self.assertRaises(ValueError):
            erc8183_fee_invoice_orbit(
                replace(row, auditor_model_id=SOL), native_prefix=base,
                native_check=lambda *_: {}, native_settle=lambda *_: {})


if __name__ == "__main__":
    unittest.main()
