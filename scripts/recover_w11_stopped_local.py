#!/usr/bin/env python3
"""Post-hoc local ERC-8183 replay of one stopped W11 episode.

This is a technical forensic artifact, excluded from assignment-006 COMPLETE
outcomes. It never resumes the original market or requests a model response.
Only the copied Anvil checkpoint is settled, using the archived REJECT verdict.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = str(WORKSPACE / ".local" / "share")
os.environ["XDG_CACHE_HOME"] = str(WORKSPACE / ".cache")
os.environ["XDG_CONFIG_HOME"] = str(WORKSPACE / ".config")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from agent_economic_trust.w11_market_native import (  # noqa: E402
    LiveNativeMarket, verify_market_evidence,
)


MARKET_ID = "market-acb40c26ae8838c87fd3"
EPISODE_ID = "episode-de0a57bf5b8ca2bbe753"
ASSIGNMENT_SHA256 = "ae037b6df7b0e0130578c6f6f7fe210a23690ad653ee54d0877315173ee9f0d9"
VERDICT = "REJECT"


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


@contextmanager
def _loopback_only():
    """Deny Python external sockets; the replay needs localhost Anvil RPC."""
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def check(address: object) -> None:
        if isinstance(address, str):  # AF_UNIX socket path
            return
        if not isinstance(address, tuple) or not address:
            raise OSError("forensic replay denied a non-loopback socket")
        try:
            if ipaddress.ip_address(address[0]).is_loopback:
                return
        except (ValueError, TypeError):
            pass
        raise OSError("forensic replay denied a non-loopback socket")

    def guarded_connect(sock: socket.socket, address: object):
        check(address)
        return original_connect(sock, address)

    def guarded_connect_ex(sock: socket.socket, address: object):
        check(address)
        return original_connect_ex(sock, address)

    with patch.object(socket.socket, "connect", guarded_connect), patch.object(
        socket.socket, "connect_ex", guarded_connect_ex
    ):
        yield


def _forensic_preflight(plan_dir: Path, runs_dir: Path, preimage_root: Path) -> dict:
    path = ROOT / "scripts" / "forensic_w11_stopped.py"
    spec = spec_from_file_location("forensic_w11_stopped_offline", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("read-only W11 forensic preflight is unavailable")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.forensic_preflight(plan_dir, runs_dir, preimage_root,
                                     market_id=MARKET_ID, episode_id=EPISODE_ID)


def recover_local(plan_dir: Path, runs_dir: Path, preimage_root: Path,
                  output_dir: Path) -> dict:
    """Replay a saved local job in isolation after independent offline checks."""
    plan_dir, runs_dir, preimage_root, output_dir = map(
        Path, (plan_dir, runs_dir, preimage_root, output_dir))
    output_abs = output_dir.resolve()
    input_roots = (plan_dir.resolve(), runs_dir.resolve(), preimage_root.resolve(),
                   ROOT / "artifacts" / "budget")
    if output_dir.exists() or any(output_abs == root or output_abs.is_relative_to(root)
                                      for root in input_roots):
        raise ValueError("recovery output must be a new path outside original inputs")
    original_native = runs_dir / MARKET_ID / "native"
    original_episode = runs_dir / MARKET_ID / "episodes" / EPISODE_ID
    originals = (
        plan_dir / "assignment_manifest.json",
        original_episode / "STOPPED.json",
        original_episode / "inspect.eval",
        original_native / "evidence.json",
        original_native / "anvil-state.hex",
        ROOT / "artifacts" / "budget" / "openrouter-ledger.jsonl",
        ROOT / "artifacts" / "budget" / "openrouter-ledger.jsonl.anchor",
    )
    before = {str(path.resolve()): _sha(path) for path in originals}
    with _loopback_only():
        preflight = _forensic_preflight(plan_dir, runs_dir, preimage_root)
        if (preflight["assignment_manifest_sha256"] != ASSIGNMENT_SHA256
                or preflight["market_id"] != MARKET_ID
                or preflight["episode_id"] != EPISODE_ID
                or preflight["verdict"] != VERDICT
                or preflight["oracle_truth"] != 0
                or preflight["checked"] is not True
                or preflight["native_status"] != "OPEN"
                or preflight["ledger_status"] != "UNKNOWN"
                or preflight["model_calls"] != 8):
            raise ValueError("stopped-round forensic preflight differs from archived REJECT")
        original = json.loads((original_native / "evidence.json").read_bytes())
        open_round = next(item for item in original["rounds"]
                          if item["episode_id"] == EPISODE_ID)
        if (open_round["obligation_id"] != original["active_obligation"]
                or open_round["job_id"] != 3
                or open_round["artifact_digest"] !=
                next(row["artifact_digest"] for row in json.loads(
                    (plan_dir / "private_rounds.json").read_bytes())
                    if row["episode_id"] == EPISODE_ID)):
            raise ValueError("saved OPEN job differs from frozen assignment")

        native_copy = output_dir / "native-replay"
        native_copy.mkdir(parents=True, mode=0o700, exist_ok=False)
        for filename in ("evidence.json", "anvil-state.hex"):
            shutil.copy2(original_native / filename, native_copy / filename)
            if _sha(native_copy / filename) != _sha(original_native / filename):
                raise ValueError("isolated checkpoint copy differs from original")
        # No credential is made available to any local native replay process.
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "",
                                     "ALLOW_EXTERNAL_MODEL_CALLS": "false",
                                     "MAX_REAL_SPEND": "0"}):
            with LiveNativeMarket(MARKET_ID, native_copy, r=original["R"],
                                  assignment_manifest_sha256=ASSIGNMENT_SHA256,
                                  resume=True) as market:
                verified_open = market.verify_open_round(open_round["obligation_id"])
                if verified_open != open_round:
                    raise ValueError("restored live OPEN round differs from saved checkpoint")
                settlement = market.settle_round(open_round["obligation_id"], VERDICT,
                                                 open_round["artifact_digest"])
        recovered_path = native_copy / "evidence.json"
        result = verify_market_evidence(recovered_path)
        recovered = json.loads(recovered_path.read_bytes())
        terminal = next(item for item in recovered["rounds"]
                        if item["episode_id"] == EPISODE_ID)
        if (recovered["rounds"][:2] != original["rounds"][:2]
                or terminal["status"] != "REJECTED"
                or terminal["settlement"] != settlement
                or settlement["verdict"] != VERDICT
                or settlement["provider_paid"] is not False
                or settlement["provider_payout_minor_units"] != 0
                or recovered["active_obligation"] is not None
                or result["statuses"] != {"REJECTED": 2, "COMPLETED": 1}
                or len(recovered["transactions"]) != len(original["transactions"]) + 2):
            raise ValueError("isolated local settlement does not match archived verdict")
        after = {str(path.resolve()): _sha(path) for path in originals}
        if after != before:
            raise RuntimeError("an original W11 artifact or budget ledger changed during replay")
        report = {
            "schema": "w11-local-forensic-settlement-v1",
            "classification": "POST_HOC_TECHNICAL_RECOVERY",
            "assignment_006_complete_denominator_inclusion": False,
            "original_status": "STOPPED_UNKNOWN_BILLING",
            "original_native_status": "OPEN",
            "replayed_native_status": "REJECTED",
            "model_calls_made": 0,
            "external_payment_calls_made": 0,
            "local_replay_transactions": 2,
            "real_asset_value": 0,
            "source_preflight": preflight,
            "original_sha256_unchanged": before,
            "replayed_native_evidence_sha256": _sha(recovered_path),
            "replayed_native_state_sha256": _sha(native_copy / "anvil-state.hex"),
            "replayed_job_id": terminal["job_id"],
            "replayed_obligation_id": terminal["obligation_id"],
            "replayed_settlement_tx_hash": settlement["raw_receipt"]["transactionHash"],
            "replayed_provider_payout_minor_units": 0,
            "replayed_client_refund_minor_units": 20_000_000,
            "native_verification": result,
            "limitations": [
                "The original assignment-006 episode remains STOPPED and incomplete.",
                "The local chain was restored from a saved checkpoint in a new process.",
                "This replay is a post-hoc technical verification, not a prospective payment outcome.",
                "Provider billing is unresolved by this local replay.",
            ],
        }
        report_path = output_dir / "recovery_report.json"
        report_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assignment-dir", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--preimage-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = recover_local(args.assignment_dir, args.runs_dir,
                           args.preimage_root, args.output_dir)
    print(json.dumps({key: result[key] for key in (
        "classification", "assignment_006_complete_denominator_inclusion",
        "replayed_native_evidence_sha256", "replayed_native_status",
        "model_calls_made", "external_payment_calls_made")}, sort_keys=True))


if __name__ == "__main__":
    main()
