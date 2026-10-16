"""Read-only source-stage BILATERAL030 assigned-denominator collector.

It can verify a STOPPED evidence envelope and leave its primary outcome
missing. It cannot mark a row COMPLETE until a separate native/Inspect replay
collector is implemented, reviewed and pinned before assignment freeze.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping

from agent_economic_trust.bilateral030_plan import CANONICAL_LEDGER, ROWS, make_schedule
from agent_economic_trust.remote_budget import BudgetLedger


class CollectionError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CollectionError(message)


def _stop(row: Any, directory: Path, ledger: Mapping[str, Any]) -> dict:
    path = directory / "STOPPED.json"
    _require(not path.is_symlink() and path.is_file(), "STOPPED evidence is not regular")
    value = json.loads(path.read_bytes())
    _require(set(value) == {"schema", "episode_id", "assignment_sha256",
                            "status", "error_type",
                            "budget_state", "ledger_run_id", "partial_artifacts",
                            "no_retry_or_substitution"}
             and value["schema"] == "bilateral030-stopped-source-v1"
             and value["episode_id"] == row.episode_id
             and value["status"] == "STOPPED"
             and type(value["error_type"]) is str and value["error_type"]
             and value["no_retry_or_substitution"] is True
             and type(value["partial_artifacts"]) is list,
             "BILATERAL030 STOPPED envelope differs")
    ident = value["ledger_run_id"]
    budget = value["budget_state"]
    assignment_sha = value["assignment_sha256"]
    runs = ledger.get("runs", {})
    _require(type(assignment_sha) is str and
             re.fullmatch(r"[0-9a-f]{64}", assignment_sha) is not None
             and ident == f"bilateral030-{assignment_sha[:12]}-{row.episode_id}"
             and budget in {"UNRESERVED", "UNKNOWN"}
             and ((budget == "UNRESERVED" and ident not in runs)
                  or (budget == "UNKNOWN" and
                      runs.get(ident, {}).get("status") in {"UNKNOWN", "CONTINGENT"}
                      and runs[ident].get("metadata", {}).get("episode_id") ==
                      row.episode_id
                      and runs[ident].get("metadata", {}).get("assignment_sha") ==
                      assignment_sha)),
             "BILATERAL030 STOPPED billing state cannot be verified")
    seen = set()
    for item in value["partial_artifacts"]:
        _require(type(item) is dict and set(item) == {"path", "sha256"}
                 and type(item["path"]) is str and item["path"]
                 and type(item["sha256"]) is str and len(item["sha256"]) == 64,
                 "BILATERAL030 partial artifact entry differs")
        source = directory / item["path"]
        _require(item["path"] not in seen and not source.is_symlink()
                 and source.is_file()
                 and source.resolve().is_relative_to(directory.resolve())
                 and sha256(source.read_bytes()).hexdigest() == item["sha256"],
                 "BILATERAL030 partial artifact hash or path differs")
        seen.add(item["path"])
    expected_nodes = {"STOPPED.json"}
    for relative in seen:
        source = Path(relative)
        _require(not source.is_absolute() and ".." not in source.parts,
                 "BILATERAL030 partial artifact escapes row directory")
        expected_nodes.add(source.as_posix())
        expected_nodes.update(parent.as_posix() for parent in source.parents
                              if parent != Path("."))
    actual_nodes = {path.relative_to(directory).as_posix() for path in
                    directory.rglob("*")}
    _require(all(not path.is_symlink() for path in directory.rglob("*"))
             and actual_nodes == expected_nodes,
             "BILATERAL030 unrecorded partial evidence exists")
    return {"episode_id": row.episode_id, "status": "STOPPED",
            "primary_bad_early_approve_and_payout": None,
            "bilateral_collusion": None,
            "native_payment_independently_verified": False,
            "budget_state": budget,
            "partial_artifact_count": len(seen)}


def collect_source_only(seed_hex: str, episodes_dir: Path) -> dict:
    """Keep all thirty assignments visible; first STOPPED blocks later rows."""
    rows = make_schedule(seed_hex)
    ledger = BudgetLedger(CANONICAL_LEDGER).snapshot()
    root = Path(episodes_dir)
    assigned = {row.episode_id for row in rows}
    if root.exists():
        _require(root.is_dir() and not root.is_symlink(),
                 "BILATERAL030 episode root differs")
        _require(all(path.name in assigned and path.is_dir() and not path.is_symlink()
                     for path in root.iterdir()),
                 "BILATERAL030 unassigned episode directory exists")
    results = []
    blocked = False
    for row in rows:
        directory = root / row.episode_id
        if blocked:
            _require(not directory.exists(),
                     "BILATERAL030 row exists after first STOPPED or gap")
            result = {"episode_id": row.episode_id, "status": "PENDING",
                      "primary_bad_early_approve_and_payout": None,
                      "bilateral_collusion": None}
        elif (directory / "STOPPED.json").exists():
            result = _stop(row, directory, ledger)
            blocked = True
        elif directory.exists():
            raise CollectionError(
                "BILATERAL030 source-only collector cannot verify a COMPLETE or partial row")
        else:
            result = {"episode_id": row.episode_id, "status": "PENDING",
                      "primary_bad_early_approve_and_payout": None,
                      "bilateral_collusion": None}
            blocked = True
        results.append(result)
    _require(len(results) == ROWS, "BILATERAL030 denominator differs")
    return {"schema": "bilateral030-source-itt-collection-v1",
            "status": "SOURCE_ONLY_NO_LIVE_RESULTS",
            "frozen_assignment_verified": False,
            "native_payment_independently_verified": False,
            "planned_episodes": ROWS,
            "complete_episodes": 0,
            "stopped_episodes": sum(row["status"] == "STOPPED" for row in results),
            "pending_episodes": sum(row["status"] == "PENDING" for row in results),
            "rows": results,
            "inference_limit": "STOPPED has missing scientific outcome; no live or native result is verified"}
