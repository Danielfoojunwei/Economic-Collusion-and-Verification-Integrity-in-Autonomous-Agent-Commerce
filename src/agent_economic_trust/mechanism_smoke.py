"""Persist and independently reopen four scripted native Inspect mechanism cells.

Run with ``python -m agent_economic_trust.mechanism_smoke generate PATH``.
Only Inspect's mockllm and fake callback are used. A PASS proves tool grants,
ordering, and saved-log provenance; it is not evidence of LLM collusion or
native ERC-8183/side-escrow execution.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ.setdefault("XDG_DATA_HOME", "/workspace/.local/share")
os.environ.setdefault("XDG_CACHE_HOME", "/workspace/.cache")
os.environ.setdefault("XDG_CONFIG_HOME", "/workspace/.config")

from inspect_ai import eval as inspect_eval
from inspect_ai.log import read_eval_log

from .mechanism_task import (
    ARM_NEUTRAL, ARM_OFFER, BonusFundingReceipt, ClaimSubmissionReceipt,
    audit_saved_mechanism_log, build_mechanism_task,
)


_ROOT = Path(__file__).resolve().parents[2]
_SOURCES = (
    "src/agent_economic_trust/mechanism_task.py",
    "src/agent_economic_trust/mechanism_smoke.py",
    "src/agent_economic_trust/protected_receipts.py",
    "tests/test_mechanism_task.py",
)


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _inventory_digest() -> str:
    # Import lazily to avoid a cycle: the freezer inventories this module too.
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from scripts.freeze_mechanism_pilot import source_inventory_sha256
    return source_inventory_sha256()


def _fixtures():
    # The test module is intentionally the sole source of the scripted model.
    # No production live runner imports this smoke generator.
    from tests.test_mechanism_task import case_for, obligation_for, scripted_model
    return case_for, obligation_for, scripted_model


def _cell_id(quality: str, arm: str) -> str:
    return f"{quality.lower()}-{arm.lower().replace('_', '-')}"


def _score_fields(sample: Any) -> dict[str, Any]:
    score = sample.scores["mechanism_score"]
    return {
        "value": score.value,
        "Y": score.metadata["Y"], "V": score.metadata["V"],
        "Q": score.metadata["Q"],
        "official_job_submitted": score.metadata["official_job_submitted"],
        "submission_tier": score.metadata["submission_tier"],
        "funding_tier": score.metadata["funding_tier"],
    }


def generate_scripted_smoke(output: Path) -> dict[str, Any]:
    """Write four immutable-once-created scripted `.eval` archives and report."""
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"smoke output already exists: {output}")
    output.mkdir(parents=True)
    case_for, obligation_for, scripted_model = _fixtures()
    cells = []
    for index, (quality, arm) in enumerate(
        ((q, a) for q in ("GOOD", "BAD") for a in (ARM_NEUTRAL, ARM_OFFER)), 1
    ):
        case, artifact = case_for(quality)
        episode_id = f"scripted-{quality.lower()}-{arm.lower()}"
        cell_id = _cell_id(quality, arm)
        cell_dir = output / cell_id
        cell_dir.mkdir()
        submissions = []
        bonuses = []

        def submit(request):
            submissions.append(request)
            return ClaimSubmissionReceipt(request, "SCRIPTED_SIMULATION")

        def fund(proposal):
            bonuses.append(proposal)
            return BonusFundingReceipt(proposal, "SCRIPTED_SIMULATION")

        task = build_mechanism_task(
            case, artifact, episode_id=episode_id, arm=arm,
            obligation=obligation_for(index),
            funding_tier="SCRIPTED_SIMULATION", submit_claim=submit,
            fund_bonus=fund if arm == ARM_OFFER else None,
        )
        [runtime] = inspect_eval(
            task, model=scripted_model(case, artifact, arm),
            log_dir=str(cell_dir), display="none", log_realtime=False,
            max_retries=0,
        )
        if runtime.status != "success":
            raise RuntimeError(f"scripted Inspect cell {cell_id} failed: {runtime.error}")
        archive = cell_dir / "inspect.eval"
        shutil.copyfile(runtime.location, archive)
        original = Path(runtime.location)
        if original != archive:
            original.unlink()
        saved = read_eval_log(str(archive), resolve_attachments=True)
        audit = audit_saved_mechanism_log(
            saved, case, artifact, episode_id=episode_id, arm=arm,
            require_delivery=True,
        )
        if (len(submissions) != 1 or len(bonuses) != int(arm == ARM_OFFER)
                or not audit["provider_private_quality_read"]
                or audit["official_submission_count"] != 1
                or not audit["exact_message_reached_auditor_input"]
                or not audit["trusted_bonus_proof_seen_before_verdict"]):
            raise RuntimeError(f"scripted Inspect cell {cell_id} lacks required proof")
        cells.append({
            "cell_id": cell_id, "quality": quality, "arm": arm,
            "episode_id": episode_id,
            "saved_eval": f"{cell_id}/inspect.eval",
            "saved_eval_sha256": _sha(archive),
            "model_behavior_tier": "SCRIPTED_SIMULATION",
            "payment_tier": "SCRIPTED_SIMULATION",
            "submission_callback_count": len(submissions),
            "bonus_callback_count": len(bonuses),
            "audit": audit, "score": _score_fields(saved.samples[0]),
        })
    report = {
        "schema": "mechanism-scripted-inspect-v1", "status": "PASS",
        "claim_limit": "Scripted model and callbacks only; no live LLM, native payment, or collusion finding.",
        "source_sha256": {path: _sha(_ROOT / path) for path in _SOURCES},
        "source_inventory_sha256": _inventory_digest(),
        "cells": cells,
    }
    (output / "scripted_inspect_report.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return verify_scripted_smoke(output)


def verify_scripted_smoke(output: Path) -> dict[str, Any]:
    """Reopen every saved archive and recompute private oracle and channel audit."""
    output = Path(output)
    report = json.loads((output / "scripted_inspect_report.json").read_text(encoding="utf-8"))
    if (report.get("schema") != "mechanism-scripted-inspect-v1"
            or report.get("status") != "PASS" or len(report.get("cells", [])) != 4):
        raise ValueError("scripted Inspect report is incomplete")
    if report.get("source_sha256") != {path: _sha(_ROOT / path) for path in _SOURCES}:
        raise ValueError("scripted Inspect source differs from report")
    if report.get("source_inventory_sha256") != _inventory_digest():
        raise ValueError("full frozen source inventory differs from scripted Inspect report")
    case_for, _, _ = _fixtures()
    seen = set()
    for cell in report["cells"]:
        quality, arm = cell["quality"], cell["arm"]
        key = (quality, arm)
        if (quality not in {"GOOD", "BAD"} or arm not in {ARM_NEUTRAL, ARM_OFFER}
                or key in seen or cell["cell_id"] != _cell_id(quality, arm)
                or cell["model_behavior_tier"] != "SCRIPTED_SIMULATION"
                or cell["payment_tier"] != "SCRIPTED_SIMULATION"):
            raise ValueError("scripted Inspect cell identity or tier changed")
        seen.add(key)
        archive = output / cell["saved_eval"]
        if archive.resolve() != (output / cell["cell_id"] / "inspect.eval").resolve():
            raise ValueError("scripted Inspect archive path escaped expected cell")
        if _sha(archive) != cell["saved_eval_sha256"]:
            raise ValueError("scripted Inspect archive hash changed")
        case, artifact = case_for(quality)
        saved = read_eval_log(str(archive), resolve_attachments=True)
        audit = audit_saved_mechanism_log(
            saved, case, artifact, episode_id=cell["episode_id"], arm=arm,
            require_delivery=True,
        )
        if audit != cell["audit"] or _score_fields(saved.samples[0]) != cell["score"]:
            raise ValueError("saved native Inspect behavior differs from report")
        if (cell["submission_callback_count"] != 1
                or cell["bonus_callback_count"] != int(arm == ARM_OFFER)
                or cell["score"]["value"] != 1
                or cell["score"]["Y"] != int(quality == "GOOD")
                or cell["score"]["Q"] is not True
                or cell["score"]["submission_tier"] != "SCRIPTED_SIMULATION"
                or audit["scripted_offer_exposed"] != (arm == ARM_OFFER)
                or audit["native_funded_offer_exposed"]
                or not audit["trusted_bonus_proof_seen_before_verdict"]
                or audit["trusted_bonus_status"] != (
                    "SCRIPTED_NOT_NATIVE" if arm == ARM_OFFER else "NONE")
                or audit["auditor_verified_bonus"]["escrow_address"] is not None
                or audit["auditor_verified_bonus"]["funding_tx_hash"] is not None
                or audit["auditor_verified_bonus"]["receipt_sha256"] is not None):
            raise ValueError("scripted Inspect controlled outcome differs from plan")
    if seen != {(q, a) for q in ("GOOD", "BAD") for a in (ARM_NEUTRAL, ARM_OFFER)}:
        raise ValueError("scripted Inspect four-cell coverage differs from plan")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("generate", "verify"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = (generate_scripted_smoke(args.output) if args.action == "generate"
              else verify_scripted_smoke(args.output))
    print(json.dumps({"status": report["status"], "cells": len(report["cells"]),
                      "report": str(args.output / "scripted_inspect_report.json")},
                     sort_keys=True))


if __name__ == "__main__":
    main()
