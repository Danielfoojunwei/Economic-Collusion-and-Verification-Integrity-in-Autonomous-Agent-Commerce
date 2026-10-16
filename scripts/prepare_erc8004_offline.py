"""Prepare a pinned, local solcjs compiler for ERC-8004 Hardhat tests.

Hardhat 3 downloads a compiler index even when a local compiler path is set.
This creates a local index for the exact solc@0.8.24 npm compiler bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


UPSTREAM_COMMIT = "b9e466c250744a7e06b13dff9d3c2844ed64f825"
SOLJSON_SHA256 = "fb59b825b7d57f9de89cd9de2415b12aab1fcc7eb2573fd2bf5c9b969eacf4d9"


def prepare(upstream: Path, compiler: Path, cache_home: Path) -> dict:
    upstream = upstream.resolve()
    compiler = compiler.resolve()
    commit = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
    if commit != UPSTREAM_COMMIT:
        raise ValueError(f"wrong ERC-8004 commit: {commit}")
    tracked_changes = subprocess.check_output(
        ["git", "-C", str(upstream), "status", "--porcelain", "--untracked-files=no"], text=True
    ).strip()
    if tracked_changes:
        raise ValueError("pinned upstream tracked files are modified")
    digest = hashlib.sha256(compiler.read_bytes()).hexdigest()
    if digest != SOLJSON_SHA256:
        raise ValueError(f"wrong solc@0.8.24 bytes: {digest}")
    local_config = upstream / "hardhat.local.config.ts"
    local_config.write_text(
        'import config from "./hardhat.config.ts";\n'
        f'for (const profile of Object.values((config.solidity as any).profiles)) {{\n'
        f'  (profile as any).path = {json.dumps(str(compiler))};\n'
        '}\nexport default config;\n'
    )
    for platform in ("linux-amd64", "wasm"):
        destination = cache_home / "hardhat-nodejs" / "compilers-v3" / platform
        destination.mkdir(parents=True, exist_ok=True)
        name = "soljson-v0.8.24.js"
        shutil.copy2(compiler, destination / name)
        if platform == "linux-amd64":
            (destination / f"{name}.does.not.work").touch()
        build = {
            "path": name, "version": "0.8.24", "longVersion": "0.8.24+commit.e11b9ed9",
            "sha256": f"0x{digest}",
        }
        (destination / "list.json").write_text(json.dumps({
            "builds": [build], "releases": {"0.8.24": name}, "latestRelease": "0.8.24",
        }))
    return {"upstream_commit": commit, "compiler_sha256": digest, "cache_home": str(cache_home)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=Path, default=Path("/workspace/upstreams/w17-erc8004"))
    parser.add_argument("--compiler", type=Path, default=Path("/workspace/upstreams/w17-solc24/soljson.js"))
    parser.add_argument("--cache-home", type=Path, default=Path(os.environ.get("XDG_CACHE_HOME", "/workspace/upstreams/.cache")))
    args = parser.parse_args()
    print(json.dumps(prepare(args.upstream, args.compiler, args.cache_home), sort_keys=True))
