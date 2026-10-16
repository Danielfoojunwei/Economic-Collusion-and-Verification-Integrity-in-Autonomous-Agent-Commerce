# W01 — upstream pinning and ORBIT runtime smoke

**Status: PASS for W01 and A02 runtime plumbing. G1 remains pending.** The official ORBIT v1.0.3 wheel executed a native Inspect Task with two scripted agents, native tool events, and saved `.eval` logs. This establishes installation and event plumbing only. No live model, worker/auditor research episode, verification price, or payment protocol ran.

## Source pins and licensing

| Component | Official source and inspected revision | License finding | Runtime finding |
| --- | --- | --- | --- |
| ORBIT | [wlanderson0/orbit](https://github.com/wlanderson0/orbit), release `v1.0.3`, commit `588b3035f92450ec4f0496bb8b629daa205e84c7` | Apache-2.0 in `LICENSE`, `NOTICE`, and `pyproject.toml` | Verified release wheel installed; `multi_agent_task` returns an Inspect `Task`. |
| Inspect AI | [UKGovernmentBEIS/inspect_ai](https://github.com/UKGovernmentBEIS/inspect_ai), tag `0.3.263`, commit `7aa7343e4a14fa7be07e5a09c7431df5e88c17ee` | MIT in `LICENSE` and `pyproject.toml` | Installed package `0.3.263`, ORBIT's tested lock version. |
| Colosseum | [umass-ai-safety/colosseum](https://github.com/umass-ai-safety/colosseum), commit `b077fe7e2f10566e92156cc12e06ffb2aac54790` | No tracked `LICENSE`, `COPYING`, or `NOTICE` file or package license field was found at this revision. Code reuse permission is unresolved. | Source inspected as a methodology reference only. It was neither installed nor run. Its `pyproject.toml` declares `terrarium-agents[providers,science,plots]==0.1.1`. |

The supplied handover source register described ORBIT `v1.0.2`; the official README and release now identify `v1.0.3`. ORBIT's release manifest names the same source commit as the checkout. Its published `SHA256SUMS` verified the wheel SHA-256 `4be987cbc9ac3ed068fdf8208b3e20012ee8dd3d325547bf7b07afa9ffe2e642` and source archive SHA-256 `0a9d231051ba5c620f0a86fa66b2e0a7b687ee8a21eb8e35207e84d1955c1c8c`. The Inspect wheel selected by pip had SHA-256 `503e7ff509d77fcdf65989027a19fea966fb668deb88a234468c3290964fd86a`. The release checksum list and manifest are copied here for review; they are publisher hosted checks, not an independent signature.

ORBIT's public authoring API was inspected in `orbit/tasks/multi_agent.py`, `orbit/__init__.py`, `docs/authoring.md`, and `examples/first_benchmark.py`. `AgentSpec` and `SetupConfig` define agents; `ExecutionConfig` and `SchedulerConfig` determine activations; `ToolFactory` supplies native Inspect tools with trusted agent identity. Inspect owns samples, scorer, stores, `.eval` logs, and model calls. The official installation path is the checked GitHub release wheel. The PyPI command `pip install orbit` refers to an unrelated project and was not used.

## Commands actually run

The Git clones live outside the project at `/workspace/upstreams/{orbit,inspect_ai,colosseum}`. I verified their remotes and exact revisions with `git remote get-url origin`, `git rev-parse HEAD`, and `git tag --points-at HEAD`; the Colosseum license-file check used `git ls-tree -r --name-only HEAD`. The ORBIT install and smoke ran under Python 3.12.14:

```bash
git clone --depth 1 --branch v1.0.3 https://github.com/wlanderson0/orbit /workspace/upstreams/orbit
cd /workspace/upstreams/orbit-release
orbit_release_url=https://github.com/wlanderson0/orbit/releases/download/v1.0.3
curl --fail --fail-early --location --remote-name-all \
  "$orbit_release_url/orbit-1.0.3-py3-none-any.whl" \
  "$orbit_release_url/orbit-1.0.3.tar.gz" \
  "$orbit_release_url/SHA256SUMS" \
  "$orbit_release_url/release-manifest.json"
sha256sum -c SHA256SUMS
mkdir -p /workspace/upstreams/orbit-smoke
python3 -m venv /workspace/upstreams/orbit-smoke/.venv
tar -xzf /workspace/upstreams/orbit-release/orbit-1.0.3.tar.gz \
  --strip-components=2 -C /workspace/upstreams/orbit-smoke \
  orbit-1.0.3/examples/first_benchmark.py
/workspace/upstreams/orbit-smoke/.venv/bin/python -m pip install \
  --disable-pip-version-check --no-input \
  --report /workspace/upstreams/orbit-smoke/install-report.json \
  'inspect-ai==0.3.263' \
  /workspace/upstreams/orbit-release/orbit-1.0.3-py3-none-any.whl
/workspace/upstreams/orbit-smoke/.venv/bin/python -m pip check
```

The first positive smoke attempt exited 1 **before evaluation** because Inspect's `platformdirs` tried to create `/home/agent/.local/share/inspect_ai` on a read-only filesystem. No score or log came from that attempt. The supported XDG path override fixed the local write location. From `/workspace/upstreams/orbit-smoke`, both of these commands exited 0:

```bash
XDG_DATA_HOME=/workspace/upstreams/orbit-smoke/.local/share \
XDG_CACHE_HOME=/workspace/upstreams/orbit-smoke/.cache \
XDG_CONFIG_HOME=/workspace/upstreams/orbit-smoke/.config \
.venv/bin/python first_benchmark.py \
  --log-dir /workspace/upstreams/orbit-smoke/logs/positive

XDG_DATA_HOME=/workspace/upstreams/orbit-smoke/.local/share \
XDG_CACHE_HOME=/workspace/upstreams/orbit-smoke/.cache \
XDG_CONFIG_HOME=/workspace/upstreams/orbit-smoke/.config \
.venv/bin/python first_benchmark.py --negative-control \
  --log-dir /workspace/upstreams/orbit-smoke/logs/negative
```

`pip check` returned “No broken requirements found.” The installed versions are frozen in [installed-requirements.txt](installed-requirements.txt). Pip selected OpenAI SDK `3.31.0`; ORBIT's `uv.lock` pins its tested SDK to `3.13.0`. The offline controls passed with `3.31.0`, but live provider compatibility at that version was not exercised.

## Results and independent evidence

The model execution tier was **`SCRIPTED_SIMULATION`** (`mockllm/first-benchmark`); the transaction tier was **not applicable**. No external model API or paid service was called.

| Control | Inspect status | `inventory_score / mean` | Sample epochs | Errors / limits | Native events |
| --- | --- | ---: | ---: | ---: | --- |
| Positive | `success` | 1 | 4/4 | 0 / 0 | 16 model, 8 `reserve_units`, 4 `channel_post`, 4 score; Alice and Bob spans present. |
| Negative, Bob claims completion without reserving | `success` | 0 | 4/4 | 0 / 0 | 16 model, 4 `reserve_units`, 4 `channel_post`, 4 score; Alice and Bob spans present. |

The score comes from the example's native Inspect scorer reading sample-local `InventoryState` after tool actions. It does not trust the agents' completion text. I reloaded both saved `.eval` files with `inspect_ai.log.read_eval_log` and counted actual event classes, tool functions, scores, sample errors, and limits; see [smoke-evidence.json](smoke-evidence.json). The native logs are [positive.eval](logs/positive.eval) (SHA-256 `2d690e453c48721b0b6990ffcc9e8b2d8d68a2150dd4592a2a9d15c7eb9c0aa0`) and [negative.eval](logs/negative.eval) (SHA-256 `a4460018615ed5f0ca0f8c0dfc44d0efaa9595fb474c5e6b32900bf915a65fb9`).

## Limits and next work

The inventory example uses separate scheduled conversations, but its channel rules do not isolate shared files or trusted Python tools. A research auditor must receive only scoped tools, with hidden truth kept behind a separate scorer or an authorized paid check. This smoke does not establish oracle isolation, checking economics, worker/auditor behavior, collusion, native payment settlement, or a real local model result. Colosseum's runtime and its Terrarium/CoLLAB dependencies were not installed or tested; no Colosseum code was copied.

**Acceptance:** A02 PASS for genuine ORBIT/Inspect runtime evidence. A03–A07 SKIP pending the worker/auditor experiment and local model prerequisite. G1 is not yet PASS. No owner decision is needed for the next offline work order. Paid remote model use and testnet activity remain outside this work order and require separate owner authorization under `planning/STAGE_GATES.md`.

**Files delivered:** `UPSTREAM_PINNED.json`; this report; `smoke-evidence.json`; two native Inspect logs; ORBIT release manifest and checksums; installed dependency snapshot. `legacy/` and project configuration were not changed. **Next eligible work order: W02**, a small native ORBIT/Inspect worker and auditor task with an independent task oracle to be completed under G1.
