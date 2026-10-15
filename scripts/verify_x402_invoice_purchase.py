#!/usr/bin/env python3
"""Independently verify one stored native-local x402 invoice purchase."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_economic_trust.x402_invoice_verifier import verify_purchase


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("purchase_directory", type=Path)
    args = parser.parse_args()
    result = verify_purchase(args.purchase_directory)
    print(json.dumps(result.to_dict(), sort_keys=True))
