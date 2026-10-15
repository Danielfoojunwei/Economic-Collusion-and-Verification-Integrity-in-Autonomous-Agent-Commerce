"""Prospective partial-claim row and worst-case budget bounds."""

import ast
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import partial014_freeze
from scripts.partial014_freeze import ROOT, source_names
from agent_economic_trust.partial014_budget import (
    FEE014_FULL_HOLD_USD, FEE014_PROVISIONAL_EVIDENCE_REF,
    FEE014_STOPPED_RUN_ID, exact_prior_holds)
from agent_economic_trust.remote_budget import BudgetLedger
from agent_economic_trust.x402_live012_budget import BASE_HOLDS_USD
from agent_economic_trust.partial014_plan import (
    CANONICAL_LEDGER, CLIENT_PREPAID, NATIVE_CONTINGENT, SOL, SONNET, ROWS,
    full_block_headroom, make_schedule, per_row_reserve, terms, validate_rows)


def sample_catalog():
    common = {"context_length": 1_000_000, "max_completion_tokens": 128_000,
              "request_usd": "0"}
    return {SOL: {**common, "model_id": SOL, "input_usd_per_token": "0.00001",
                  "output_usd_per_token": "0.00003"},
            SONNET: {**common, "model_id": SONNET,
                     "input_usd_per_token": "0.000004",
                     "output_usd_per_token": "0.00001"}}


class PartialClaimPlanTests(unittest.TestCase):
    def test_post_freeze_source_inventory_is_fixed_and_detects_original_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "sealed.py"
            original.write_text("value = 1\n")
            with patch.object(partial014_freeze, "ROOT", root):
                sealed = {"sealed.py": partial014_freeze.sha(original)}
                (root / "later_billing.py").write_text("value = 2\n")
                self.assertEqual(partial014_freeze.frozen_source_inventory(sealed), sealed)
                original.write_text("value = 3\n")
                self.assertNotEqual(partial014_freeze.frozen_source_inventory(sealed), sealed)

    def test_fee014_frozen_first_stop_and_billing_replay(self):
        """Clearance replays actual archived row bytes and reviewed hold proof."""
        from scripts import fee014_freeze, verify_erc8183_fee_control as controls
        from agent_economic_trust import erc8183_fee_native_verifier as native
        from agent_economic_trust.mpp005_plan import canonical_project_root
        state = BudgetLedger(CANONICAL_LEDGER).snapshot()
        canonical = canonical_project_root()
        with (patch.object(fee014_freeze, "_canonical_root", lambda: None),
              patch.object(controls, "UPSTREAM", canonical.parent / "upstreams/erc8183"),
              patch.object(native, "ROOT", canonical)):
            result = partial014_freeze._fee014_predecessor(state)
            self.assertEqual(result["row_statuses"],
                             ["COMPLETE", "STOPPED", "PENDING", "PENDING", "PENDING"])
            self.assertEqual(result["stopped_charge_disposition"]["fee014_charge_status"],
                             "CONTINGENT")
            with patch.object(partial014_freeze, "FEE014_BILLING_REVIEW",
                              partial014_freeze.FEE014_BILLING):
                with self.assertRaises(ValueError):
                    partial014_freeze._fee014_predecessor(state)

    def test_fee014_unknown_blocks_and_full_hold_or_bill_is_required(self):
        original = BudgetLedger(CANONICAL_LEDGER).snapshot()
        base = deepcopy(original)
        run = base["runs"][FEE014_STOPPED_RUN_ID]
        run["status"] = "UNKNOWN"
        base["blocked"] = True
        base["unknown_run_ids"] = [FEE014_STOPPED_RUN_ID]
        with self.assertRaises(ValueError):
            exact_prior_holds(base)
        base["blocked"] = False
        base["unknown_run_ids"] = []
        run["status"] = "CONTINGENT"
        run["evidence_ref"] = FEE014_PROVISIONAL_EVIDENCE_REF
        run["contingent_evidence_ref"] = run["evidence_ref"]
        run.pop("actual_usd", None)
        base["contingent_run_ids"] = sorted(set(base["contingent_run_ids"])
                                            | {FEE014_STOPPED_RUN_ID})
        base["reserved_usd"] = str(BASE_HOLDS_USD + FEE014_FULL_HOLD_USD)
        self.assertEqual(exact_prior_holds(base)["fee014_charge_status"],
                         "CONTINGENT")
        unreviewed = deepcopy(base)
        unreviewed["runs"][FEE014_STOPPED_RUN_ID]["evidence_ref"] = "sha256:" + "1" * 64
        with self.assertRaises(ValueError):
            exact_prior_holds(unreviewed)
        underheld = deepcopy(base)
        underheld["reserved_usd"] = str(BASE_HOLDS_USD)
        with self.assertRaises(ValueError):
            exact_prior_holds(underheld)
        settled = deepcopy(base)
        fee = settled["runs"][FEE014_STOPPED_RUN_ID]
        fee["status"] = "SETTLED"
        fee["actual_usd"] = "0.12"
        fee["evidence_ref"] = "provider-billing:sha256:" + "2" * 64
        settled["contingent_run_ids"].remove(FEE014_STOPPED_RUN_ID)
        settled["reserved_usd"] = str(BASE_HOLDS_USD)
        with self.assertRaises(ValueError):
            exact_prior_holds(settled)

    def test_source_seal_covers_local_transitive_python_imports(self):
        """A local imported module can change the prompt or receipt verifier."""
        sealed = set(source_names())

        def local_path(module: str):
            if module.startswith("agent_economic_trust."):
                return ROOT / "src/agent_economic_trust" / (
                    module.removeprefix("agent_economic_trust.").replace(".", "/") + ".py")
            if module.startswith(("scripts.", "tests.")):
                return ROOT / (module.replace(".", "/") + ".py")
            return None

        missing = set()
        for relative in sealed:
            if not relative.endswith(".py"):
                continue
            path = ROOT / relative
            package = path.parent.name
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Import):
                    candidates = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    base = ((package + "." + (node.module or "")) if node.level
                            else (node.module or ""))
                    candidates = [base, *(base + "." + alias.name
                                          for alias in node.names)]
                else:
                    continue
                for module in candidates:
                    target = local_path(module)
                    if target is not None and target.is_file():
                        name = str(target.relative_to(ROOT))
                        if name not in sealed:
                            missing.add(name)
        self.assertEqual(missing, set())

    def test_five_row_bad_factorial_and_one_native_good_anchor(self):
        rows = make_schedule("a7" * 32)
        self.assertEqual(len(rows), ROWS)
        self.assertEqual([r.truth for r in rows], ["bad"] * 4 + ["good"])
        self.assertEqual({(r.fee_term, r.contact) for r in rows[:4]},
                         {(f, c) for f in (NATIVE_CONTINGENT, CLIENT_PREPAID)
                          for c in ("CHANNEL", "NO_CONTACT")})
        self.assertEqual((rows[-1].fee_term, rows[-1].contact),
                         (NATIVE_CONTINGENT, "NO_CONTACT"))
        self.assertNotEqual(make_schedule("a7" * 32), make_schedule("b8" * 32))
        with self.assertRaises(ValueError):
            validate_rows((*rows[:4], replace(rows[-1], fee_term=CLIENT_PREPAID)))

    def test_native_interim_and_full_payment_terms(self):
        rows = make_schedule("a7" * 32)
        native = terms(next(r for r in rows if r.fee_term == NATIVE_CONTINGENT))
        prepaid = terms(next(r for r in rows if r.fee_term == CLIENT_PREPAID))
        self.assertEqual(native["claim_cumulative_minor"], 10_000_000)
        self.assertEqual(prepaid["claim_cumulative_minor"], 9_000_000)
        self.assertEqual(native["provider_interim_payout_minor"],
                         prepaid["provider_interim_payout_minor"])
        self.assertEqual(native["claim_cumulative_minor"],
                         native["provider_interim_payout_minor"] +
                         native["evaluator_interim_native_fee_minor"])
        self.assertEqual(native["provider_full_accept_payout_minor"],
                         prepaid["provider_full_accept_payout_minor"])

    def test_historical_price_preview_and_negative_catalog(self):
        prices = sample_catalog()
        self.assertEqual(per_row_reserve(prices), Decimal("3.981312"))
        self.assertEqual(full_block_headroom(prices), Decimal("21.9065942"))
        with self.assertRaises(ValueError):
            per_row_reserve({SOL: prices[SOL]})
        with self.assertRaises(ValueError):
            per_row_reserve({**prices, SONNET: {**prices[SONNET],
                                                "input_usd_per_token": "NaN"}})
        with self.assertRaises(ValueError):
            per_row_reserve({**prices, SOL: {**prices[SOL], "context_length": 100}})


if __name__ == "__main__":
    unittest.main()
