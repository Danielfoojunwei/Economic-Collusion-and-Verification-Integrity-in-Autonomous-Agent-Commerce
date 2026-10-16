# W16 — Virtuals ACP v2 feasibility and SDK role check

**Work result: SKIP for native Virtuals job execution.** A separate offline test of the maintained SDK's `JobSession` role interface passed 3/3. That test supplied synthetic events and an inert backend; it did not create, fund, submit, evaluate, or settle a Virtuals job.

## Source commit, package, and dependency lock

- Official maintained source: `https://github.com/Virtual-Protocol/acp-node-v2`, commit `392dcc6eb17a6884c214c21aff31afa1b99f45ae` (verified with `git rev-parse HEAD`). No Git tags were advertised by `git ls-remote --tags` at inspection time. The repository's `package.json` identifies `@virtuals-protocol/acp-node-v2` version `0.1.15`.
- Installed npm package: `@virtuals-protocol/acp-node-v2@0.1.15`, release integrity `sha512-8hf92cjFiEx532PpwCTejbogqwJfCNlTn4rdYzcM96vIOvALy6hE3OJ0qU2F5H8bMPiPzdTJ8vnBIgtktPFigg==`. [package-lock.json](package-lock.json) pins its resolved dependencies; [package.json](package.json) records the exact requested version. The lock SHA-256 and installed `jobSession.js` SHA-256 are in [source-inspection.json](source-inspection.json). The npm package version matches the Git source metadata, but npm-to-Git source identity was not independently proven.
- Package metadata declares `ISC`; no `LICENSE`, `COPYING`, or `NOTICE` file is tracked at the pinned source commit. No upstream code was copied into this project. Clarify distribution terms before copying any substantial source.

## Commands and results

```bash
git -C /workspace/upstreams/virtuals-acp-feasibility rev-parse HEAD
git ls-remote --tags https://github.com/Virtual-Protocol/acp-node-v2
npm_config_cache=/workspace/upstreams/.npm-cache npm view @virtuals-protocol/acp-node-v2@0.1.15 version license dist.integrity --json
npm_config_cache=/workspace/upstreams/.npm-cache npm install --prefix /workspace/upstreams/virtuals-acp-w16 --ignore-scripts --no-audit --no-fund --save-exact @virtuals-protocol/acp-node-v2@0.1.15
VIRTUALS_ACP_INSTALL=/workspace/upstreams/virtuals-acp-w16 node --test tests/virtuals_acp_sdk.test.mjs
```

[sdk-role-test.log](sdk-role-test.log) records 3 PASS, 0 FAIL. The tests imported the published SDK and checked role/status tool availability, rejection of wrong-role `executeTool` calls before a backend call, and event responder selection. The SDK rejected local Anvil chain ID `31337` because that ID has no configured ACP contract. The successful evaluator `executeTool` call reached only the injected inert backend; it produced no chain transaction. The upstream package's `npm test` script is an explicit placeholder that exits 1, so it was not treated as an upstream conformance suite.

## Native SKIP cause and protocol boundary

The SDK's official examples require agents registered in the Virtuals Service Registry, separate managed buyer/seller wallet IDs, Privy P-256 authorization signer keys, and a Virtuals backend that authenticates signed messages and streams job events over SSE. The required example wallet and signer variables were absent in this runner (names only recorded in `source-inspection.json`). No corresponding credentials were created or inspected. The pinned SDK configures deployed contract addresses only for specific EVM/Solana networks; no deployable Solidity contract source is tracked in this repository. A local Anvil run would therefore require a different contract/backend implementation and would not be the maintained Virtuals native job flow. No testnet traffic was authorized for W16.

The Virtuals protocol supports separate client, provider, and evaluator roles in its source. Its example documents a consequential configuration: omitting `evaluatorAddress` selects the zero-address skip-evaluation mode, which auto-completes on submit. This was inspected in source documentation, not tested with a native transaction. The SDK tool interface is a convenience gate; direct action methods and the actual deployed contract require separate role checks. No wrong-role receipt, token balance, payout, refund, or semantic work verification was observed.

Virtuals ACP v2 is an **agent job and evaluator** protocol. It is distinct from the OpenAI/Stripe Agentic Commerce Protocol checkout specifications, which are a separate W17 item. Neither is interchangeable with ERC-8183 or an HTTP resource charge.

## Work-order record

- **Work ID:** W16; G6 broader-protocol native item `SKIP`, SDK-only role slice `PASS`.
- **Source commit(s) + dependency lock:** Git commit and exact npm release above; local dependency lock attached.
- **Execution tier model / payment:** `NOT_APPLICABLE` / `NOT_RUN`; zero native transactions.
- **Tests PASS / FAIL / SKIP:** 3 / 0 / 1 native flow skipped for credentials, backend, supported chain and testnet authorization.
- **Delivered paths:** `tests/virtuals_acp_sdk.test.mjs` and this W16 evidence directory.
- **Threat model:** untrusted agent may ask the SDK to take a role-ineligible action; only the SDK tool interface was exercised offline. Contract and backend enforcement remain unverified.
- **Confounds and limitations:** synthetic events, inert backend, no source-to-npm tarball identity proof, no payment or real model decision.
- **Evidence that protocol was native:** none; SDK-only test is explicitly `MOCK_BACKEND`, and the native item is `SKIP`.
- **Backwards compatibility or migration:** no project runtime path was changed. The maintained v2 API uses `AcpAgent` and `JobSession`; the deprecated v1 `acp-node` API is not used.
- **Decision or owner approval required:** genuine native work would require registry identities, managed signer setup, backend access, and separate authorization for testnet traffic. No such work was attempted.
- **Next eligible work order:** W17, with each protocol classified and pinned separately; do not infer a Virtuals native PASS from this offline test.
