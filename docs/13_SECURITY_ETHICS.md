# 13 — Safety, ethics, legal boundaries and research integrity

## Payment and identity safety

- NEVER use mainnet real assets, charge real payment instruments, or interact with real customer/provider accounts. Default to locally funded valueless EVM test assets and loopback HTTP test services.
- All model-controlled payment requests are proposals, not direct key access. Keys remain isolated in an allowlisted transaction signer under deterministic authority checks.
- No API tokens or secrets in source, prompts, manifests, chat logs or ZIP. `.env.example` contains placeholders only.
- Official SDKs may support mainnet by default; explicitly force chain ID and endpoints to local network and test transactions before enabling.
- No automated scans or exploit testing against external providers, mainnet facilitators, or live commerce sites.

## Model and adversarial safety

- Provider-controlled descriptions, tool output and agent cards are always untrusted data.
- Isolate roles and their memory (including when the same base model is reused). Do not assume prompts enforce role permissions.
- Code tasks are containerized with no outgoing network and limited files/processes/time. Executed code must not receive wallet keys, cloud credentials or test oracles.
- No offensive public cyberattack task scenarios; security tasks use deliberately controlled toy fixtures and authorized local environments.
- Model-generated attack plans in benign synthetic market should not be repurposed against real institutions or users.

## Human/subjective evidence

- Do not collect personal information or recruit human raters before appropriate supervisor/ethics review.
- For any expert adjudication, disclose consent, data retention, anonymization, compensation and conflict-of-interest management.
- For open task datasets, respect redistribution/use restrictions and version/commit. Do not embed third-party datasets without checking licenses.

## Scientific integrity

- Never fabricate runs or present scripted policy coefficients as model behaviour.
- Distinguish 'collusion experimentally induced' from 'emergent under neutral instructions'.
- Report all preregistered arms, nulls, incomplete runs, and anomalous traces. Adversary controls must be explicit.
- Do not leak private ground truth or run learned models on held-out tasks already exposed by training; report contamination risks.
- Preserve an append-only deviations log whenever designs, prompts, thresholds or model configurations change after preregistration.

## Approval gates

- `ALLOW_EXTERNAL_MODEL_CALLS` defaults `false`.
- `ALLOW_TESTNET` defaults `false`.
- `ALLOW_MAINNET` is *always* `false` for this project.
- `MAX_REAL_SPEND_MINOR_UNITS` defaults `0`.
- Running remote APIs or local-chain transactions with nonzero value requires an explicit written scope/budget approval and a local/test-only signer configuration.
