# ORBIT004 local-chain storage preflight, 2026-10-16

This records a cloud runtime incident **before any ORBIT004 model call or experimental output directory existed**. The native transactions in the first two discarded chains were only one-time 1,014-unit valueless marker transfers, not auditor checks, bonuses, or buyer releases. They must not be counted as experimental episodes.

The first bare Tempo container, `free-mpp-live-orbit004-localnet` (`4996fd097d1e…`), was started at RPC port 19997 and passed the fresh-chain marker check. At about 11:12 UTC the root filesystem had zero available bytes. The ORBIT004 parent printed `OSError` during preflight **before** creating `artifacts/exploratory/FREE_MPP_NATIVE_ORBIT004_2026-10-16_001`; there was no worker intent, Inspect evaluation, or remote POST. The chain was stopped, its container and anonymous volume removed, and root free space returned to about 2.1 GB. The marker and Docker mount metadata were preserved in [the preflight incident record](../artifacts/native-chain-backups/orbit004-preflight/free-orbit004-disk-preflight-incident.json).

A second fresh chain used a Docker bind mount at `/tmp/free-orbit004-localnet-data` and another one-time marker. Its container again exhausted the root filesystem; the bind mount did not place the container's other writable layers on the shell's separate `/tmp` filesystem. Its marker is [archived](../artifacts/native-chain-backups/orbit004-preflight/free-orbit004-chain-marker-attempt002.json). The container was stopped and removed before an experimental output directory or model call; root free space returned to about 2.1 GB.

To make a stable local-chain run possible while retaining historical evidence, the stopped `mpp009-pressure-localnet` container (`c405873046cd…`) was backed up before removal. Its Docker root filesystem and attached `/data` volume were streamed into separate gzip archives, `gzip -t` verified, copied into [native-chain backups](../artifacts/native-chain-backups/), and SHA-256 matched after copying:

| Archived component | SHA-256 | Compressed size |
| --- | --- | ---: |
| `mpp009-pressure-localnet-rootfs-2026-10-16.tar.gz` | `e81ce2a030493770a7ae0cb6a856459c4a8cab3f26cd064bfcf805ff4e9a8f8c` | 397 MB |
| `mpp009-pressure-localnet-volume-2026-10-16.tar.gz` | `5931c1211c3122f7c7d7c5c5fbbcbe3d8cd37a5394fdda011fd0c19c68552a32` | 79 MB |

Only after those checks was that stopped container removed with its anonymous volume. Root free space increased from about 2.1 GB to 7.0 GB. Its original RPC chain is no longer running or directly replayable. The verified archives retain its data for a future restoration attempt; **they do not by themselves prove that restoration or historical RPC re-verification has succeeded**. Historical receipt JSON in the research tree was not modified.

A third fresh chain was then started with the same pinned Tempo image and port, and its [new marker](../artifacts/native-chain-backups/orbit004-preflight/free-orbit004-chain-marker-attempt003.json) passed against an empty treasury. About 4.6 GB remained free after startup. This is the **only** chain marker passed to the sealed ORBIT004 experiment. The first two marker receipts are preflight artifacts and are not interchangeable with it. The experiment's own terminal record and independent native review govern any later model or payment claim.

An unattached anonymous Tempo volume created at 06:36 UTC (`459db91a…`) was also compressed, `gzip -t` verified, and copied to a local-only archive (SHA-256 `6f6adf65253ab8826815c773333e62b9eec4395c530611e5699c5cfc77ff243a`). It was then removed. That volume had no attached container, and its removal did not measurably increase root free space. The [backup inventory](../artifacts/native-chain-backups/README.md) records why the three raw operational snapshots are excluded from public Git while their preflight marker JSON remains committed.
