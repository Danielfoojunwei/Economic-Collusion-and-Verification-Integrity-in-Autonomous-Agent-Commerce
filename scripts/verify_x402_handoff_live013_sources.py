#!/usr/bin/env python3
"""Read-only x402 013 source and USD-50 budget preview; never freezes a row."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402
from agent_economic_trust.x402_handoff_live013_plan import (  # noqa: E402
    BAD_SOURCE, GOOD_SOURCE, SourceReadinessError, _source, budget_quote,
    make_schedule, verified_sources)
from agent_economic_trust.x402_live012_plan import CANONICAL_LEDGER  # noqa: E402


def readiness() -> dict:
    ledger = BudgetLedger(CANONICAL_LEDGER).snapshot()
    result = {"schema": "x402-handoff-live013-source-readiness-v1",
              "status": "BLOCKED", "paid_model_calls": 0,
              "new_native_transactions": 0,
              "assignment_frozen": False, "ledger_reserved": False,
              "bad_source_path": str(BAD_SOURCE.relative_to(ROOT)),
              "good_source_path": str(GOOD_SOURCE.relative_to(ROOT)),
              "ledger_seq": ledger["seq"], "ledger_cap_usd": ledger["cap_usd"],
              "ledger_available_usd": ledger["available_usd"],
              "ledger_unknown_run_ids": ledger["unknown_run_ids"]}
    try:
        bad = _source("bad", BAD_SOURCE)
        result["bad_source_status"] = "INDEPENDENTLY_REPLAYED"
        result["bad_source_report_digest"] = bad.report_digest
    except SourceReadinessError as exc:
        result["blocker"] = str(exc)
        return result
    try:
        sources = verified_sources()
    except SourceReadinessError as exc:
        result["blocker"] = str(exc)
        return result
    # Fixed preview seed is a test vector, not an assignment seed. This never
    # creates a frozen manifest or a budget reservation.
    rows = make_schedule("00" * 32, sources)
    result["source_status"] = "BOTH_MATCHED_LOCAL_RECEIPTS_REPLAYED"
    try:
        prior = json.loads((ROOT / "artifacts/gates/ERC8183_PRESSURE016/assignment-001/"
                           "assignment_manifest.json").read_text())
        prices = prior["public_pricing_snapshot"]
        quote = budget_quote(prices, rows)
        result["historical_price_quote_not_spend_clearance"] = quote
        if (ledger["cap_usd"] != "50" or ledger["blocked"]
                or ledger["unknown_run_ids"] or
                Decimal(ledger["available_usd"]) < Decimal(quote["required_headroom_usd"])):
            result["blocker"] = "full prospective block has no conservative USD50 spend clearance"
            return result
    except Exception as exc:
        result["blocker"] = f"current model price preview unavailable: {exc}"
        return result
    result["status"] = "SOURCES_AND_HISTORICAL_HEADROOM_PREVIEW_PASS_NOT_SPEND_CLEARANCE"
    result["blocker"] = "live ORBIT task, raw collector, independent source review, freeze and GO not implemented"
    return result


if __name__ == "__main__":
    print(json.dumps(readiness(), indent=2, sort_keys=True))
