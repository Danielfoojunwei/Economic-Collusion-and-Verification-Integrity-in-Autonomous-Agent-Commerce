# Local Tempo chain storage incident — 2026-10-16

This note records a runtime failure during exploratory decision-conditioned MPP playback. It does not change any saved model row, model bill, protocol receipt JSON, or experimental inference.

## Observed failure

- The four pre-existing bare Tempo localnets reached block `302398` (`0x49d3e`) and stopped advancing. The MPP010 log repeatedly reported `failed decoding boundary block extra data as DKG outcome: Unexpected End-of-Buffer`. A new local MPP010 `prepare` transaction `0xf65362f7ec02c82131941b013573861b72304a1a627fc80c844c653a78c6f5e8` stayed pending and its receipt timed out. The exploratory playback produced no native decision or payment evidence on this chain.
- The root filesystem then had zero available bytes. The live free-model MPP block later stopped at 16 indexed rows with `ENOSPC`. Those rows and the frozen index remain in `artifacts/exploratory/MPP_FREE_BAD090_2026-10-16_001`; unattempted assignments must stay unattempted in that block.
- Docker's image was `ghcr.io/tempoxyz/tempo-localnet@sha256:86f199f161be85d3610d990e5bc2653ece29de3ee9c91e8c8e768cf2b8c05c3b`, local image ID `sha256:085da3bc19f0d51ab2b0206e4d4d7ccdf788dd2f0987b044f1243c87e5e21093`.

## Storage action and consequence

- A zero-link, anonymous Docker volume `b96b685470efd47c3f07d632da6af920bdbfabe7ca3b5283bf8582102dc2c78f` (created 2026-10-15 15:04:40 UTC, Docker-reported size 4.296 GB) was removed. It had no attached container; the root filesystem still reported zero available bytes afterward.
- The old `open-mpp-booking-service-debug` container (ID `670a67485b4b2f5084606652d273632c471d9758baf442865b32f5bc88785400`, loopback RPC port `19567`) and its exclusive anonymous volume `5c129b51b00a8f4ba2472f7cc476393a8c4367aaaf3220feb8c7265d6229bb83` (created 2026-10-15 12:28:24 UTC) were removed. A full chain-data backup did **not** succeed. Saved receipt JSON for this chain remains under `artifacts/prospective/mpp-booking-service-stress-corrected/` and `artifacts/gates/MPP008/`.
- Immediately before that removal, the four stalled containers were issued a stop command to halt disk growth. Docker automatically removed `mpp010-pressure-localnet` (ID `b6ba4a64e5b9`, formerly RPC port `19767`, volume `64e852a7cdff79fba3fa54cbbb13c7126260b5051e68b2feac064eb43a51f0e1`) and `mpp009-fresh-funding-control` (ID `9f18d5b7eda9`, formerly RPC port `19677`, volume `e0aa3077491f6aad0442bc76673ad42bb95a374d919949fd941a9`) together with their anonymous volumes. This auto-removal was unexpected and was reported as soon as it was observed. `mpp009-pressure-localnet` (ID `c405873046cd`, volume `94482cc295a47c2f51254950efdc96940bb769b9059d0ffa85225b468938f85f`) remained exited with its volume intact.
- After cleanup, the root filesystem reported 16 GB available. No remote model or real payment call was made by the local playback attempt.

## Evidence limit

The existing archived native receipt files and Inspect traces have not been altered. Historical RPC re-verification for the removed MPP010, MPP009 fresh-funding, and debug chains is now unavailable; a fresh local chain cannot authenticate those old transaction hashes. Any report using these older artifacts must state that the archived receipts can be read and hashed but cannot currently be replayed against their original chain. Fresh playback, if run, must use a new isolated chain and a new marker, and must never be presented as restoration or verification of the old chain.

## Cloud environment restoration at 11:05 UTC

The ORBIT/Inspect virtual environment at `/workspace/upstreams/orbit-smoke/.venv` is now a real directory in the persistent workspace. It was copied byte-for-byte from the preserved temporary environment while the ACP model process was running, compared with `diff -qr` (no differences), and swapped into place only after that process ended. A post-swap import check loaded Inspect AI 0.3.263, ORBIT, and httpx 0.28.1. The former temporary symlink was removed; the temporary source copy remains outside the workspace and is not needed by the configured interpreter. This change affects environment persistence, not archived experiment results. At the check, `/workspace` had about 2.1 GB free. The four newer exploratory Tempo containers were stopped but preserved for receipt replay; no Docker pruning was performed.
