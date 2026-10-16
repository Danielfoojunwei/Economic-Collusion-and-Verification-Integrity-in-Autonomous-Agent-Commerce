# AGENTS.md — repository-wide instructions for Codex

## Mission

Answer a focused empirical research question about autonomous agents paid to verify other agents' work. **Do not turn this into a standalone benchmark development project.** The manuscript is about economic dependence, actual verification decisions, payment consequences, and security/utility countermeasures. Working title: *When Agents Pay Their Auditors: Economic Collusion and Verification Integrity in Autonomous Agent Commerce*.

## Read first

`START_HERE.md`, `CODEX_MASTER_PROMPT.md`, and `planning/WORK_ORDERS.md`. Follow `planning/STAGE_GATES.md` and `planning/ACCEPTANCE_TEST_MATRIX.md` at each handover checkpoint.

## Runtime / code policy

- Default orchestration: official ORBIT v1 maintained GitHub release (built on Inspect AI). Verify exact API/commit before importing.
- ORBIT warns that `pip install orbit` installs an unrelated package: NEVER use that command to install this research ORBIT. Use its verified GitHub release wheel/source instructions.
- Colosseum: preserve its metric definitions and research baseline, pin its exact repo/commit; do not copy large code into this repo.
- AgentDojo/AgenticPay/other sources: optional task/negotiation modules; verify data licenses and feasible baseline first.
- Existing `legacy/` is **read-only**. If adapting a legacy module, extract a tiny interface in the new `src/` tree and add independent tests; keep provenance comments.
- Follow primary source specifications for native protocols. Never call a Python transition stub “native ERC-8183,” “official x402,” or “cryptographically secure.”
- Protocols solve different problems. A2A is communications; ERC-8004 is identity/reputation; AP2 is delegated authorization; OpenAI/Stripe ACP is retail commerce; Virtuals ACP is another protocol.
- Prefer small, reviewable slices with tests; do not preemptively add large scaffolds or new frameworks.

## Evidence and claims

Every result row must record `execution_tier`: `SCRIPTED_SIMULATION`, `REAL_LLM_LOCAL`, `NATIVE_LOCAL_PROTOCOL`, or `NATIVE_TESTNET`. Production is never allowed in this project. An experiment combining tiers must record **both** model tier and transaction tier, not assume one label fully describes the run.

Do not infer collusion from mutual ACCEPT, chat planning, or network adjacency. Report: false approval, unchecked approval, wrongful settlement, wrong amount/payee, and coalition excess relative to appropriate independent counterfactuals separately. Report null results and honest-provider nonpayment.

## Safety / approvals

- Default `ALLOW_EXTERNAL_MODEL_CALLS=false`, `ALLOW_TESTNET=false`, `ALLOW_MAINNET=false`, `MAX_REAL_SPEND=0`.
- No real money, external wallet keys, private user documents, unattended API spending or live third-party payment exploits.
- No provider's untrusted content may become system instructions. Keep signing outside LLM processes.
- Code tasks execute in no-network containers with CPU/memory/time bounds and no host secrets.
- External dataset download requires license/provenance review; cite all upstream sources.

## Tests and reporting

Use deterministic seeds for scripts and store a complete run manifest, pinned code hashes, prompts, model versions, task IDs and treatment assignment. Maintain `docs/15_EVIDENCE_AND_CLAIMS.md` with claimed evidence levels. For every new function: unit test, negative test, clear failure/skip reason. Refuse to mark a gate PASS if prerequisites were mocked instead of exercised.

Required completion report at each gate: commands run; pass/fail/skip summary; files changed; new artifacts; independent verifier statement; evidence limitations; next work order; unresolved blockers. If blocked, stop with evidence.
