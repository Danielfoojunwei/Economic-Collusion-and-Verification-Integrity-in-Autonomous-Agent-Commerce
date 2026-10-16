#!/usr/bin/env bash
set -euo pipefail

# Install the verified official ORBIT release, never the unrelated PyPI orbit.
workspace_root=/workspace
export XDG_DATA_HOME="$workspace_root/.local/share"
export XDG_CACHE_HOME="$workspace_root/.cache"
export XDG_CONFIG_HOME="$workspace_root/.config"
export PIP_CACHE_DIR="$workspace_root/.cache/pip"
release_dir="$workspace_root/upstreams/orbit-release"
venv_dir="$workspace_root/upstreams/orbit-smoke/.venv"
wheel_name=orbit-1.0.3-py3-none-any.whl
wheel_sha256=4be987cbc9ac3ed068fdf8208b3e20012ee8dd3d325547bf7b07afa9ffe2e642
release_url=https://github.com/wlanderson0/orbit/releases/download/v1.0.3

mkdir -p "$release_dir"
if [[ ! -f "$release_dir/$wheel_name" ]]; then
  curl --fail --location --show-error --silent \
    "$release_url/$wheel_name" -o "$release_dir/$wheel_name"
fi
printf '%s  %s\n' "$wheel_sha256" "$release_dir/$wheel_name" | sha256sum --check --status
if [[ ! -x "$venv_dir/bin/python" ]]; then
  python3 -m venv "$venv_dir"
fi
"$venv_dir/bin/python" -m pip install --quiet --disable-pip-version-check --no-input \
  'inspect-ai==0.3.263' 'jsonschema==4.26.0' "$release_dir/$wheel_name"
"$venv_dir/bin/python" -m pip check
"$venv_dir/bin/python" -c 'import importlib.metadata as m; assert m.version("orbit") == "1.0.3"; assert m.version("inspect-ai") == "0.3.263"; assert m.version("jsonschema") == "4.26.0"'
