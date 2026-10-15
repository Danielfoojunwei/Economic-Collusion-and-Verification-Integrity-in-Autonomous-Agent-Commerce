#!/usr/bin/env python3
"""Read-only replay of G1/W05 native Inspect isolation checks.

This resolves Inspect's attachment references before examining model inputs and
tool replies. It does not regenerate or edit the original evidence.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from inspect_ai.log import read_eval_log

from agent_economic_trust.reporting import assert_log_isolation


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIRS = (
    "artifacts/gates/G1/scripted-run-004/always_accept",
    "artifacts/gates/G1/scripted-run-004/always_reject",
    "artifacts/gates/G1/scripted-run-004/check",
    "artifacts/gates/W05/real-run-001/reconcile-002",
    "artifacts/gates/W05/real-run-002/reconcile-001",
)


def audit(directory: Path) -> dict[str, object]:
    native = directory / "inspect.eval"
    manifest_path = directory / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    native_sha = sha256(native.read_bytes()).hexdigest()
    if (manifest.get("status") != "COMPLETE"
            or manifest.get("artifacts_sha256", {}).get("inspect.eval") != native_sha):
        raise ValueError(f"manifest does not pin complete native evidence: {directory}")
    log = read_eval_log(str(native), resolve_attachments=True)
    if log.status != "success" or not log.samples:
        raise ValueError(f"native Inspect evaluation is incomplete: {directory}")
    counts = assert_log_isolation(log)
    for sample in log.samples:
        for event in sample.events:
            if event.event == "model":
                content = json.dumps([message.model_dump(mode="json")
                                      for message in event.input], sort_keys=True)
            elif event.event == "tool":
                content = json.dumps(event.result, sort_keys=True, default=str)
            else:
                continue
            if "attachment://" in content:
                raise ValueError(f"native Inspect attachment was not resolved: {directory}")
    return {
        "directory": str(directory.relative_to(ROOT)) if directory.is_relative_to(ROOT) else str(directory),
        "native_sha256": native_sha,
        "manifest_sha256": sha256(manifest_path.read_bytes()).hexdigest(),
        "samples": len(log.samples),
        "resolved_attachment_replay": True,
        **counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", nargs="*", type=Path,
                        help="evidence directories; defaults to final G1 and two W05 runs")
    args = parser.parse_args()
    directories = args.directories or [ROOT / name for name in DEFAULT_DIRS]
    records = [audit(path.resolve()) for path in directories]
    print(json.dumps({"verified": True, "records": records}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
