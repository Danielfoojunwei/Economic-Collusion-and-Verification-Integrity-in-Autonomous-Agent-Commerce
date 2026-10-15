#!/usr/bin/env python3
"""Freeze prospective W13 assignments and replay independently audited G4 evidence.

This script is read-only with respect to G4 and makes no model or payment call.
The generated defense outcomes are projected application counterfactuals only.
"""

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
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.collect_w10_factorial import _load_plan, collect  # noqa: E402
from agent_economic_trust.w13_live_defense_plan import (  # noqa: E402
    _canonical, prospective_manifest, replay_verified_g4,
)


def _new_json(path: Path, value: dict) -> str:
    encoded = _canonical(value) + b"\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    return sha256(encoded).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assignment-dir", type=Path, required=True)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--spot-seed", required=True,
                        help="Predeclared 64-character hex seed for retrospective cell selection")
    parser.add_argument("--prospective-pair-seed", help="Fresh seed; do not reuse G4 pair seed")
    parser.add_argument("--prospective-defense-seed", help="Separate fresh defense-arm seed")
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("output directory already exists")
    if bool(args.prospective_pair_seed) != bool(args.prospective_defense_seed):
        parser.error("provide both prospective seeds or neither")
    try:
        prospective = (prospective_manifest(args.prospective_pair_seed,
                                            args.prospective_defense_seed)
                       if args.prospective_pair_seed else None)
        trials, assignment_sha = _load_plan(args.assignment_dir)
        if args.prospective_pair_seed and (args.prospective_pair_seed ==
                                           (args.assignment_dir / "seed.hex").read_text(
                                               encoding="ascii").strip()
                                           or {row["pair_id"] for row in prospective["rows"]}
                                           & {trial.pair_id for trial in trials}):
            raise ValueError("prospective economic pair seed reuses G4 pair identities")
        args.output_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
        collection_dir = args.output_dir / "source_collection"
        collection = collect(args.assignment_dir, args.runs_dir, collection_dir)
        records_bytes = (collection_dir / "records.jsonl").read_bytes()
        if sha256(records_bytes).hexdigest() != collection["records_sha256"]:
            raise ValueError("verified source collection changed before replay")
        records = [json.loads(line) for line in records_bytes.splitlines()]
        replay = replay_verified_g4(trials, records, seed_hex=args.spot_seed)
        replay["source_assignment_manifest_sha256"] = assignment_sha
        replay["source_records_sha256"] = collection["records_sha256"]
        replay["source_collection_analysis_sha256"] = collection["analysis_sha256"]
        replay["source_collector_valid_complete_count"] = collection["valid_complete_count"]
        replay["source_collector_failed_evidence_count"] = collection["failed_evidence_count"]
        replay_sha = _new_json(args.output_dir / "retrospective_replay.json", replay)
        seeds_sha = _new_json(args.output_dir / "seed_material.json", {
            "retrospective_spot_seed_hex": args.spot_seed,
            "prospective_pair_seed_hex": args.prospective_pair_seed,
            "prospective_defense_seed_hex": args.prospective_defense_seed,
            "note": "Research assignment seeds, not credentials. Retrospective replay is not preregistered.",
        })
        result = {"status": "OFFLINE_ONLY", "source_valid_complete": collection["valid_complete_count"],
                  "retrospective_replay_sha256": replay_sha,
                  "seed_material_sha256": seeds_sha,
                  "retrospective_native_defense_execution": False}
        if prospective is not None:
            prospective["source_code_sha256"] = {
                name: sha256((ROOT / name).read_bytes()).hexdigest() for name in (
                    "src/agent_economic_trust/w13_live_defense_plan.py",
                    "src/agent_economic_trust/w10_factorial.py",
                    "src/agent_economic_trust/protected_receipts.py",
                    "scripts/run_w13_live_plan.py",
                )
            }
            result["prospective_manifest_sha256"] = _new_json(
                args.output_dir / "prospective_assignment_manifest.json", prospective)
        print(json.dumps(result, sort_keys=True))
    except Exception as exc:
        print(f"W13 offline planning stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
