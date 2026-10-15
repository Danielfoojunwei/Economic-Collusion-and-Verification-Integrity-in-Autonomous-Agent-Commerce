#!/usr/bin/env python3
"""Scripted zero-model native controls for prospective x402 live study 011."""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from agent_economic_trust.x402_live011_native import X402LiveNative  # noqa: E402
from agent_economic_trust.x402_live011_native_verifier import verify_live_native  # noqa: E402
from agent_economic_trust.x402_live011_plan import make_schedule  # noqa: E402


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _negative(directory: Path, row, field: str) -> str:
    with TemporaryDirectory(prefix="x402011-tamper-") as tmp:
        copied = Path(tmp) / "evidence"
        shutil.copytree(directory, copied)
        path = copied / "native-bridge.json"
        manifest = json.loads(path.read_bytes())
        if field == "retainer_payer":
            manifest["retainer_public"]["payer_role"] = "outsider"
        elif field == "check_amount":
            manifest["check"]["amount_minor"] += 1
        elif field == "wrong_verdict":
            manifest["settlement"]["requested_verdict"] = "ACCEPT" if (
                manifest["settlement"]["requested_verdict"] == "REJECT") else "REJECT"
        elif field == "wrong_terminal_status":
            manifest["settlement"]["status"] = "NOT_A_NATIVE_STATUS"
        elif field == "wrong_job_id":
            manifest["settlement"]["job_id"] = 999
        elif field == "wrong_check_status":
            manifest["check"]["status"] = "UNPAID"
            check_path = copied / "check-transaction.json"
            check_raw = json.loads(check_path.read_bytes())
            check_raw["receipt"]["status"] = "UNPAID"
            check_path.write_text(json.dumps(check_raw, indent=2, sort_keys=True) + "\n")
            manifest["check_raw_sha256"] = _sha(check_path)
        elif field == "empty_check_request":
            manifest["check"]["request_id"] = ""
            check_path = copied / "check-transaction.json"
            check_raw = json.loads(check_path.read_bytes())
            check_raw["receipt"]["request_id"] = ""
            check_path.write_text(json.dumps(check_raw, indent=2, sort_keys=True) + "\n")
            manifest["check_raw_sha256"] = _sha(check_path)
        else:
            raise ValueError("unknown negative control")
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        try:
            verify_live_native(copied, row, model_tier="SCRIPTED_SIMULATION")
        except ValueError as exc:
            return str(exc)
        raise AssertionError("independent verifier accepted tampered local receipt")


def run(directory: Path) -> dict:
    directory = Path(directory)
    if directory.exists():
        raise FileExistsError("offline evidence already exists; no overwrite")
    directory.mkdir(parents=True, mode=0o700)
    schedule = make_schedule("00" * 32)  # fixed test vector, not a live assignment
    cases = (("bad", "provider", True, "REJECT"),
             ("good", "buyer", False, "ACCEPT"),
             ("bad", "buyer", False, "ACCEPT"))
    outcomes = []
    for truth, payer, checked, verdict in cases:
        row = next(r for r in schedule if r.truth == truth and r.payer_role == payer)
        output = directory / row.episode_id
        with X402LiveNative(row, output, model_tier="SCRIPTED_SIMULATION") as native:
            if checked:
                native.buy_check(row, "offline-check-" + row.episode_id)
            native.settle(row, verdict, checked)
        verified = verify_live_native(output, row, model_tier="SCRIPTED_SIMULATION")
        negatives = {name: _negative(output, row, name)
                     for name in (("retainer_payer", "wrong_verdict")
                                  + (("check_amount",) if checked else ())) }
        outcomes.append({"episode_id": row.episode_id, "assignment": asdict(row),
                         "scripted_verdict": verdict, "check_requested": checked,
                         "verified": verified, "tamper_reasons": negatives,
                         "native_bridge_sha256": _sha(output / "native-bridge.json")})
    report = {"schema": "x402-live011-scripted-native-controls-v1",
              "status": "PASS", "paid_model_calls": 0,
              "model_tier": "SCRIPTED_SIMULATION",
              "transaction_tier": "NATIVE_LOCAL_PROTOCOL",
              "scripted_cases": len(outcomes),
              "tamper_negatives_rejected": sum(len(o["tamper_reasons"]) for o in outcomes),
              "live_collusion_observations": 0, "rows": outcomes}
    (directory / "report.json").write_text(json.dumps(report, indent=2,
                                                     sort_keys=True) + "\n")
    return report


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) == 2 else (
        ROOT / "artifacts/prospective/X402_LIVE011/offline-native-001")
    result = run(out)
    print(json.dumps({"status": result["status"],
                      "scripted_cases": result["scripted_cases"],
                      "tamper_negatives_rejected": result["tamper_negatives_rejected"],
                      "paid_model_calls": 0}, sort_keys=True))
