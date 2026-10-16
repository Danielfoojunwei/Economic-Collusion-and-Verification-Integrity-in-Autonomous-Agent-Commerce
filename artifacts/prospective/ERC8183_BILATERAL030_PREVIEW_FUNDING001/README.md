# Public pre-view funding transcripts

These two source-only archives were written from fresh, disposable local ERC-8183 jobs by `bilateral030_funding_archive.write_funding_archive()` before any agent choice. `funded.json` contains 19 raw setup/funding transactions and a 5,000,000-unit provider deposit to the first-claim hook. `unfunded.json` contains 17 raw setup/funding transactions and the assigned absence of that bonus. Both use valueless local MockUSDC and public-only report descriptions. They contain no protected buyer ledger, model messages, decisions or research outcome.

| File | SHA-256 |
| --- | --- |
| `funded.json` | `d9d27afdb85ca143ff6d186f428fbd4446d89602de465ed7f74b4f3ae3a377be` |
| `unfunded.json` | `9e95916c5ea3f26f6cd52dc76d43c530a74a6e28c9d818a4965960a31ad44bec` |

The archives are controller records. They do not independently verify funding until a separate read-only verifier replays the source pins, calldata, receipt events and balances. They do not establish model behavior or collusion.
