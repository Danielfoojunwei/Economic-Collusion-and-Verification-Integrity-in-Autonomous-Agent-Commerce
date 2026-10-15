#!/usr/bin/env bash
set -euo pipefail

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project_root"
export PYTHON_DOTENV_DISABLED=1
export XDG_DATA_HOME=/workspace/.local/share
export XDG_CACHE_HOME=/workspace/.cache
export XDG_CONFIG_HOME=/workspace/.config
exec /workspace/upstreams/orbit-smoke/.venv/bin/python scripts/run_g1_offline.py "$@"
