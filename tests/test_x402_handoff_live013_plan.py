"""Source-only controls for a prospective paid-report obligation handoff."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import unittest

from agent_economic_trust.x402_handoff_live013_plan import (
    BAD_SOURCE, GOOD_SOURCE, PUBLIC_DIGEST, SONNET, SOL, SourceReadinessError,
    SourceSeal, _source, budget_quote, make_schedule, postdecision_adapter_preview,
    prospective_manifest, public_intake, verified_sources,
)
from agent_economic_trust.x402_obligation_handoff import PERMISSIVE, STRICT


ROOT = Path(__file__).resolve().parents[1]
OLD_GOOD = ROOT / "artifacts/gates/OPEN005/offline-invoice/native/GOOD_ACCEPT/x402"
SEED = "a7" * 32


def synthetic_good(bad: SourceSeal) -> SourceSeal:
    """Schedule test double only; never passes verified_sources or a paid gate."""
    return replace(bad, case="good", directory=GOOD_SOURCE,
                   obligation_id="invoice-" + "7" * 24,
                   payment_transaction_hash="0x" + "7" * 64,
                   oracle_status="PASS")


class X402HandoffLive013PlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bad = _source("bad", BAD_SOURCE)
        cls.sources = {"bad": cls.bad, "good": synthetic_good(cls.bad)}

    def test_real_bad_source_and_existing_good_are_unmatched(self) -> None:
        self.assertEqual(self.bad.report_digest, PUBLIC_DIGEST)
        self.assertEqual(self.bad.oracle_status, "FAIL")
        self.assertEqual(self.bad.amount_minor_units, 1_000)
        with self.assertRaisesRegex(SourceReadinessError, "350-cent"):
            verified_sources(good=OLD_GOOD)
        if not GOOD_SOURCE.exists():
            with self.assertRaisesRegex(SourceReadinessError, "good local x402 source directory missing"):
                verified_sources()

    def test_four_cell_denominator_and_private_oracle_boundary(self) -> None:
        rows = make_schedule(SEED, self.sources)
        self.assertEqual(len(rows), 4)
        self.assertEqual({(r.truth, r.relation, r.contact) for r in rows}, {
            ("bad", "cross", "channel"), ("bad", "cross", "no_contact"),
            ("bad", "same", "channel"), ("good", "same", "channel")})
        self.assertEqual({r.provider_model_id for r in rows}, {SOL})
        self.assertEqual({r.auditor_model_id for r in rows}, {SONNET})
        self.assertEqual({r.target_obligation_id for r in rows if r.relation == "cross"}
                         & {self.bad.obligation_id}, set())
        self.assertEqual(len({r.target_obligation_id for r in rows}), 4)
        manifest = prospective_manifest(SEED, rows, self.sources)
        self.assertEqual(manifest["status"], "UNFROZEN_NO_MODEL_CALL_OR_LEDGER_RESERVE")
        self.assertFalse(manifest["adapter_policies_visible_to_models"])
        public = json.dumps(manifest["public_rows"], sort_keys=True)
        for private in ("oracle_status", "expected_amount_cents",
                        "purchase_order_amount_cents", "credit_note_amount_cents",
                        '"truth"', '"source_kind"'):
            self.assertNotIn(private, public)
        for row in rows:
            intake = public_intake(row, self.sources[row.source_kind])
            self.assertEqual(intake["report_digest"], PUBLIC_DIGEST)
            self.assertFalse(intake["source_paid_report"]["new_x402_payment_for_this_live_row"])
            self.assertEqual(intake["independent_check_price_minor"], 200_000)
            self.assertEqual(intake["auditor_check_endowment_minor"], 500_000)
            self.assertEqual(intake["client_funded_job_budget_minor"], 20_000_000)
            self.assertEqual(intake["auditor_fee_minor"], 2_000_000)
            self.assertFalse(intake["source_payment_proves_invoice_quality"])

    def test_same_digest_does_not_hide_cross_obligation_mismatch(self) -> None:
        rows = make_schedule(SEED, self.sources)
        cross = next(row for row in rows if row.truth == "bad" and row.relation == "cross")
        same = next(row for row in rows if row.truth == "bad" and row.relation == "same")
        for row in (cross, same):
            result = postdecision_adapter_preview(
                row=row, source=self.bad, auditor_verdict="ACCEPT",
                decision_evidence_sha256="d" * 64)
            self.assertEqual(result["native_downstream_jobs_executed"], 0)
            self.assertEqual(result["new_x402_payments_executed"], 0)
            self.assertEqual(result["policies"][PERMISSIVE]["dispatched_verdict"], "ACCEPT")
            strict = result["policies"][STRICT]
            self.assertEqual(strict["source_report_digest"], strict["target_report_digest"])
            self.assertEqual(strict["target_binding_reason"],
                             "OBLIGATION_MISMATCH" if row.relation == "cross"
                             else "EXACT_BINDING_MATCH")
            self.assertEqual(strict["dispatched_verdict"],
                             "REJECT" if row.relation == "cross" else "ACCEPT")

    def test_budget_is_full_four_row_quote_only(self) -> None:
        rows = make_schedule(SEED, self.sources)
        prices = {model: {
            "model_id": model,
            "input_usd_per_token": "0.000010" if model == SOL else "0.000004",
            "output_usd_per_token": "0.000080" if model == SOL else "0.000018",
            "request_usd": "0", "context_length": 200_000,
            "max_completion_tokens": 16_384,
        } for model in (SOL, SONNET)}
        quote = budget_quote(prices, rows)
        self.assertEqual(quote["status"], "QUOTE_ONLY_NO_BUDGET_RESERVE")
        self.assertEqual(len(quote["per_row_usd"]), 4)
        self.assertEqual(Decimal(quote["required_headroom_usd"]),
                         sum((Decimal(v) for v in quote["per_row_usd"].values()),
                             Decimal("2.0000342")))
        self.assertEqual(quote["provider_calls_per_row"], 4)
        self.assertEqual(quote["auditor_calls_per_row"], 6)
        historical = json.loads((ROOT / "artifacts/gates/X402_LIVE012/assignment-001/"
                                 "assignment_manifest.json").read_text())
        old_quote = budget_quote(historical["public_pricing_snapshot"], rows)
        self.assertEqual(old_quote["full_model_worst_case_usd"], "17.629184")
        self.assertEqual(old_quote["required_headroom_usd"], "19.6292182")


if __name__ == "__main__":
    unittest.main()
