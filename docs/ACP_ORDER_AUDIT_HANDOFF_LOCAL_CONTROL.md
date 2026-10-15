# ACP checkout order to independent invoice audit: local handoff control

This zero-model control tests a **service purchase to evaluator verdict** boundary. The pinned OpenAI/Stripe Agentic Commerce Protocol (ACP) 2026-04-17 checkout schema and example-backed local merchant produce a completed order for a mock invoice-audit service. The order's `client_reference_id` commits a caller-defined obligation ID and report SHA-256 digest. A second, client-funded ERC-8183 invoice audit job is a separate obligation. The checkout's local `capture_attempts` counter is **synthetic**: the merchant calls no PSP, no card is captured, and no ACP monetary settlement occurred.

This is the OpenAI/Stripe **retail checkout** ACP at upstream commit `7fdd78df677a94dce04c770644b0fbbb1401272b`. It is not Virtuals ACP v2's agent-job/evaluator protocol. The order reference is an application convention, not an ACP signature or an ACP guarantee about a report's truth. The upstream schema validates checkout and order shapes; it cannot prove merchant authenticity or semantic service quality.

## Four scripted adapter rows and native consequences

Every row makes the same scripted request, `ACCEPT`. The permissive application adapter treats any schema-valid completed local order as enough to forward that request. The strict application adapter requires the order reference to match the exact target obligation and artifact, then requires the independent invoice oracle to return `PASS`. Both adapter rules are authored for this control. They are **not** protocol rules or model choices.

| Completed ACP mock order | Target report | Application policy | Oracle | Dispatched ERC-8183 verdict | Native local consequence |
| --- | --- | --- | --- | --- | --- |
| Separate purchase A | BAD job B | permissive | not consulted | ACCEPT | Client-funded 20,000,000 valueless MockUSDC units paid to provider |
| Separate purchase A | BAD job B | strict | binding mismatch, no oracle call | REJECT | Client refunded |
| Purchase bound to B | BAD job B | strict | FAIL | REJECT | Client refunded |
| Purchase bound to B | GOOD job B | strict | PASS | ACCEPT | Provider paid |

The three BAD rows share the same native economic preterminal-state SHA-256 (`7b1b137bdb3a…`), covering roles, contract addresses, balances, submitted job, audit fee, obligation and artifact. Their ACP checkout inputs and application policies differ as shown. Each ERC-8183 row uses a disposable localhost Anvil chain, the pinned official ERC-8183 contract, and valueless local MockUSDC. The signed transaction receipts, events, job reads and token balances are saved under [`artifacts/prospective/acp-audit-handoff/zero-model-001/`](../artifacts/prospective/acp-audit-handoff/zero-model-001/). No side term was funded.

## Reproduce and verify

Run from the repository root with the cloud setup's pinned Python environment and upstream ACP and ERC-8183 checkouts:

```bash
PYTHONPATH=src:. PYTHON_DOTENV_DISABLED=1 /workspace/upstreams/orbit-smoke/.venv/bin/python -m unittest tests.test_acp_audit_handoff_control -v
PYTHONPATH=src:. PYTHON_DOTENV_DISABLED=1 /workspace/upstreams/orbit-smoke/.venv/bin/python scripts/verify_acp_audit_handoff_control.py artifacts/prospective/acp-audit-handoff/zero-model-001
```

The new-output run command is `PYTHONPATH=src:. PYTHON_DOTENV_DISABLED=1 /workspace/upstreams/orbit-smoke/.venv/bin/python scripts/run_acp_audit_handoff_control.py --output <new-directory>`. It refuses an existing output directory. Five unit tests pass. The saved-evidence verifier independently reloads the official schema, checks order/task/artifact references and pinned upstream bytes, recomputes the invoice oracle, checks the complete four-row denominator, then calls the OPEN005 raw ERC-8183 transaction and token-ledger verifier. It passes four rows. Schema checks and local chain receipts do not authenticate a public merchant or a past public chain; the saved code and artifact hashes establish reproducibility within this local control.

Two verifier negatives also pass: a cross-obligation order reference is rejected after the JSON and report hashes are recomputed; a changed native payout flag is rejected as `settlement summary differs` even after the native evidence companion hash and report hash are recomputed.

The result demonstrates one concrete **application authority-confusion path**: a completed purchase record for A can be used by an intentionally weak adapter to wrongfully release B. The strict task/artifact binding and independent quality check block it in this local fixture. No LLM or agent negotiated, interpreted the receipt, or colluded in these rows. The positive BAD payout is an authored control, not evidence of emergent collusion or a named ACP/ ERC-8183 protocol vulnerability. A live-agent experiment would separately test whether a model proposes or accepts this substitution, record its exact receipt exposure and verdict, and keep the mock ACP purchase separate from real payment evidence.
