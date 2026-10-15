# 16 — Verified upstream links and commit-pinning instructions

These are official or paper-linked public sources checked as of **2026-10-15**. **Links are not git commit pins**. Codex must fetch, inspect, verify license, and record immutable commit/release hashes before integration. No third-party code is copied into this package.

## Primary runtime / methods

| Component | Canonical URL | Implementation caveat |
|---|---|---|
| ORBIT | https://github.com/wlanderson0/orbit | Maintained README describes release v1.0.2, Github wheel and source distribution. **Do not `pip install orbit`; unrelated package.** Python 3.11+, Inspect 0.3.263 in tested baseline; read actual installation guide. |
| Inspect AI | https://github.com/UKGovernmentBEIS/inspect_ai | Original UK AISI evaluation runtime; pin compatible release per ORBIT. |
| Colosseum | https://github.com/umass-ai-safety/colosseum | Published experiments use Terrarium, CoLLAB for some tasks; clone recursive submodules if required. Port math/metrics conceptually, don't replace ORBIT scheduler. |
| AgentDojo | https://github.com/ethz-spylab/agentdojo | Dynamic tasks/attacks; API still evolving. Check task/dataset licences. |
| AgenticPay | https://github.com/SAIL-Research-Lab/AgenticPay | Original `SafeRL-Lab` URL redirects here; optional negotiation module. |

## Payment and interoperability sources

| Component | Canonical URL | Warning |
|---|---|---|
| ERC-8183 | https://github.com/erc-8183/base-contracts | Foundry contracts and hooks; current implementation contains partial claim/settlement semantics: pin ABI/revision. |
| ERC-8183 EIP | https://eips.ethereum.org/EIPS/eip-8183 | Draft can differ from base-contracts current code. |
| x402 v2 | https://github.com/x402-foundation/x402 | Pin exact spec/scheme and HTTP transport version. |
| x402 v2 spec | https://github.com/x402-foundation/x402/blob/main/specs/x402-specification-v2.md | Payment flow models include default authorization and potentially upfront variants. |
| MPP | https://github.com/tempoxyz/mpp | Documentation/protocol SDK reference; official Stripe/Tempo project. |
| Google AP2 | https://github.com/google-agentic-commerce/AP2 | Native Python SDK exists under `code/sdk/python/ap2`; use current spec version. |
| Virtuals ACP v2 | https://github.com/Virtual-Protocol/acp-node-v2 | `@virtuals-protocol/acp-node-v2` maintained. Old `acp-node` deprecated. |
| OpenAI/Stripe ACP | https://github.com/agentic-commerce-protocol/agentic-commerce-protocol | Checkout-oriented, **not** Virtuals ACP. Versioned `2026-04-17` OpenAPI. |
| UCP | https://github.com/universal-commerce-protocol/ucp | Commerce layer; test AP2 composition only if supported. |
| A2A | https://github.com/a2aproject/A2A | Communication specification; version 1.0.0; not a payment rail. |
| A2A Python | https://github.com/a2aproject/a2a-python | Official Python SDK; optional v0.3 compat mode. |
| ERC-8004 | https://github.com/erc-8004/erc-8004-contracts | Identity/reputation/validation overlay; no inherent payments. |

## Prior work references for manuscript

- Shi et al., *Emergent Collusion in Long-Horizon LLM Agent Interaction*, https://arxiv.org/abs/2609.24967
- Nakamura et al., *Colosseum*, https://arxiv.org/abs/2602.15198
- Hagag et al., *ORBIT*, https://arxiv.org/abs/2609.33102
- Zhou et al., *CABAL*, https://arxiv.org/abs/2609.05227
- Liu et al., *AgenticPay*, https://arxiv.org/abs/2602.06008
- Debenedetti et al., *AgentDojo*, https://arxiv.org/abs/2406.13352
- Jiang et al., *A Formal Analysis of Agent Payment Protocols*, https://arxiv.org/abs/2609.00060
- Aviv et al., *Beyond the Mandate*, https://arxiv.org/abs/2608.23858
- Sun et al., *SoK: Decentralized Agent Economic Infrastructure*, https://arxiv.org/abs/2610.01756
- Xiong et al., *Can Trustless Agents Be Trusted?*, https://arxiv.org/abs/2606.26028
- Wang et al., *When HTTP 402 Meets the Blockchain*, https://arxiv.org/abs/2607.19545
- Srivastava & Paul, *Agentic Commerce Bench*, https://arxiv.org/abs/2609.35886
- Hagverdiyev, *Compromise Is Not Consequence*, https://arxiv.org/abs/2610.05840
- Yang et al., *SoK: When Safe Agents Fail Together*, https://arxiv.org/abs/2609.00595

## Version manifest requirements

For each upstream store: canonical URL, branch, pinned git SHA, local path or wheel checksum, license path, known unsupported functions, native test command, status `FETCHED/PINNED/TESTED/BLOCKED`, and reason. Use a legal version of the license and citation in final repo, and document generated/altered assets. Do not assume a paper arXiv link establishes software license.
