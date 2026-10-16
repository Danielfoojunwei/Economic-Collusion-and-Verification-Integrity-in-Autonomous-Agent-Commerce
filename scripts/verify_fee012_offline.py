#!/usr/bin/env python3
"""Replay FEE012 scripted native controls without any model call."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from agent_economic_trust.fee012_offline import ARCHIVE, verify as _verify  # noqa: E402


def verify(output_dir: Path = ARCHIVE) -> dict:
    return _verify(output_dir)


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
