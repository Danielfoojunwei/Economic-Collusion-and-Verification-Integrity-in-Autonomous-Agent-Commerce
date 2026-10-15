#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m unittest discover -s tests -v
python -m paidaudit wire-smoke
python -m paidaudit run --config configs/pilot.json --out runs/pilot
python -m paidaudit verify-log runs/pilot/trials.jsonl
python -m paidaudit market-run --out runs/market --protocols all \
  --patterns reciprocal,rotating,ring3 --episodes 12 --seeds 2 --policy economic
python -m paidaudit verify-log runs/market/trials.jsonl
echo 'All OFFLINE simulations reproduced; no real funds or network payment SDKs used.'
