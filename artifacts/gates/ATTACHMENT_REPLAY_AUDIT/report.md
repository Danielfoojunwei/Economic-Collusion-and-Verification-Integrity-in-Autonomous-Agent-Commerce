# Saved Inspect attachment replay audit

**Status:** PASS for the five final G1/W05 native logs checked on 2026-10-15.
This is a read-only retrospective check; original logs and manifests were not
changed.

Inspect's default `read_eval_log()` leaves repeated message content as
`attachment://` references. The earlier W05 exporter reopened the saved file
with that default for structural comparison; it ran `assert_log_isolation` on
the in-memory evaluation log. G1 likewise checked the in-memory log before
copying native evidence. The saved-log privacy check is therefore replayed here
with `resolve_attachments=True` so actual model inputs and tool replies are
examined, not attachment placeholders.

`scripts/audit_saved_isolation.py` verified the native SHA-256 against each
original COMPLETE manifest, resolved all model-input and tool-result
attachments, and reran the ORBIT role/tool and private-oracle checks. All five
logs passed:

| Evidence | Samples | Model events | Tool events | Native SHA-256 |
| --- | ---: | ---: | ---: | --- |
| G1 scripted-run-004/always_accept | 3 | 15 | 9 | `e65037c33433f337fb5e91dd9df8930c27ebca0912977be9d8a149be915b35e9` |
| G1 scripted-run-004/always_reject | 3 | 15 | 9 | `0712dd5d7a913cc75d93523fb00f091c42588ad493e4efea981146681309dc9d` |
| G1 scripted-run-004/check | 3 | 15 | 12 | `0236ae9deda58987cd82eb72840ca6706bfaed451df5afe32da48e061ecaa1b7` |
| W05 real-run-001/reconcile-002 | 1 | 5 | 4 | `05a74a8dcbf4be2d4f913c3e88069c39f15bc9f43ad196addb62850a93e83d95` |
| W05 real-run-002/reconcile-001 | 1 | 5 | 4 | `3dc9741c506fe544d3e404d81cb9757e8ffd4e572950baa50a6624d0dcce7062` |

Reproduce locally, without provider access:

```bash
PYTHONPATH=src /workspace/upstreams/orbit-smoke/.venv/bin/python scripts/audit_saved_isolation.py
```

This audit confirms the existing marker/field isolation rules against saved
message content. Those rules do not prove that every possible paraphrase of a
private fact is absent, and the scripted G1 controls are not evidence of live
collusion. The W10 protected-receipt exporter now fails closed if attachments
are unresolved and checks the full saved log before producing evidence.
