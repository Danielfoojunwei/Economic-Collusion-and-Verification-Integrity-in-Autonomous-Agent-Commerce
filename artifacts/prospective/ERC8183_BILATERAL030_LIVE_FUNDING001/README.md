# Two live local pre-view funding confirmations

`report.json` records two disposable Anvil checks of the revised BILATERAL030 funding path. For each privately assigned row, the controller wrote a public-only archive after job setup and before any agent choice. The separate funding verifier then read the exact archive and queried the still-running loopback chain with read-only RPC methods. It returned `FUNDING_LIVE_CONFIRMED` for a provider-funded 5,000,000-unit bonus and for an assigned zero-bonus job. No model was called or shown these proofs. The MockUSDC units had no real value.

The exact bytes that **could** be placed in each role's model input are `funded/funding-attestation.json` and `unfunded/funding-attestation.json`, respectively. They are candidates for a later handoff, not evidence of model exposure. The runner must bind their archive and public-prefix hashes to both provider and auditor inputs, including in CHANNEL and NO_CONTACT arms, before making that exposure claim. The read-only attestation does not prove the invoice is correct, an early claim was approved, or that agents colluded.

The first local invocation exited with code 1 because its harness expected `FUNDING_VERIFIED` while the verifier correctly returned `FUNDING_LIVE_CONFIRMED`. `report.json` records this failure and its archive hash. A fresh two-case invocation then passed. Chain tips, source hashes, exact archive hashes, and exact attestation hashes for the passing invocation are in `report.json`. The chains were stopped afterward, so the saved receipts can be replayed but cannot be live queried again.

The archives, attestations and report exclude condition group, private truth and protected buyer records. The private planner seed and native partial files are not included here.
