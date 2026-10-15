#!/usr/bin/env python3
"""Run and export the G1 ORBIT/Inspect scripted verifier controls offline.

Example:
  /workspace/upstreams/orbit-smoke/.venv/bin/python scripts/run_g1_offline.py \
    --output-dir artifacts/gates/G1/scripted-run-001

No external model or payment endpoint is selected. The three policies are
authored controls; their outcomes cannot establish economic collusion.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["XDG_DATA_HOME"] = str(WORKSPACE_ROOT / ".local" / "share")
os.environ["XDG_CACHE_HOME"] = str(WORKSPACE_ROOT / ".cache")
os.environ["XDG_CONFIG_HOME"] = str(WORKSPACE_ROOT / ".config")
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from agent_economic_trust.offline import run_offline  # noqa: E402
from agent_economic_trust.reporting import export_log  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--policy", choices=("check", "always_accept", "always_reject", "all"),
        default="all",
    )
    parser.add_argument(
        "--created-utc", default=None,
        help="Fixed UTC timestamp for byte-identical derived event replay.",
    )
    args = parser.parse_args()
    pins = json.loads((PROJECT_ROOT / "UPSTREAM_PINNED.json").read_text(encoding="utf-8"))["sources"]
    source_pins = {
        name: {
            "commit": details["commit"],
            "version": details.get("release") or details.get("tag") or details.get("pyproject_version"),
        }
        for name, details in pins.items()
    }
    policies = (
        ("check", "always_accept", "always_reject")
        if args.policy == "all" else (args.policy,)
    )
    if args.output_dir.exists():
        raise SystemExit(f"Refusing to reuse existing output directory: {args.output_dir}")
    args.output_dir.mkdir(parents=True)
    summaries = []
    with TemporaryDirectory(prefix="g1-inspect-", dir=WORKSPACE_ROOT) as temporary:
        for policy in policies:
            log = run_offline(Path(temporary) / policy, policy=policy)
            result = export_log(
                log, args.output_dir / policy, policy=policy,
                source_pins=source_pins, created_utc=args.created_utc,
            )
            summaries.append({"policy": policy, **result})
    summary = {
        "experiment_id": "g1-reconciliation-controlled-pilot",
        "model_behavior_tier": "SCRIPTED",
        "payment_tier": "MOCK_LOCAL",
        "execution_tier": "SCRIPTED_SIMULATION",
        "controls": summaries,
        "limitations": [
            "Fixed worker artifacts do not measure worker competence.",
            "Public arithmetic can be inferred without buying the check.",
            "Scripted decisions do not measure LLM behavior or economic collusion.",
            "Mock settlement is not ERC-8183, x402, or any native payment protocol.",
        ],
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
