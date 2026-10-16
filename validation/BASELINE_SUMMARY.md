# Packaging baseline validation — 2026-10-15

| Check | Actual result | Interpretation |
|---|---|---|
| Legacy Python suite | 41 tests passed in 1.714s | Offline mock functionality and fixture/regression checks |
| Legacy pilot on-demand triggered by tests | 8 offline trials; 8 trace-digest checks | Local-script plumbing, no native cryptography |
| `python -m paidaudit wire-smoke` | x402 and MPP `402→200`; replay 409; changed amount 403 | Loopback HTTP-shape mock; HMAC is not a native payment credential |
| ORBIT installed and integrated in this delivery | NOT RUN | Codex integration required |
| Native local ERC-8183 | NOT RUN | Codex integration required |
| Native local x402 scheme | NOT RUN | Codex integration required |
| Real independent worker/auditor LLM run | NOT RUN | Codex integration required |

See adjacent verbatim output files for the actual packaging test evidence. Do not convert old simulation successes into research claims.
