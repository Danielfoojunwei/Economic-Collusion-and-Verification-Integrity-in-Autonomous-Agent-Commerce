# W15 — AP2 v0.2.0 signed mandate conformance

**Work result: PASS (local authorization slice).** G6 as a whole remains separate. No payment was initiated, no PSP or credential was used, and no task work was checked by AP2. The protocol's role here is delegated spending authorization.

## Source, license, and isolated install

- Official source: `https://github.com/google-agentic-commerce/AP2`, tag `v0.2.0`, commit `b4587ac1d055888a73b4b21750973cffba961793` (verified with `git rev-parse HEAD`). Root `LICENSE` and `pyproject.toml` declare Apache-2.0.
- The tag is `v0.2.0` while its Python distribution metadata says `ap2==0.1`; the exact Git commit identifies the SDK tested here. No upstream code was copied into this project.
- Actual installation used an isolated worktree and venv outside the project:

```bash
git -C /workspace/upstreams/ap2-feasibility worktree add --detach /workspace/upstreams/ap2-w15 b4587ac1d055888a73b4b21750973cffba961793
UV_CACHE_DIR=/workspace/upstreams/.uv-cache uv venv /workspace/upstreams/ap2-w15/.venv
UV_CACHE_DIR=/workspace/upstreams/.uv-cache uv pip install --python /workspace/upstreams/ap2-w15/.venv/bin/python -e /workspace/upstreams/ap2-w15
```

For a clean cloud setup, clone the official repository at tag `v0.2.0`, assert the commit above, then run the two `uv` commands. [dependency-freeze.txt](dependency-freeze.txt) records the resolved transitive versions. The SDK pins `cryptography==46.0.5`, `jwcrypto==1.5.6`, `pydantic==2.12.5`, and `sd-jwt==0.10.4`. No production secrets or real payment instruments are needed.

## Commands and evidence

```bash
/workspace/upstreams/ap2-w15/.venv/bin/python scripts/run_ap2_local.py
/workspace/upstreams/ap2-w15/.venv/bin/python -m unittest tests.test_ap2_local -v
/workspace/upstreams/ap2-w15/.venv/bin/python -m pytest /workspace/upstreams/ap2-w15/code/sdk/python/ap2/tests/payment_mandate_chain_tests.py /workspace/upstreams/ap2-w15/code/sdk/python/ap2/tests/mandate_presentation_tests.py -q
python -m unittest tests.test_ap2_local -v
```

- [conformance.json](conformance.json): 17/17 expected outcomes; official `MandateClient.create`, `present`, and `verify` plus `PaymentMandateChain.parse`/`verify` were exercised with ephemeral P-256 issuer and agent keys. A root open mandate limited USD amount, payee, and instrument; the delegated closed mandate specified those fields and a synthetic checkout digest. Evidence stores presentation SHA-256 hashes only, never private keys or full tokens.
- [local-unittest.log](local-unittest.log): 2/2 project tests passed in the pinned AP2 venv. [upstream-focused.log](upstream-focused.log): 8/8 selected official SDK tests passed.
- [base-python-skip.log](base-python-skip.log): 2/2 project AP2 tests explicitly skipped when the pinned SDK is absent, so base Python discovery remains usable.
- [manifest.json](manifest.json) hashes the new runner, tests, report, dependency freeze, and local evidence files.
- PASS cases include valid authorization and expected rejection of damaged root signature, wrong trusted issuer, wrong holder key, wrong audience, wrong nonce, expired root/leaf, out-of-scope payee/amount/currency/instrument, and mismatches between the signed mandate and proposed transaction. The replay case rejects via the caller's in-memory one-use ledger.

The project tests independently assert the *specific rejection reason* for each negative case so unrelated failures do not count as conformance. Cryptographic verification itself uses the official AP2 SDK under test; no second AP2 implementation was cross-checked.

## Boundary and limitations

- Execution tier: `NATIVE_LOCAL_PROTOCOL` for signed authorization. Model tier: none. Transaction tier: none. All identifiers are synthetic test values; no payment settlement evidence exists.
- AP2 SDK is stateless for reuse of the same valid presentation. The one-use ledger, proposed-transaction equality checks, and trusted issuer key selection are caller controls. A fresh verifier instance accepts the same valid presentation; a real service would need durable, atomic replay state and issuer trust management. The challenge nonce is verified cryptographically, but uniqueness must be managed by the verifier.
- No revocation service is configured or exercised (**SKIP**); expiration is exercised using the SDK with zero clock skew and an evaluation time five minutes after issuance. No issuer-to-user consent proof, signed checkout chain, payment receipt, PSP execution, or actual delegated charge is claimed (**SKIP**). The transaction ID is a base64url SHA-256 digest of a synthetic checkout reference, not proof of a valid checkout.
- AP2 constrains a delegated payment action. It does not attest that a worker's submission is correct or that an auditor checked it. Any verification rule remains an explicit application control. The fixture has no LLM decisions.

Files added: `scripts/run_ap2_local.py`, `tests/test_ap2_local.py`, and this W15 evidence directory. No `legacy/` or handover package file changed. No migration required. No owner approval is needed for the local valueless tests. Next eligible protocol work remains W16/W17 as scheduled; scientific claims remain gated by the live-agent stages.
