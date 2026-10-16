#!/usr/bin/env python3
"""Write W18's one-seed ORBIT scorer qualification; no model or payment calls."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_economic_trust.meeting_generalization import calibration_summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; keep prior evidence immutable")
    args.output.mkdir(parents=True)
    summary = calibration_summary()
    payload = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    evidence = args.output / "evidence.json"
    evidence.write_text(payload, encoding="utf-8")
    print(json.dumps({"evidence": str(evidence), "sha256": sha256(payload.encode()).hexdigest(),
                      "controls": summary["complete_assignments_checked"]}, sort_keys=True))


if __name__ == "__main__":
    main()
