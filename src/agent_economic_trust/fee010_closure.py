"""Independent read-only final closure of FEE010's zero-call verifier stop.

The first assignment is a retained experimental denominator. Its source and
artifacts are never repaired in place. All eight rows are explicitly closed
before execution, which is distinct from a stopped model trial.
"""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

from .erc8183_fee_plan import CANONICAL_LEDGER, ROWS, make_schedule, prospective_manifest
from .remote_budget import BudgetLedger


ROOT = CANONICAL_LEDGER.parents[2]
SOURCE_ROOT = Path(__file__).resolve().parents[2]
OLD_GATE = ROOT / "artifacts/gates/ERC8183_FEE010"
OLD_READINESS = ROOT / "artifacts/prospective/erc8183-fee-live/readiness-001.json"
CLOSURE = SOURCE_ROOT / "artifacts/gates/ERC8183_FEE010/verification-stop-001.json"
OLD_ASSIGNMENT_SHA256 = "db6dcf6c4cca6c6a4e3ce2f527cb7d35d054c8ab6da5c42571b68bedc6d3adcd"
OLD_LOCK_SHA256 = "3e0ad984fc13c1ae7683f0fce697bafcf1134f449aa5ca3d290d803e195beec6"
OLD_READINESS_SHA256 = "c6c1d3549fa990c4fa9f978a5c564c363a6f60e93cd2e0696c4e5842312ab8dc"
OLD_SEED_SHA256 = "9bb9211eda8b568a45eea4fd927cab96120611d291d9778e08e48620b290b46a"
OLD_PRIVATE_ROWS_SHA256 = "5fae08d442a614cf5d3205ac70272bea18593313bf500b4c8c2e9129cbcf1be2"
OLD_SOURCE_COMMIT = "be284036ae17f129b757b29c058adde2dff613aa"
CLOSURE_SHA256 = "15ec9bc8fdbdaeba553987e62691cdc3539c2e4c2dcf4281575119389459d96b"


def file_sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("FEE010 archive file missing or symlinked")
    return sha256(path.read_bytes()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def original_clearance() -> tuple[dict, tuple]:
    """Reconstruct old assignment while reproducing its sole preview mismatch."""
    assignment_path = OLD_GATE / "assignment-001/assignment_manifest.json"
    lock_path = OLD_GATE / "first-freeze.lock.json"
    seed_path = OLD_GATE / "assignment-001/seed.hex"
    rows_path = OLD_GATE / "assignment-001/private_rows.json"
    for path, expected in ((assignment_path, OLD_ASSIGNMENT_SHA256),
                           (lock_path, OLD_LOCK_SHA256),
                           (OLD_READINESS, OLD_READINESS_SHA256),
                           (seed_path, OLD_SEED_SHA256),
                           (rows_path, OLD_PRIVATE_ROWS_SHA256)):
        _require(file_sha(path) == expected, "pinned FEE010 zero-call artifact differs")
    frozen = json.loads(assignment_path.read_text())
    lock = json.loads(lock_path.read_text())
    readiness = json.loads(OLD_READINESS.read_text())
    seed = seed_path.read_text().strip()
    rows = make_schedule(seed)
    preview = prospective_manifest(seed, rows)
    private_rows = json.loads(rows_path.read_text())
    _require(len(rows) == ROWS and private_rows == [asdict(row) for row in rows]
             and frozen.get("source_commit") == OLD_SOURCE_COMMIT
             and lock.get("source_commit") == OLD_SOURCE_COMMIT
             and frozen.get("readiness_sha256") == OLD_READINESS_SHA256
             and frozen.get("schema") == "erc8183-fee-first-assignment-v1"
             and frozen.get("status") == "FROZEN_NOT_EXECUTED"
             and lock.get("schema") == "erc8183-fee-first-freeze-lock-v1"
             and lock.get("assignment_manifest_sha256") == OLD_ASSIGNMENT_SHA256
             and lock.get("paid_model_calls") == 0
             and readiness.get("schema") == "erc8183-fee-independent-readiness-v1"
             and readiness.get("status") == "PASS_READ_ONLY"
             and readiness.get("source_sha256") == frozen.get("source_sha256")
             and readiness.get("runtime_versions") == frozen.get("runtime_versions")
             and readiness.get("control_summary_sha256") ==
                 frozen.get("zero_model_summary_sha256")
             and readiness.get("mpp009_predecessor_disposition") ==
                 frozen.get("mpp009_predecessor_disposition")
             and frozen.get("source_inventory_sha256") ==
                 lock.get("source_inventory_sha256")
             and frozen.get("erc8183_upstream_commit") ==
                 "142e669c1fd318486a4628395b629f033654dd06"
             and frozen.get("seed_commitment_sha256") == preview["seed_commitment_sha256"]
             and frozen.get("private_rows_hmac_sha256") ==
                 preview["private_rows_hmac_sha256"],
             "FEE010 seed, rows, old readiness or lock differs")
    mismatches = {key: {"frozen": frozen.get(key), "preview": preview[key]}
                  for key in preview if frozen.get(key) != preview[key]}
    _require(mismatches == {
        "schema": {"frozen": "erc8183-fee-first-assignment-v1",
                   "preview": "erc8183-fee-design-assignment-preview-v1"},
        "status": {"frozen": "FROZEN_NOT_EXECUTED",
                   "preview": "UNFROZEN_NO_PAID_EXECUTION"}},
        "FEE010 verifier mismatch is not limited to schema/status")
    sources = frozen.get("source_sha256")
    _require(isinstance(sources, dict) and len(sources) == 28,
             "FEE010 sealed source inventory differs")
    source_digest = sha256(json.dumps(sources, sort_keys=True,
        separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    _require(frozen.get("source_inventory_sha256") == source_digest,
             "FEE010 source inventory digest differs")
    for name, expected in sources.items():
        path = ROOT / name
        _require(path.resolve().is_relative_to(ROOT.resolve())
                 and file_sha(path) == expected,
                 "FEE010 frozen executable/source changed")
    runs = OLD_GATE / "runs-001"
    _require(not runs.exists(), "FEE010 episode/run path exists after zero-call stop")
    ledger = BudgetLedger(CANONICAL_LEDGER).snapshot()
    fee010_runs = sorted(name for name in ledger.get("runs", {}) if name.startswith("fee010-"))
    _require(not fee010_runs, "FEE010 has a shared-ledger run after zero-call stop")
    return {"schema": "fee010-preexecution-closure-v1",
            "status": "CLOSED_STOPPED_BEFORE_EXECUTION",
            "study_id": "erc8183-native-evaluator-fee-live-010",
            "old_assignment_sha256": OLD_ASSIGNMENT_SHA256,
            "old_lock_sha256": OLD_LOCK_SHA256,
            "old_readiness_sha256": OLD_READINESS_SHA256,
            "old_seed_file_sha256": OLD_SEED_SHA256,
            "old_private_rows_sha256": OLD_PRIVATE_ROWS_SHA256,
            "old_source_commit": OLD_SOURCE_COMMIT,
            "old_source_inventory_sha256": frozen["source_inventory_sha256"],
            "execution_order": frozen["execution_order"],
            "preview_mismatch": mismatches,
            "read_only_verifier_error": {"type": "ValueError",
                "message": "frozen fee study assignment/source differs"},
            "planned_episodes": ROWS,
            "completed_episodes": 0,
            "stopped_before_execution_episodes": ROWS,
            "pending_episodes": 0,
            "rows": [{"episode_id": row.episode_id,
                      "status": "STOPPED_BEFORE_EXECUTION"} for row in rows],
            "old_lock_paid_model_calls": 0,
            "paid_model_calls": 0,
            "shared_ledger_fee010_run_ids": [],
            "old_run_directory_present": False,
            "observed_ledger_seq": ledger["seq"],
            "observed_ledger_hash": ledger["last_hash"],
            "evidence_limit": "zero calls established by old lock, absent local run path and shared ledger; external off-ledger billing is not covered"}, rows


def verify_closure() -> tuple[dict, tuple]:
    if not CLOSURE_SHA256:
        raise ValueError("FEE010 final closure has no pinned hash")
    _require(file_sha(CLOSURE) == CLOSURE_SHA256,
             "pinned FEE010 final closure changed")
    saved = json.loads(CLOSURE.read_text())
    current, rows = original_clearance()
    _require(set(saved) == set(current), "FEE010 final closure field set differs")
    for key in current:
        if key not in {"observed_ledger_seq", "observed_ledger_hash"}:
            _require(saved.get(key) == current[key],
                     "FEE010 final closure differs from current clearance")
    return saved, rows
