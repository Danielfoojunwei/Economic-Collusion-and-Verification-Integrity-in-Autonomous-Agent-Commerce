# Free-model MPP decision playback on isolated local Tempo

`scripts/playback_free_mpp_decision_native.py` is an exploratory consequence check for a saved free-model MPP booking decision. It runs no remote model call. It requires a terminal study and a `PASS` from the independent semantic reviewer, then applies the frozen-order row rule in `docs/MPP_FREE_NATIVE_PLAYBACK_SELECTION_PREDECLARATION_2026-10-16.md` without choosing by verdict. The selected row, prior exclusions, raw provider message, raw auditor verdict, source file hashes, model routes, and zero-price evidence are bound to a scripted ORBIT run. ORBIT's local mock emits those saved actions; the original models are not agents inside this native run.

The playback uses the existing MPP010 native charge, calendar-service and application release code on a fresh test-only Tempo container at `127.0.0.1:19867`. `protocols/mpp/free-playback-chain-marker.mjs` records a new block marker. The copied protocol helper overlay changes only the loopback ports and chain marker; the MPP010 service, receipt verifier, compensation, and package lock bytes are unchanged. The fresh marker transaction hash can equal a historical marker hash because the bare chain and test-account nonce are deterministic; the **marker block number and block hash** distinguish the chains and are independently verified.

The free-model text prompt advertises a 1,000-unit auditor base fee. Versioned MPP010 native code fixes that fee at 10,000 units. The check price (4,000), conditional bonus (20,000), and separate client release (100,000) match numerically. The result is a local payment consequence under **nearby but different economics**, not an exact replication. MPP itself transports and charges for a service; the application's ACCEPT trigger causes the separate client release, while its controller pays the auditor base fee and ACCEPT-only bonus. Native receipt success alone says nothing about whether the booking was true.

Technical synthetic smoke controls on the fresh chain passed independent receipt re-verification: scripted `SKIP + ACCEPT` paid 30,000 auditor units and released 100,000 client units on a BAD booking; scripted `SKIP + REJECT` paid 10,000 and released zero. Those controls were fabricated only to validate plumbing and are kept under `/tmp/free-mpp-native-playback-smoke-2026-10-16-fresh` and `/tmp/free-mpp-native-playback-smoke-reject-2026-10-16-fresh`. They are not live-agent findings. The source-row playback must wait for the new 90-row study to reach a terminal semantic `PASS`; interrupted block 001 has no terminal record and remains ineligible.

Run after a terminal source study:

```bash
PYTHONPATH=src /workspace/upstreams/orbit-smoke/.venv/bin/python \
  scripts/playback_free_mpp_decision_native.py \
  --study-dir artifacts/exploratory/MPP_FREE_BAD090_2026-10-16_002 \
  --chain-marker artifacts/exploratory/free-mpp-native-playback-chain-2026-10-16/marker.json \
  --output artifacts/exploratory/free-mpp-native-decision-playback-2026-10-16-001

PYTHONPATH=src /workspace/upstreams/orbit-smoke/.venv/bin/python \
  scripts/playback_free_mpp_decision_native.py \
  --output artifacts/exploratory/free-mpp-native-decision-playback-2026-10-16-001 --verify
```

The archived historical MPP010 chain was lost during the storage incident in `docs/LOCAL_CHAIN_STORAGE_INCIDENT_2026-10-16.md`. The fresh playback chain does not re-verify or restore those older transactions.
