#!/usr/bin/env python3
"""Export or offline-verify the stopped W10 good-world native pilot."""

from __future__ import annotations

import argparse
import json

from agent_economic_trust.w10_recovery import recover_good, verify_recovery


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("recover", "verify"))
    args = parser.parse_args()
    result = recover_good() if args.action == "recover" else verify_recovery()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
