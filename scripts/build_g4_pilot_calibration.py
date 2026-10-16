#!/usr/bin/env python3
"""Build an exploratory W19 calibration from 32 reverified G4 trial records.

This reads a completed W10 collector checkpoint and reruns its full saved-log,
native-receipt, schema-v1 and canonical-ledger verifier for every trial. It
does not contact a model or chain and makes no causal or confirmatory claim.
"""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = str(WORKSPACE / ".local" / "share")
os.environ["XDG_CACHE_HOME"] = str(WORKSPACE / ".cache")
os.environ["XDG_CONFIG_HOME"] = str(WORKSPACE / ".config")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts import collect_w10_factorial as collector  # noqa: E402
from agent_economic_trust.remote import PROJECT_LEDGER_PATH  # noqa: E402
from agent_economic_trust.remote_budget import BudgetLedger  # noqa: E402
from agent_economic_trust.w10_factorial import (  # noqa: E402
    APPROVED_MODEL_ID, _canonical, analyze_assignments, frozen_fixtures,
)
from agent_economic_trust.w19_analysis import CELLS  # noqa: E402
from agent_economic_trust.w19_power import PilotCalibration  # noqa: E402


_HASH = re.compile(r"[0-9a-f]{64}\Z")
_COLLECTION_FIELDS = {
    "assignment_manifest_sha256", "record_count_including_pending",
    "missing_output_count", "failed_evidence_count", "valid_complete_count",
    "incomplete_output_count", "claim_scope", "causal_claim_ready",
    "ledger_last_hash_at_collection", "records_sha256",
}


def _need(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _regular(path: Path) -> Path:
    _need(path.is_file() and not path.is_symlink(), "missing_or_linked_evidence_file")
    return path


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(_regular(path).read_bytes())
    _need(isinstance(value, dict), "evidence_json_must_be_an_object")
    return value


def _read_records(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    data = _regular(path).read_bytes()
    _need(data.endswith(b"\n"), "collector_records_missing_final_newline")
    rows = [json.loads(line) for line in data.splitlines()]
    _need(all(isinstance(row, dict) for row in rows), "collector_record_is_not_an_object")
    _need(data == b"".join(_canonical(row) + b"\n" for row in rows),
          "collector_records_are_not_canonical")
    return rows, data


def _ledger_contains_hash(path: Path, expected: str) -> bool:
    """Check the collection head is an ancestor of the verified project ledger."""
    with _regular(path).open("rb") as stream:
        fcntl.flock(stream, fcntl.LOCK_SH)
        return any(json.loads(line).get("hash") == expected for line in stream)


def _check_collection(analysis: dict[str, Any], rows: list[dict[str, Any]],
                      records_bytes: bytes, trials: tuple[Any, ...],
                      assignment_sha: str) -> None:
    _need(len(trials) == len(rows) == 32, "G4_requires_all_32_assigned_pairs")
    _need([row.get("trial_id") for row in rows]
          == [trial.trial_id for trial in trials], "collector_assignment_order_changed")
    _need(all(row.get("status") == "COMPLETE"
              and row.get("evidence_validation") == "PASS"
              and row.get("assignment_manifest_sha256") == assignment_sha
              for row in rows), "G4_collection_contains_unverified_or_incomplete_trial")
    expected = analyze_assignments(trials, rows)
    _need(set(analysis) == set(expected) | _COLLECTION_FIELDS,
          "collector_analysis_fields_changed")
    _need(all(analysis[key] == value for key, value in expected.items()),
          "collector_analysis_differs_from_32_records")
    _need(analysis["assignment_manifest_sha256"] == assignment_sha
          and analysis["record_count_including_pending"] == 32
          and analysis["valid_complete_count"] == 32
          and all(analysis[key] == 0 for key in (
              "missing_output_count", "failed_evidence_count",
              "incomplete_output_count"))
          and analysis["records_sha256"] == sha256(records_bytes).hexdigest()
          and analysis["claim_scope"] == "descriptive_exploratory_ITT_bounds_only"
          and analysis["causal_claim_ready"] is False
          and isinstance(analysis["ledger_last_hash_at_collection"], str)
          and _HASH.fullmatch(analysis["ledger_last_hash_at_collection"]) is not None,
          "collector_checkpoint_hash_or_completion_changed")
    _need(all(analysis["cells"][cell]["complete"] == 4
              and analysis["cells"][cell]["incomplete"] == 0
              for cell in CELLS), "G4_cell_is_not_complete")


def _trial_artifacts(directory: Path, trial: Any, row: dict[str, Any],
                     assignment_sha: str) -> dict[str, str]:
    _need(directory.is_dir() and not directory.is_symlink(),
          "trial_evidence_directory_invalid")
    names = ("run_manifest.json", "inspect.eval", "native_evidence.json",
             "trial_record.json", "events.jsonl", "episode_outcomes.csv")
    hashes = {name: _sha(_regular(directory / name)) for name in names}
    _need(row["run_manifest_sha256"] == hashes["run_manifest.json"]
          and row["native_inspect_sha256"] == hashes["inspect.eval"]
          and row["native_payment_sha256"] == hashes["native_evidence.json"],
          "verified_trial_artifact_hash_changed")
    manifest = _json_object(directory / "run_manifest.json")
    randomization = manifest.get("randomization", {})
    _need(manifest.get("schema_version") == "1"
          and manifest.get("status") == "COMPLETE"
          and manifest.get("run_id") == row["ledger_run_id"]
          and manifest.get("model_behavior_tier") == "REAL_LLM_REMOTE_APPROVED"
          and manifest.get("payment_tier") == "NATIVE_LOCAL_CHAIN"
          and manifest.get("planned_episodes") == manifest.get("completed_episodes") == 1
          and manifest.get("models") == [{
              "id": APPROVED_MODEL_ID, "kind": "REAL_LLM_REMOTE_APPROVED",
              "reasoning_effort": "high",
          }]
          and randomization.get("assignment_manifest_sha256") == assignment_sha
          and randomization.get("trial_id") == trial.trial_id
          and randomization.get("pair_id") == trial.pair_id
          and tuple(randomization.get(key) for key in ("R", "S", "P"))
          == (trial.r, trial.s, trial.p),
          "trial_schema_v1_manifest_changed")
    _need(all(manifest.get("artifacts_sha256", {}).get(name) == hashes[name]
              for name in names if name != "run_manifest.json"),
          "trial_schema_v1_artifact_hash_changed")
    return hashes


def _cell_counts(trials: tuple[Any, ...], rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    truth = {fixture.fixture_id: fixture.truth for fixture in frozen_fixtures()}
    result = {cell: {key: 0 for key in (
        "bad_assigned", "bad_wrong_paid", "bad_unresolved", "all_assigned",
        "checked", "check_unresolved",
    )} for cell in CELLS}
    for trial, row in zip(trials, rows, strict=True):
        cell = result[trial.cell]
        oracle = truth[trial.fixture_id]
        _need(row.get("oracle_truth") == oracle, "verified_oracle_truth_changed")
        cell["all_assigned"] += 1
        cell["checked"] += int(row["checked"] is True)
        if oracle == 0:
            cell["bad_assigned"] += 1
            cell["bad_wrong_paid"] += int(row["payment_status"] == "PAID")
    return result


def build(assignment_dir: Path, collection_dir: Path, runs_dir: Path,
          output_dir: Path) -> dict[str, Any]:
    """Reverify a completed checkpoint and write a fresh bound calibration."""
    assignment_dir, collection_dir, runs_dir, output_dir = map(
        Path, (assignment_dir, collection_dir, runs_dir, output_dir))
    if output_dir.exists():
        raise FileExistsError("aggregate output already exists")
    _need(collection_dir.is_dir() and not collection_dir.is_symlink()
          and runs_dir.is_dir() and not runs_dir.is_symlink(),
          "collection_or_trial_directory_invalid")
    trials, assignment_sha = collector._load_plan(assignment_dir)
    records_path = collection_dir / "records.jsonl"
    analysis_path = collection_dir / "analysis.json"
    rows, records_bytes = _read_records(records_path)
    analysis_bytes = _regular(analysis_path).read_bytes()
    analysis = json.loads(analysis_bytes)
    _need(isinstance(analysis, dict), "collector_analysis_is_not_an_object")
    analysis_sha = sha256(analysis_bytes).hexdigest()
    _check_collection(analysis, rows, records_bytes, trials, assignment_sha)

    ledger = BudgetLedger(PROJECT_LEDGER_PATH).snapshot()
    _need(ledger["cap_usd"] == "20"
          and _ledger_contains_hash(PROJECT_LEDGER_PATH,
                                    analysis["ledger_last_hash_at_collection"]),
          "canonical_project_budget_or_collection_head_changed")
    artifacts: list[dict[str, Any]] = []
    costs: list[Decimal] = []
    for trial, row in zip(trials, rows, strict=True):
        directory = runs_dir / trial.trial_id
        raw = _json_object(directory / "trial_record.json")
        _need(not (directory / "STOPPED.json").exists()
              and not (directory / "STOPPED.json").is_symlink(),
              "runner_stopped_after_trial_record")
        independently_verified = collector._validated_record(
            directory, trial, assignment_sha, raw, ledger["runs"])
        _need(row == {
            "trial_id": trial.trial_id, "pair_id": trial.pair_id,
            "fixture_id": trial.fixture_id, "R": trial.r, "S": trial.s,
            "P": trial.p, "assignment_manifest_sha256": assignment_sha,
        } | independently_verified,
              "collected_record_differs_from_fresh_native_verification")
        hashes = _trial_artifacts(directory, trial, row, assignment_sha)
        try:
            cost = Decimal(row["model_cost_usd_estimate"])
        except (InvalidOperation, KeyError, TypeError):
            raise ValueError("invalid_verified_trial_model_cost") from None
        _need(cost.is_finite() and cost > 0, "invalid_verified_trial_model_cost")
        costs.append(cost)
        artifacts.append({
            "trial_id": trial.trial_id, "pair_id": trial.pair_id,
            "fixture_id": trial.fixture_id, "cell": trial.cell,
            "ledger_run_id": row["ledger_run_id"],
            "schema_v1_run_manifest_sha256": hashes["run_manifest.json"],
            "native_evidence_sha256": hashes["native_evidence.json"],
            "inspect_eval_sha256": hashes["inspect.eval"],
            "trial_record_sha256": hashes["trial_record.json"],
            "events_sha256": hashes["events.jsonl"],
            "episode_outcomes_sha256": hashes["episode_outcomes.csv"],
        })
    cells = _cell_counts(trials, rows)
    for cell in CELLS:
        _need(cells[cell]["bad_assigned"] == analysis["cells"][cell]["bad_assigned"]
              and cells[cell]["bad_wrong_paid"] == analysis["cells"][cell]["observed_bad_paid"]
              and cells[cell]["checked"] == analysis["cells"][cell]["observed_checks"],
              "calibration_counts_differ_from_collector_analysis")
    _need(_sha(_regular(assignment_dir / "assignment_manifest.json")) == assignment_sha
          and _sha(records_path) == sha256(records_bytes).hexdigest()
          and _sha(analysis_path) == analysis_sha,
          "checkpoint_changed_during_aggregate_verification")
    for item in artifacts:
        directory = runs_dir / item["trial_id"]
        for filename, key in (
            ("run_manifest.json", "schema_v1_run_manifest_sha256"),
            ("native_evidence.json", "native_evidence_sha256"),
            ("inspect.eval", "inspect_eval_sha256"),
            ("trial_record.json", "trial_record_sha256"),
            ("events.jsonl", "events_sha256"),
            ("episode_outcomes.csv", "episode_outcomes_sha256"),
        ):
            _need(_sha(_regular(directory / filename)) == item[key],
                  "trial_evidence_changed_during_aggregate_verification")
    manifest = {
        "schema": "g4-aggregate-run-manifest-v1",
        "status": "COMPLETE_VERIFIED",
        "source_gate": "G4",
        "claim_scope": "exploratory_calibration_only",
        "causal_claim_ready": False,
        "confirmatory_data": False,
        "assignment_unit": "fresh_worker_auditor_economic_pair",
        "assignment_manifest_sha256": assignment_sha,
        "assignment_count": 32,
        "independently_reverified_count": 32,
        "collection_records_sha256": _sha(records_path),
        "collection_analysis_sha256": analysis_sha,
        "collection_ledger_last_hash": analysis["ledger_last_hash_at_collection"],
        "verification_ledger_last_hash": ledger["last_hash"],
        "model_id": APPROVED_MODEL_ID,
        "model_behavior_tier": "REAL_LLM_REMOTE_APPROVED",
        "payment_tier": "NATIVE_LOCAL_PROTOCOL",
        "trials": artifacts,
        "source_sha256": {
            name: _sha(ROOT / name) for name in (
                "scripts/build_g4_pilot_calibration.py",
                "scripts/collect_w10_factorial.py",
                "src/agent_economic_trust/w19_power.py",
            )
        },
    }
    manifest_bytes = _canonical(manifest) + b"\n"
    pilot = {
        "schema": "w19-real-g4-pilot-v1",
        "source_gate": "G4",
        "randomized": True,
        "model_tier": "REAL_LLM_REMOTE_APPROVED",
        "payment_tier": "NATIVE_LOCAL_PROTOCOL",
        "source_run_sha256": sha256(manifest_bytes).hexdigest(),
        "max_observed_task_cost_usd": format(max(costs), "f"),
        "cells": cells,
        "claim_scope": "exploratory_calibration_only",
        "confirmatory_data": False,
    }
    PilotCalibration.parse(pilot)
    output_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    collector._new_file(output_dir / "aggregate_run_manifest.json", manifest_bytes)
    collector._new_file(output_dir / "pilot_calibration.json", _canonical(pilot) + b"\n")
    return {
        "status": "COMPLETE_VERIFIED_EXPLORATORY_CALIBRATION",
        "assignment_count": 32,
        "aggregate_manifest_sha256": pilot["source_run_sha256"],
        "pilot_calibration_sha256": _sha(output_dir / "pilot_calibration.json"),
        "max_observed_task_cost_usd": pilot["max_observed_task_cost_usd"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assignment-dir", type=Path, required=True)
    parser.add_argument("--collection-dir", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(args.assignment_dir, args.collection_dir,
                       args.runs_dir, args.output_dir)
    except Exception as exc:
        print(f"G4 pilot calibration stopped: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
