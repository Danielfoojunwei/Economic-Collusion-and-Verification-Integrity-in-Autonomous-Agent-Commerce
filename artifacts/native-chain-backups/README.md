# Local-only Docker recovery archives

The three raw `.tar.gz` files named below remain in this workspace and are excluded from GitHub. They are operational backups made during the ORBIT004 disk incident, **not scientific outcome files**. The two volume snapshots contain Tempo node credential files (`data/discovery-secret` and `data/jwt.hex`); the root filesystem snapshot includes `/etc/shadow` and large node logs. Git LFS would solve the largest file's size limit but would publish those contents. The source, assignments, Inspect traces, row decisions, receipts, preflight markers, and independent reviews are committed separately.

| Local archive | Compressed bytes | SHA-256 |
| --- | ---: | --- |
| `mpp009-pressure-localnet-rootfs-2026-10-16.tar.gz` | 415752799 | `e81ce2a030493770a7ae0cb6a856459c4a8cab3f26cd064bfcf805ff4e9a8f8c` |
| `mpp009-pressure-localnet-volume-2026-10-16.tar.gz` | 82809918 | `5931c1211c3122f7c7d7c5c5fbbcbe3d8cd37a5394fdda011fd0c19c68552a32` |
| `orphan-tempo-volume-459db91a-2026-10-16.tar.gz` | 18931908 | `6f6adf65253ab8826815c773333e62b9eec4395c530611e5699c5cfc77ff243a` |

These hashes identify the retained originals; they are not downloadable GitHub artifacts. Any later public derivative must be sanitized and independently checked, with a new hash. The machine-specific `native-overlay/.../node_modules` symlinks are also excluded; `package-lock.json` and overlaid source are retained for rebuilding dependencies.
