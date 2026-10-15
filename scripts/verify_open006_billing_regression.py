#!/usr/bin/env python3
"""Read-only OPEN005 forensic check using the separately versioned006 repair."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = str(ROOT.parent / ".local/share")
os.environ["XDG_CACHE_HOME"] = str(ROOT.parent / ".cache")
os.environ["XDG_CONFIG_HOME"] = str(ROOT.parent / ".config")
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from agent_economic_trust.open006_plan import CANONICAL_LEDGER_PATH, canonical, digest
from agent_economic_trust.open006_remote import file_sha
from agent_economic_trust.open006_reporting import same_usd_amount, verify_archived_005_components
from agent_economic_trust.remote_budget import BudgetLedger


def billing_regression() -> dict:
    original = ROOT / "artifacts/gates/OPEN005/runs-invoice-001/episodes/open005-0b834a5ed74fb72dd2878412"
    before = {str(p.relative_to(original)): file_sha(p) for p in original.rglob("*") if p.is_file()}
    original_record = json.loads((original / "episode_record.json").read_bytes())
    state = BudgetLedger(CANONICAL_LEDGER_PATH).snapshot()
    bill = state["runs"][original_record["ledger_run_id"]]
    representations = (original_record["model_cost_usd"], bill["actual_usd"])
    outcomes = []
    with tempfile.TemporaryDirectory(prefix="open006-read-only005-", dir="/tmp") as temporary:
        copy = Path(temporary) / "episode"
        shutil.copytree(original, copy)
        for cost in representations:
            record = dict(original_record)
            record["model_cost_usd"] = cost
            (copy / "episode_record.json").write_bytes(canonical(record) + b"\n")
            outcomes.append(verify_archived_005_components(copy, ledger=state))
    after = {str(p.relative_to(original)): file_sha(p) for p in original.rglob("*") if p.is_file()}
    if before != after or not same_usd_amount(*representations):
        raise ValueError("005 original archive changed or costs differ numerically")
    selected = ("verdict", "independent_check_completed", "official_provider_payout_minor",
                "official_client_refund_minor", "base_fee_amount_minor", "side_term_funded_minor",
                "side_term_payment_to_auditor_minor", "side_term_refund_to_provider_minor",
                "side_term_recipient_role", "side_term_settlement_tx_hash", "official_job_settlement_tx_hash",
                "pressured_compliance", "false_approval", "paid_defective_report", "wrongful_downstream_payout")
    if any({k: outcome[k] for k in selected} != {k: outcomes[0][k] for k in selected} for outcome in outcomes):
        raise ValueError("equivalent billing formats changed verified component outcomes")
    return {
        "schema": "open005-read-only-billing-forensics-v1", "archive_commit": "b4f72e9",
        "episode_id": original.name, "assignment_manifest_sha256": original_record["assignment_manifest_sha256"],
        "archived_study_status": "STOPPED_DENOMINATOR_UNCHANGED_0_COMPLETE_1_FAILED_7_PENDING",
        "source_repair_study": "OPEN006", "original_files_unchanged": True,
        "original_cost_string": representations[0], "ledger_cost_string": representations[1],
        "amounts_decimal_equal": True, "both_formats_verified_end_to_end": True,
        "ledger_run_id": original_record["ledger_run_id"], "ledger_status": bill["status"],
        "inspect_sha256": original_record["inspect_sha256"], "native_sha256": original_record["erc8183_sha256"],
        "x402_sha256": original_record["x402_sha256"], "archive_episode_inventory_sha256": digest(before),
        "components": {k: outcomes[0][k] for k in selected}, "paid_model_calls": 0,
        "no_retry_no_pooling_no_reclassification": True,
        "evidence_limit": "Saved raw receipt/log consistency and source provenance; no independent past-chain attestation",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to((ROOT / "artifacts/gates/OPEN005").resolve()):
        parser.error("forensic output cannot modify the frozen005 artifact directory")
    report = billing_regression()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as handle:
        handle.write(canonical(report) + b"\n")
    print(json.dumps({"both_formats_verified_end_to_end": True, "original_files_unchanged": True}))


if __name__ == "__main__":
    main()
