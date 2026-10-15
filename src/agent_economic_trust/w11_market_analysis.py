"""Read-only W11 intent-to-treat denominators, including unrun markets."""

from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
from typing import Any

from .remote_budget import BudgetLedger
from .remote import PROJECT_LEDGER_PATH
from .w11_market_plan import ARMS
from .w11_market_remote import _episode_dir, _load_plan, _load_prior_entries, _market_rows


def collect_market_itt(plan_dir: Path, runs_dir: Path) -> dict[str, Any]:
    """Keep randomized market/round denominators and bound missing outcomes."""
    frozen, assignment_sha, rows = _load_plan(plan_dir)
    ledger = BudgetLedger(PROJECT_LEDGER_PATH).snapshot()
    order = frozen["market_execution_order"]
    if set(order) != {row.market_id for row in rows} or len(order) != 12 * len({row.block_id for row in rows}):
        raise ValueError("frozen market order differs from assigned markets")
    markets = []
    completed_records: dict[str, dict] = {}
    for market_id in order:
        market_rows = _market_rows(rows, market_id)
        flags = [(_episode_dir(runs_dir, row) / "episode_record.json").is_file()
                 for row in market_rows]
        completed = next((i for i, flag in enumerate(flags) if not flag), len(flags))
        if any(flags[completed:]):
            raise ValueError("market has a gap after an incomplete assigned round")
        verified = _load_prior_entries(
            market_rows, completed, runs_dir, assignment_sha, ledger,
            frozen["source_sha256"],
        )
        if len(verified) != completed:
            raise ValueError("complete market record was not independently reverified")
        for row in market_rows[:completed]:
            record = json.loads((_episode_dir(runs_dir, row) / "episode_record.json").read_bytes())
            completed_records[row.episode_id] = record
        stopped = any((_episode_dir(runs_dir, row) / "STOPPED.json").is_file()
                      for row in market_rows[completed:])
        status = "COMPLETE" if completed == len(market_rows) else (
            "FAILED_OR_INCOMPLETE" if stopped else "PENDING"
        )
        markets.append({"market_id": market_id, "arm": market_rows[0].arm,
                        "R": market_rows[0].r, "status": status,
                        "completed_episodes": completed,
                        "pending_or_failed_episodes": len(market_rows) - completed,
                        "assigned_episode_ids": [row.episode_id for row in market_rows]})
    cells: dict[str, Any] = {}
    for arm, r in ((arm, r) for arm in ARMS for r in (0, 1)):
        assigned = [row for row in rows if row.arm == arm and row.r == r]
        bad = [row for row in assigned if row.fixture_id.endswith("-bad")]
        good = [row for row in assigned if row.fixture_id.endswith("-good")]
        observed_bad_paid = sum(completed_records.get(row.episode_id, {}).get("payment_status") == "PAID"
                                for row in bad)
        observed_bad_approved = sum(completed_records.get(row.episode_id, {}).get("verdict") == "ACCEPT"
                                    for row in bad)
        observed_good_unpaid = sum(completed_records.get(row.episode_id, {}).get("payment_status") == "NOT_PAID"
                                   for row in good)
        missing_bad = sum(row.episode_id not in completed_records for row in bad)
        missing_good = sum(row.episode_id not in completed_records for row in good)
        direct_assigned = [row for row in assigned if row.communication_mode == "DIRECT"]
        read_count = sum(completed_records.get(row.episode_id, {}).get("channel_audit", {})
                         .get("assigned_message_read") is True for row in direct_assigned)
        cells[f"{arm}:R{r}"] = {
            "assigned_market_clusters": len({row.market_id for row in assigned}),
            "assigned_episodes": len(assigned),
            "completed_episodes": sum(row.episode_id in completed_records for row in assigned),
            "bad_assigned": len(bad), "good_assigned": len(good),
            "bad_wrong_payment_observed": observed_bad_paid,
            "bad_false_approval_observed": observed_bad_approved,
            "good_legitimate_nonpayment_observed": observed_good_unpaid,
            "bad_missing": missing_bad, "good_missing": missing_good,
            "bad_wrong_payment_itt_bounds": [
                observed_bad_paid / len(bad),
                (observed_bad_paid + missing_bad) / len(bad),
            ],
            "good_nonpayment_itt_bounds": [
                observed_good_unpaid / len(good),
                (observed_good_unpaid + missing_good) / len(good),
            ],
            "direct_access_assigned_episodes": len(direct_assigned),
            "direct_assigned_message_read_observed": read_count,
            "direct_assigned_message_read_unresolved": sum(
                row.episode_id not in completed_records for row in direct_assigned),
        }
    spent = sum((Decimal(record["model_cost_usd_estimate"])
                 for record in completed_records.values()), Decimal("0"))
    return {
        "schema": "w11-market-itt-descriptive-v1",
        "assignment_manifest_sha256": assignment_sha,
        "analysis_unit": "randomized_market_cluster",
        "inference_tier": "DESCRIPTIVE_ONLY",
        "planned_markets": len(order), "planned_episodes": len(rows),
        "completed_markets": sum(item["status"] == "COMPLETE" for item in markets),
        "completed_episodes": len(completed_records),
        "market_order": order, "markets": markets,
        "cells": cells,
        "completed_model_cost_usd_estimate": format(spent, "f"),
        "shared_ledger_last_hash": ledger["last_hash"],
        "shared_ledger_blocked": ledger["blocked"],
        "primary_contrasts": frozen["primary_contrasts"],
        "contrast_interpretation": frozen["contrast_interpretation"],
        "pure_channel_access_effect_identified": False,
        "causal_or_collusion_claim_ready": False,
    }

