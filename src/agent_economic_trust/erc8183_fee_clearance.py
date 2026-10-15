"""Read-only predecessor disposition gate for the separately frozen MPP009 block."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from .mpp005_plan import canonical_project_root


GATE = canonical_project_root() / "artifacts/gates/MPP009"


def _sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError("sealed MPP009 artifact must be a regular file")
    return sha256(path.read_bytes()).hexdigest()


def sealed_mpp009_disposition(ledger: Mapping[str, Any]) -> dict:
    """Require exactly 0 COMPLETE, 1 STOPPED, 9 PENDING and one settled run."""
    assignment = GATE / "assignment-001/assignment_manifest.json"
    collection = GATE / "collection-001-after-first-stop.json"
    lock = GATE / "one-time-freeze.lock.json"
    frozen = json.loads(assignment.read_text())
    report = json.loads(collection.read_text())
    sealed = json.loads(lock.read_text())
    order = frozen.get("execution_order")
    if (frozen.get("schema") != "mpp009-assignment-v1"
            or report.get("schema") != "mpp009-collection-v1"
            or sealed.get("schema") != "mpp009-one-time-freeze-v1"
            or not isinstance(order, list) or len(order) != 10 or len(set(order)) != 10
            or frozen.get("planned_episodes") != 10
            or report.get("planned_episodes") != 10
            or report.get("completed_episodes") != 0
            or report.get("assignment_manifest_sha256") != _sha(assignment)
            or sealed.get("assignment_manifest_sha256") != _sha(assignment)
            or not isinstance(report.get("rows"), list)
            or [row.get("episode_id") for row in report["rows"]] != order
            or [row.get("status") for row in report["rows"]]
                != ["STOPPED", *(["PENDING"] * 9)]):
        raise ValueError("MPP009 is not sealed at 0 complete/1 stopped/9 pending")
    rows = json.loads((GATE / "assignment-001/private_episodes.json").read_text())
    by_id = {r["episode_id"]: r for r in rows}
    if len(by_id) != 10 or set(by_id) != set(order) or by_id[order[0]]["truth"] != "GOOD":
        raise ValueError("MPP009 first assigned GOOD row or denominator differs")
    episodes = GATE / "runs-001/episodes"
    if not episodes.is_dir() or {p.name for p in episodes.iterdir()} != {order[0]}:
        raise ValueError("MPP009 has continuation or unexpected episode path")
    directory = episodes / order[0]
    if directory.is_symlink() or (directory / "episode_record.json").exists():
        raise ValueError("MPP009 stopped row falsely claims completion")
    stop_path = directory / "STOPPED.json"
    stop = json.loads(stop_path.read_text())
    ident = "mpp009-" + _sha(assignment)[:12] + "-" + order[0]
    billing = ledger.get("runs", {}).get(ident)
    inspect_path = directory / "inspect.eval"
    if (stop.get("schema") != "mpp009-stopped-episode-v1"
            or stop.get("episode_id") != order[0]
            or stop.get("assignment_manifest_sha256") != _sha(assignment)
            or stop.get("ledger_run_id") != ident
            or stop.get("budget_state") != "SETTLED"
            or stop.get("no_retry_or_substitution") is not True
            or stop.get("complete_payment_claim") is not False
            or billing is None or billing.get("status") != "SETTLED"
            or billing.get("evidence_ref") != "sha256:" + _sha(inspect_path)
            or billing.get("metadata", {}).get("assignment_sha") != _sha(assignment)
            or billing.get("metadata", {}).get("episode_id") != order[0]):
        raise ValueError("MPP009 STOPPED/billing/Inspect linkage differs")
    for entry in stop.get("partial_artifacts", []):
        path = directory / entry["path"]
        if (not path.resolve().is_relative_to(directory.resolve())
                or _sha(path) != entry["sha256"]):
            raise ValueError("MPP009 stopped partial archive differs")
    return {"status": "SEALED_STOPPED_NO_RETRY", "planned_episodes": 10,
            "completed_episodes": 0, "stopped_episodes": 1, "pending_episodes": 9,
            "assignment_manifest_sha256": _sha(assignment),
            "collection_sha256": _sha(collection), "first_stop_sha256": _sha(stop_path),
            "ledger_run_id": ident, "model_execution_tier": "REAL_LLM_REMOTE_APPROVED",
            "native_outcome_claim": "STOPPED_PARTIAL_ONLY"}
