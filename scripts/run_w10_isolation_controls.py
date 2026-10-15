#!/usr/bin/env python3
"""Scripted ORBIT controls on real local R0/R1 funding receipts; no LLM calls."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = str(WORKSPACE / ".local" / "share")
os.environ["XDG_CACHE_HOME"] = str(WORKSPACE / ".cache")
os.environ["XDG_CONFIG_HOME"] = str(WORKSPACE / ".config")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from inspect_ai import eval as inspect_eval  # noqa: E402
from inspect_ai.log import read_eval_log  # noqa: E402
from agent_economic_trust.w10_factorial import (  # noqa: E402
    audit_independent_pair_log, make_assignments, task_for_trial,
)
from agent_economic_trust.w10_funding import NativePairFundingVerifier  # noqa: E402
from tests.test_protected_receipts import scripted_model  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--funding-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("scripted control output already exists")
    rows = make_assignments((args.plan / "seed.hex").read_text(encoding="ascii").strip())
    manifest_sha = sha256((args.plan / "assignment_manifest.json").read_bytes()).hexdigest()
    funding = NativePairFundingVerifier(args.funding_evidence, rows, manifest_sha)
    args.output.mkdir(parents=True, mode=0o700, exist_ok=False)
    observations = []
    for truth in ("good", "bad"):
        for r in (0, 1):
            trial = next(row for row in rows
                         if row.fixture_id == f"delivery-{truth}"
                         and row.r == r and row.s == 0 and row.p == 0)
            directory = args.output / f"{truth}-R{r}"
            [log] = inspect_eval(
                task_for_trial(trial, verify_funding=funding, scheduler_seconds=60),
                model=scripted_model("check"), log_dir=str(directory),
                display="none", log_realtime=False, max_retries=0,
            )
            if log.status != "success" or len(log.samples or []) != 1 \
                    or log.samples[0].error or log.samples[0].limit:
                raise RuntimeError("scripted native-funded ORBIT control failed")
            isolation = audit_independent_pair_log(log)
            score = log.samples[0].scores["protected_receipt_score"].metadata
            receipt = funding(trial)
            native = directory / "inspect.eval"
            Path(log.location).replace(native)
            persisted = read_eval_log(str(native))
            if audit_independent_pair_log(persisted) != isolation:
                raise AssertionError("saved native log changed pair isolation audit")
            observations.append({
                "trial_id": trial.trial_id, "pair_id": trial.pair_id,
                "fixture_id": trial.fixture_id, "R": trial.r, "S": trial.s,
                "P": trial.p, "payer_role": receipt.payer_role,
                "funding_transaction_hash": receipt.transaction_hash,
                "funding_receipt_sha256": receipt.receipt_sha256,
                "oracle_status": score["oracle_status"], "verdict": score["V"],
                "check_completed": score["Q"],
                "check_spent_units": score["check_spent_units"],
                "channel_isolation": isolation,
                "native_inspect_log": str(native.relative_to(args.output)),
                "native_inspect_sha256": sha256(native.read_bytes()).hexdigest(),
            })
    evidence = {
        "schema": "w10-scripted-native-funding-control-v1",
        "model_behavior_tier": "SCRIPTED",
        "payment_tier": "NATIVE_LOCAL_ERC20_PREPAID_FEE",
        "verdict_payment_tier": "NOT_EXECUTED",
        "assignment_manifest_sha256": manifest_sha,
        "funding_evidence_sha256": funding.evidence_sha256,
        "observations": observations,
        "limitations": [
            "Auditor and worker actions are authored scripted controls, not LLM choices.",
            "Prepaid audit fees are distinct from payment for accepted work.",
            "No causal relationship effect or collusion conclusion follows from these controls.",
        ],
    }
    target = args.output / "control_summary.json"
    target.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS", "scripted_controls": len(observations),
        "funding_evidence_sha256": funding.evidence_sha256,
        "summary_sha256": sha256(target.read_bytes()).hexdigest(),
        "model_calls": 0,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
