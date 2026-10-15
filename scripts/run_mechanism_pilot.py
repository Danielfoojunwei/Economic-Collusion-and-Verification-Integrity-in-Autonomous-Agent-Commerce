#!/usr/bin/env python3
"""Preflight/execute one paid pilot episode or run model-free readiness checks."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = str(WORKSPACE / ".local" / "share")
os.environ["XDG_CACHE_HOME"] = str(WORKSPACE / ".cache")
os.environ["XDG_CONFIG_HOME"] = str(WORKSPACE / ".config")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from agent_economic_trust.mechanism_native import (  # noqa: E402
    MechanismNative, verify_mechanism_native_evidence,
)
from agent_economic_trust.mechanism_plan import (  # noqa: E402
    case_for_episode, make_schedule,
)
from agent_economic_trust.mechanism_remote import (  # noqa: E402
    MechanismPilotPlan, execute_one, preflight,
)
from agent_economic_trust.mechanism_smoke import verify_scripted_smoke  # noqa: E402
from agent_economic_trust.mechanism_task import (  # noqa: E402
    BonusProposal, ClaimSubmission,
)
from scripts.freeze_mechanism_pilot import (  # noqa: E402
    PILOT_ROOT, source_inventory_sha256,
)


OFFLINE_ROOT = PILOT_ROOT / "offline-smoke-001"
OFFLINE_SEED = "a" * 64
OFFLINE_ASSIGNMENT_SHA = sha256(b"mechanism-model-free-native-smoke-v1").hexdigest()
PYTHON = WORKSPACE / "upstreams" / "orbit-smoke" / ".venv" / "bin" / "python"
FORGE = WORKSPACE / ".tools" / "foundry" / "v1.8.5" / "forge"


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _json(path: Path, value: dict[str, Any]) -> None:
    path.write_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False, allow_nan=False).encode() + b"\n")


def _count_passes(command: list[str], *, cwd: Path,
                  unittest_mode: bool = False) -> tuple[int, str]:
    child_env = os.environ.copy()
    if unittest_mode:
        child_env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT)))
    process = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                             timeout=180, check=False, env=child_env)
    output = process.stdout + process.stderr
    matches = (re.findall(r"\bRan (\d+) tests\b", output)
               if unittest_mode else re.findall(r"\b(\d+) passed\b", output))
    if process.returncode or not matches or (unittest_mode and not output.rstrip().endswith("OK")):
        raise RuntimeError("focused model-free readiness tests failed")
    return int(matches[-1]), output


def run_offline_smoke(output: Path = OFFLINE_ROOT) -> dict[str, Any]:
    """Create four real local payment paths with scripted decisions, zero LLMs."""
    output = Path(output)
    scripted_report = output / "scripted_inspect_report.json"
    if not scripted_report.is_file() or verify_scripted_smoke(output)["status"] != "PASS":
        raise ValueError("four-cell scripted Inspect delivery smoke is absent")
    native_root = output / "native"
    if native_root.exists():
        raise FileExistsError("model-free native smoke already exists; do not overwrite it")
    native_root.mkdir(parents=True, mode=0o700)
    rows = make_schedule(OFFLINE_SEED)
    results = []
    for row in rows:
        quality = "GOOD" if row.truth else "BAD"
        name = f"{quality.lower()}-{row.arm.lower()}"
        native_dir = native_root / name
        case, artifact = case_for_episode(row)
        with MechanismNative(row, native_dir,
                             assignment_manifest_sha256=OFFLINE_ASSIGNMENT_SHA) as native:
            obligation = native.open_job()
            submission_id = sha256(json.dumps({
                "episode_id": row.episode_id,
                "task_id": case.task_id,
                "core_address": obligation.core_address.lower(),
                "job_id": obligation.job_id,
                "artifact_digest": artifact.digest(),
            }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            native.submit_claim(ClaimSubmission(
                episode_id=row.episode_id, task_id=case.task_id,
                obligation=obligation, artifact=artifact,
                submission_id=submission_id,
            ))
            if row.arm == "DIRECT_OFFER_CAPABILITY":
                amount = 1 if row.truth == 0 else 5_000_000
                native.fund_bonus(BonusProposal(
                    episode_id=row.episode_id, task_id=row.task_id,
                    obligation=obligation, amount_minor=amount,
                    proposal_id=f"offline-{row.episode_id}",
                ))
            native.settle_job("ACCEPT" if row.truth else "REJECT", row.artifact_digest)
            evidence = native.save_evidence()
            verified = verify_mechanism_native_evidence(evidence)
            if (verified["verdict"] != ("ACCEPT" if row.truth else "REJECT")
                    or verified["audit_fee_minor_units"] != 2_000_000
                    or verified["audit_fee_payer_role"] != "provider"
                    or verified["submission_artifact_digest"] != row.artifact_digest
                    or verified["bonus_status"] != (
                        "UNFUNDED" if row.arm == "DIRECT_NEUTRAL"
                        else "RELEASED" if row.truth else "REFUNDED")):
                raise ValueError("model-free native settlement or fee control differs")
            results.append({
                "quality": quality, "arm": row.arm,
                "episode_id": row.episode_id,
                "path": str(evidence.relative_to(output)),
                "sha256": _sha(evidence), "verified": "PASS",
            })
    python_count, python_output = _count_passes([
        str(PYTHON), "-m", "unittest", "discover", "-s", "tests",
        "-p", "test_mechanism_*.py", "-v",
    ], cwd=ROOT, unittest_mode=True)
    foundry_count, foundry_output = _count_passes([
        str(FORGE), "test", "--offline", "--use",
        str(WORKSPACE / ".tools/solc/v0.8.28/solc"),
    ], cwd=ROOT / "protocols/side_escrow")
    (output / "focused-python-tests.log").write_text(python_output, encoding="utf-8")
    (output / "focused-foundry-tests.log").write_text(foundry_output, encoding="utf-8")
    report = {
        "schema": "mechanism-offline-readiness-v1",
        "status": "PASS", "independent_verifier": "PASS",
        "execution_tiers": {"agent_behavior": "SCRIPTED_SIMULATION",
                            "payment": "NATIVE_LOCAL_PROTOCOL"},
        "offline_seed_hex": OFFLINE_SEED,
        "source_inventory_sha256": source_inventory_sha256(),
        "scripted_inspect_report": {
            "path": "scripted_inspect_report.json",
            "sha256": _sha(scripted_report),
        },
        "native_evidence": results,
        "tests_passed": {"python": python_count, "foundry": foundry_count},
        "paid_model_calls": 0,
        "limitations": "Scripted decisions prove wiring only; no live-agent collusion outcome.",
    }
    _json(output / "report.json", report)
    verify_offline_smoke(output)
    return report


def verify_offline_smoke(output: Path = OFFLINE_ROOT) -> dict[str, Any]:
    """Read-only verify scripted Inspect and all four actual local payment paths."""
    output = Path(output)
    report = json.loads((output / "report.json").read_bytes())
    if (report.get("schema") != "mechanism-offline-readiness-v1"
            or report.get("status") != "PASS"
            or report.get("independent_verifier") != "PASS"
            or report.get("source_inventory_sha256") != source_inventory_sha256()
            or report.get("paid_model_calls") != 0
            or any(type(report.get("tests_passed", {}).get(key)) is not int
                   or report["tests_passed"][key] <= 0 for key in ("python", "foundry"))):
        raise ValueError("offline readiness report, source seal or test gate differs")
    scripted = report["scripted_inspect_report"]
    if (scripted != {"path": "scripted_inspect_report.json",
                    "sha256": _sha(output / "scripted_inspect_report.json")}
            or verify_scripted_smoke(output)["status"] != "PASS"):
        raise ValueError("scripted Inspect exact delivery evidence differs")
    rows = make_schedule(report["offline_seed_hex"])
    by_id = {row.episode_id: row for row in rows}
    saved = report["native_evidence"]
    if len(saved) != 4 or len({item["episode_id"] for item in saved}) != 4 \
            or set(item["episode_id"] for item in saved) != set(by_id):
        raise ValueError("model-free native evidence lacks four assigned cells")
    for item in saved:
        row = by_id[item["episode_id"]]
        quality = "GOOD" if row.truth else "BAD"
        relative = Path(item["path"])
        if (relative.is_absolute() or ".." in relative.parts
                or item["quality"] != quality or item["arm"] != row.arm
                or item["verified"] != "PASS"):
            raise ValueError("native smoke row path, arm or truth differs")
        path = output / relative
        verified = verify_mechanism_native_evidence(path)
        raw = json.loads(path.read_bytes())
        if (item["sha256"] != _sha(path)
                or raw["episode_id"] != row.episode_id
                or raw["arm"] != row.arm
                or raw["assignment_manifest_sha256"] != OFFLINE_ASSIGNMENT_SHA
                or verified["verdict"] != ("ACCEPT" if row.truth else "REJECT")
                or verified["bonus_status"] != (
                    "UNFUNDED" if row.arm == "DIRECT_NEUTRAL"
                    else "RELEASED" if row.truth else "REFUNDED")
                or verified["audit_fee_minor_units"] != 2_000_000
                or verified["audit_fee_payer_role"] != "provider"):
            raise ValueError("native smoke raw job, bonus or prepaid fee differs")
    return {"status": "PASS", "independent_verifier": "PASS",
            "native_controls_verified": 4, "scripted_inspect_cells_verified": 4,
            "paid_model_calls": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "execute-one",
                                         "offline-smoke", "verify-offline-smoke"))
    parser.add_argument("--output", type=Path, default=OFFLINE_ROOT,
                        help="only used by the model-free offline smoke")
    args = parser.parse_args()
    try:
        if args.mode == "preflight":
            result = preflight(MechanismPilotPlan())
        elif args.mode == "execute-one":
            result = execute_one(MechanismPilotPlan())
        elif args.mode == "offline-smoke":
            result = run_offline_smoke(args.output)
        else:
            result = verify_offline_smoke(args.output)
    except Exception as exc:
        # External/model exceptions can contain authorization material.
        print(f"mechanism pilot stopped: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
