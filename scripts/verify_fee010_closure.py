#!/usr/bin/env python3
"""Read-only independent check of FEE010's final pre-execution closure."""

from __future__ import annotations

import json

from agent_economic_trust.fee010_closure import CLOSURE_SHA256, verify_closure


def main() -> None:
    report, rows = verify_closure()
    print(json.dumps({"status": report["status"],
                      "closure_sha256": CLOSURE_SHA256,
                      "planned_episodes": len(rows),
                      "completed_episodes": report["completed_episodes"],
                      "stopped_before_execution_episodes":
                          report["stopped_before_execution_episodes"],
                      "paid_model_calls": report["paid_model_calls"]}, sort_keys=True))


if __name__ == "__main__":
    main()
