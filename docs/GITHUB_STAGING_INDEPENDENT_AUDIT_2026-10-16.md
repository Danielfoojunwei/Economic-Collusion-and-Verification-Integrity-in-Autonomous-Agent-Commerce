# Independent pre-stage audit for GitHub publication

Read-only audit on 2026-10-16. I did not stage, commit, push, edit experiment evidence, or make model/payment calls. Scope: the two modified docs and 698 untracked paths visible before this note was written. The user's request to publish everything is understood as including the research code, assignments, raw traces, receipts, and reviews. Three operational chain backups require special handling because they contain sensitive node state.

## Immediate staging decision

**Do not run an indiscriminate `git add -A`.** The untracked set is 527,230,252 bytes. Three `artifacts/native-chain-backups/*.tar.gz` files account for 517,494,625 bytes; the remaining research candidates are about 9.7 MB. Seven absolute `node_modules` symlinks also appear among untracked files.

| Raw backup | Compressed bytes | GitHub/LFS assessment |
| --- | ---: | --- |
| `artifacts/native-chain-backups/mpp009-pressure-localnet-rootfs-2026-10-16.tar.gz` | 415,752,799 | Exceeds GitHub's ordinary 100 MB per-file limit. Contains a full Docker root filesystem, `/etc/shadow`, and about 1.15 GB of uncompressed reth logs. Do not publish raw without a complete content/security review and appropriate sanitization. |
| `artifacts/native-chain-backups/mpp009-pressure-localnet-volume-2026-10-16.tar.gz` | 82,809,918 | Below 100 MB, but contains live-format `data/discovery-secret` and `data/jwt.hex` node credential files. Do not publish raw. |
| `artifacts/native-chain-backups/orphan-tempo-volume-459db91a-2026-10-16.tar.gz` | 18,931,908 | Also contains `data/discovery-secret` and `data/jwt.hex`. Do not publish raw. |

`git-lfs/3.6.1` is installed, but no `.gitattributes` filter applies to these files. LFS would address the size limit, **not** the disclosure of embedded node credentials or filesystem state. A sanitized, independently verified derivative could be published via LFS with its changed hash and clear provenance; original SHA-256 values and retention location should remain recorded. The unmodified raw backups can be preserved outside the public Git repository. A strongly encrypted backup stored in LFS would require separate key custody and quota review; ordinary LFS of the raw archives is not a safe shortcut. This audit did not read every byte of the 2.4 GB uncompressed rootfs or its logs, so it cannot certify the absence of additional secrets.

I recomputed the raw backup SHA-256 values and matched the storage RCA: rootfs `e81ce2a030493770a7ae0cb6a856459c4a8cab3f26cd064bfcf805ff4e9a8f8c`, mpp009 volume `5931c1211c3122f7c7d7c5c5fbbcbe3d8cd37a5394fdda011fd0c19c68552a32`, and orphan volume `6f6adf65253ab8826815c773333e62b9eec4395c530611e5699c5cfc77ff243a`.

**Stage the small `artifacts/native-chain-backups/orbit004-preflight/` JSON marker and incident records.** Excluding the entire backup directory would discard cited preflight evidence. [The storage RCA](ORBIT004_CHAIN_PREFLIGHT_STORAGE_RCA_2026-10-16.md) presently links directly to the orphan tarball; if the tarball stays local-only, change that link to a checked SHA/size inventory or mark it as locally retained before publishing. The same document's table already records the two mpp009 backup hashes.

## Symlinks and generated dependencies

Seven untracked `artifacts/exploratory/**/native-overlay/protocols/mpp/node_modules` entries are **absolute symlinks** back to this workspace's `protocols/mpp/node_modules`. Git would store their machine-specific absolute targets as link text, leaving broken links on other clones and exposing a local workspace path. Exclude these seven entries from staging, or replace them with a portable manifest that records the link target role and package-lock digest. Keep the overlaid source and `package-lock.json` files, which are small and contribute to reproducibility. Do not add the real `protocols/mpp/node_modules` dependency tree.

## Credential and evidence checks

- Scanned 690 small, non-symlink candidate files plus the two modified docs for full OpenRouter/OpenAI key patterns, cloud access keys, bearer headers, PEM private keys, and obvious API-key assignments. No positive secret pattern was found. A loose `sk-` matcher flagged `task-...` IDs; checking preceding bytes showed those were false positives. This is pattern screening, not a guarantee against arbitrary hidden secrets.
- Decoded all six untracked Inspect `.eval` archives with Inspect and applied the same credential-pattern screening to their JSON representation; no matches. Preserve these archives, since they are the primary raw native-agent traces and are individually small.
- The two untracked OpenRouter billing CSVs contain hour/session/request-count/usage columns, no detected email or full key prefix. They remain account-level usage evidence and may reveal session identifiers; publication is a privacy decision, not a code-secret finding.
- Checked 345 relative Markdown links in the newly added or modified Markdown files: all resolved in this workspace before exclusions. The direct orphan-backup link above is the one that would become absent in a public clone if that tarball is omitted.
- After excluding the three archives and seven absolute symlinks, there is no remaining untracked file over 100 MB; the largest remaining file observed was a roughly 629 KB AP2 assignment manifest. Include terminal `STOPPED` files, assignments, row indexes, raw `.eval` logs, native receipts, independent reviews, and both modified evidence/billing docs so the public account is auditable. Do not replace stops with only successful rows.

**Recommended publication set:** stage all research code/tests/docs and all small prospective, exploratory, review, billing, and native-preflight evidence; exclude the three raw backup tarballs and seven absolute dependency symlinks; record exact backup hashes/retention and adjust the orphan-backup link. Review the resulting staged file list and scan staged blobs before commit. This preserves the complete *scientific* record in GitHub while keeping operational secrets and nonportable dependency links out of the public history.
