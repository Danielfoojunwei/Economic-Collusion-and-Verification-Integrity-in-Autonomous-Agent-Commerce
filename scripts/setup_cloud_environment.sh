#!/usr/bin/env bash
set -euo pipefail

# Recreate the pinned, local-only research runtime. This script neither starts
# a model nor contacts an external chain, facilitator, or payment service.
project=/workspace/Economic-Collusion-and-Verification-Integrity-in-Autonomous-Agent-Commerce
upstreams=/workspace/upstreams
tools_dir=/workspace/.tools
export XDG_DATA_HOME=/workspace/.local/share
export XDG_CACHE_HOME=/workspace/.cache
export XDG_CONFIG_HOME=/workspace/.config
export PIP_CACHE_DIR=/workspace/.cache/pip
export COREPACK_HOME=/workspace/.cache/corepack
export PYTHON_DOTENV_DISABLED=1

fail() { printf 'setup: %s\n' "$*" >&2; exit 1; }
[[ -f "$project/UPSTREAM_PINNED.json" ]] || fail "project handover is absent at $project"
command -v git >/dev/null || fail 'git is required'
command -v curl >/dev/null || fail 'curl is required'
command -v python3 >/dev/null || fail 'Python 3.11 or later is required'
command -v node >/dev/null || fail 'Node.js 22 or later is required'
command -v corepack >/dev/null || fail 'Corepack is required for pinned pnpm'
command -v uv >/dev/null || fail 'uv is required for the isolated AP2 SDK'
command -v npm >/dev/null || fail 'npm is required for the locked MPP SDK'
command -v docker >/dev/null || fail 'Docker is required for the local Tempo payment chain'
python3 -c 'import sys; assert sys.version_info >= (3, 11)'
[[ "$(node -p 'Number(process.versions.node.split(".")[0]) >= 22')" == true ]] || fail 'Node.js 22 or later is required'
mkdir -p "$upstreams" "$tools_dir/downloads" "$tools_dir/foundry" "$tools_dir/solc/v0.8.28" \
  "$XDG_DATA_HOME" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$PIP_CACHE_DIR" "$COREPACK_HOME"

pin_checkout() {
  local name=$1 url=$2 expected=$3 path="$upstreams/$1"
  if [[ ! -e "$path" ]]; then
    git clone --quiet --filter=blob:none --no-checkout "$url" "$path"
    git -C "$path" checkout --quiet --detach "$expected"
  fi
  git -C "$path" rev-parse --is-inside-work-tree >/dev/null 2>&1 || \
    fail "$path exists but is not a Git checkout"
  local remote actual
  remote=$(git -C "$path" remote get-url origin)
  [[ "${remote%.git}" == "${url%.git}" ]] || fail "$name remote changed: $remote"
  actual=$(git -C "$path" rev-parse HEAD)
  [[ "$actual" == "$expected" ]] || fail "$name is at $actual, expected $expected; inspect before changing it"
  printf '%s: %s\n' "$name" "$actual"
}

# Colosseum is retained as a methods reference; its code is not installed.
pin_checkout orbit https://github.com/wlanderson0/orbit 588b3035f92450ec4f0496bb8b629daa205e84c7
pin_checkout inspect_ai https://github.com/UKGovernmentBEIS/inspect_ai.git 7aa7343e4a14fa7be07e5a09c7431df5e88c17ee
pin_checkout colosseum https://github.com/umass-ai-safety/colosseum.git b077fe7e2f10566e92156cc12e06ffb2aac54790
pin_checkout erc8183 https://github.com/erc-8183/base-contracts 142e669c1fd318486a4628395b629f033654dd06
pin_checkout x402 https://github.com/x402-foundation/x402 e95b06661e1a2a8a9a21fce34cc28b9934834650
pin_checkout ap2-w15 https://github.com/google-agentic-commerce/AP2 b4587ac1d055888a73b4b21750973cffba961793
pin_checkout mppx-feasibility https://github.com/wevm/mppx d8d800f101ba1568f0d737e12574c0ae8f6b6e93

if [[ -n "$(git -C "$upstreams/erc8183" status --porcelain)" ]]; then
  fail 'ERC-8183 checkout has changes; inspect before updating submodules'
fi
git -C "$upstreams/erc8183" submodule update --init --recursive
for submodule_pin in \
  'lib/forge-std 620536fa5277db4e3fd46772d5cbc1ea0696fb43' \
  'lib/openzeppelin-contracts 5fd1781b1454fd1ef8e722282f86f9293cacf256' \
  'lib/openzeppelin-contracts-upgradeable 7bf4727aacdbfaa0f36cbd664654d0c9e1dc52bf'; do
  read -r submodule expected <<< "$submodule_pin"
  actual=$(git -C "$upstreams/erc8183/$submodule" rev-parse HEAD)
  [[ "$actual" == "$expected" ]] || fail "$submodule is at $actual, expected $expected"
done

download_verified() {
  local url=$1 path=$2 digest=$3
  if [[ ! -f "$path" ]]; then
    curl --fail --location --show-error --silent --retry 2 "$url" -o "$path"
  fi
  printf '%s  %s\n' "$digest" "$path" | sha256sum --check --status || fail "checksum mismatch: $path"
}

foundry_archive="$tools_dir/downloads/foundry_v1.8.5_linux_amd64.tar.gz"
foundry_dir="$tools_dir/foundry/v1.8.5"
download_verified \
  https://github.com/foundry-rs/foundry/releases/download/v1.8.5/foundry_v1.8.5_linux_amd64.tar.gz \
  "$foundry_archive" 6c66ffcc55fa4249197721baa3098bc208014ea1d8aa04b2ed50ac6bccffb226
if [[ ! -e "$foundry_dir" ]]; then
  foundry_stage=$(mktemp -d "$tools_dir/foundry/.v1.8.5.XXXXXXXX")
  tar -xzf "$foundry_archive" -C "$foundry_stage"
  mv "$foundry_stage" "$foundry_dir"
fi
for binary_pin in \
  'forge 06c477aee83d0996e57aa92b0841fdf06382cb172fd69bbb88920bb0054dfd7f' \
  'cast 1eb1eecfdadaad8da2173ccf0c7c0be86fe237b0a267042a40d7ca12d0fa2af7' \
  'anvil 00f97668e1ae0fcca118fd7d2d1b6d25c0496447a523ca6bc2dfd10958c99604'; do
  read -r binary expected <<< "$binary_pin"
  printf '%s  %s\n' "$expected" "$foundry_dir/$binary" | sha256sum --check --status || \
    fail "Foundry $binary does not match the verified v1.8.5 archive"
done

solc_archive="$tools_dir/downloads/solc-linux-amd64-v0.8.28+commit.7893614a"
solc_binary="$tools_dir/solc/v0.8.28/solc"
solc_digest=9a0fb7e0db2c0641dbae1c5cc645dc686820c83af516226abb1c0a2f76636f25
download_verified \
  'https://raw.githubusercontent.com/ethereum/solc-bin/2875476c59e0ee167eae0459f99abb04da8ebd78/linux-amd64/solc-linux-amd64-v0.8.28%2Bcommit.7893614a' \
  "$solc_archive" "$solc_digest"
if [[ ! -e "$solc_binary" ]]; then
  install -m 0755 "$solc_archive" "$solc_binary"
fi
printf '%s  %s\n' "$solc_digest" "$solc_binary" | sha256sum --check --status || fail 'solc checksum mismatch'

cd "$project"
bash scripts/setup_g1_runtime.sh
# Freeze the full installed Python set captured during the verified W01 smoke.
/workspace/upstreams/orbit-smoke/.venv/bin/python -m pip install \
  --quiet --disable-pip-version-check --no-input \
  -r artifacts/gates/W01/installed-requirements.txt
/workspace/upstreams/orbit-smoke/.venv/bin/python -m pip check

cd "$upstreams/x402/typescript"
[[ "$(corepack pnpm --version)" == 11.1.1 ]] || fail 'x402 requires pnpm 11.1.1'
corepack pnpm --filter '@x402/evm...' --filter '@x402/express...' \
  --filter '@x402/fetch...' install --frozen-lockfile \
  --store-dir /workspace/upstreams/.pnpm-store --reporter=append-only
corepack pnpm --filter '@x402/evm...' --filter '@x402/express...' \
  --filter '@x402/fetch...' -r --workspace-concurrency=2 run build

# AP2 is only the signed authorization SDK. Its exact source and the resolved
# package versions from W15 are isolated from the ORBIT/Inspect environment.
export UV_CACHE_DIR="$upstreams/.uv-cache"
ap2_python="$upstreams/ap2-w15/.venv/bin/python"
if [[ ! -x "$ap2_python" ]]; then
  uv venv "$upstreams/ap2-w15/.venv"
fi
uv pip sync --strict --python "$ap2_python" \
  "$project/artifacts/gates/G6/W15/dependency-freeze.txt"
uv pip check --python "$ap2_python"

# MPP uses the official published mppx SDK, a frozen npm lockfile, and a
# content-addressed local Tempo image. No testnet or payment service is called.
cd "$project/protocols/mpp"
NPM_CONFIG_CACHE=/workspace/.npm-cache npm ci --ignore-scripts

docker_local() {
  env -u DOCKER_HOST -u DOCKER_CONTEXT -u DOCKER_TLS -u DOCKER_TLS_VERIFY \
    -u DOCKER_CERT_PATH docker --host=unix:///var/run/docker.sock "$@"
}
docker_local info --format '{{.ServerVersion}}' >/dev/null || fail 'managed local Docker daemon is unavailable'
tempo_image='ghcr.io/tempoxyz/tempo-localnet@sha256:86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b'
if ! docker_local image inspect "$tempo_image" >/dev/null 2>&1; then
  docker_local pull "$tempo_image"
fi
[[ "$(docker_local image inspect "$tempo_image" --format '{{json .RepoDigests}}')" == *"$tempo_image"* ]] || \
  fail 'local Tempo image does not match the pinned digest'

# W17 is an opt-in local protocol extension. It adds official schema/SDK and
# registry sources without contacting a PSP, public chain, or testnet.
if [[ "${SETUP_W17_PROTOCOLS:-false}" == true ]]; then
  pin_checkout w17-acp-retail https://github.com/agentic-commerce-protocol/agentic-commerce-protocol.git 7fdd78df677a94dce04c770644b0fbbb1401272b
  pin_checkout w17-ucp https://github.com/universal-commerce-protocol/ucp.git d9c18e0d27c7f6892e69243fbc13df0e3685864e
  pin_checkout w17-a2a https://github.com/a2aproject/A2A.git 7c861a597b93208de3c19357cc0d66b9f6250e9b
  pin_checkout w17-a2a-python https://github.com/a2aproject/a2a-python.git a4c4fc91a22778f3d805e5e592bf690915a33033
  pin_checkout w17-erc8004 https://github.com/erc-8004/erc-8004-contracts.git b9e466c250744a7e06b13dff9d3c2844ed64f825

  a2a_python="$upstreams/w17-a2a-venv/bin/python"
  if [[ ! -x "$a2a_python" ]]; then
    uv venv "$upstreams/w17-a2a-venv"
  fi
  uv pip sync --strict --python "$a2a_python" \
    "$project/artifacts/gates/G6/W17/a2a-dependency-freeze.txt"
  uv pip check --python "$a2a_python"

  cd "$upstreams/w17-erc8004"
  NPM_CONFIG_CACHE="$XDG_CACHE_HOME/npm" npm ci --legacy-peer-deps --no-audit --no-fund --silent
  solc24_dir="$upstreams/w17-solc24"
  solc24="$solc24_dir/soljson.js"
  if [[ ! -f "$solc24" ]]; then
    NPM_CONFIG_CACHE="$XDG_CACHE_HOME/npm" npm install --prefix "$solc24_dir" \
      --no-save --package-lock=false --ignore-scripts --no-audit --no-fund --silent solc@0.8.24
    cp "$solc24_dir/node_modules/solc/soljson.js" "$solc24"
  fi
  printf '%s  %s\n' fb59b825b7d57f9de89cd9de2415b12aab1fcc7eb2573fd2bf5c9b969eacf4d9 "$solc24" | \
    sha256sum --check --status || fail 'W17 solc@0.8.24 bytes do not match the pinned compiler'
  python3 "$project/scripts/prepare_erc8004_offline.py"
  SEPOLIA_RPC_URL=http://127.0.0.1:9 MAINNET_RPC_URL=http://127.0.0.1:9 \
    NPM_CONFIG_CACHE="$XDG_CACHE_HOME/npm" npx --no-install hardhat compile --config hardhat.local.config.ts
  printf 'setup: optional W17 ACP schemas, A2A SDK, and ERC-8004 local compiler ready\n'
fi

printf 'setup: pinned ORBIT/Inspect, ERC-8183, x402, AP2, and local MPP runtimes ready\n'
