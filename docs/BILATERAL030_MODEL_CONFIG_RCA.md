# BILATERAL030 per-agent reasoning and output cap RCA

The first BILATERAL030 **mock-only** ORBIT trace showed a configuration gap:
the provider's ModelEvents requested `reasoning_effort=high`,
`reasoning_history=none`, `max_tokens=3072`, and `max_retries=0`; all three
auditor ModelEvents instead had `None`, `None`, `None`, and `0`. The model tool
calls in that trace were scripted mock outputs, so this is a request-boundary
finding, not a finding about auditor reasoning quality.

ORBIT 1.0.3 `AgentSpec` forwards only its `temperature` override. Inspect's
task-level `GenerateConfig` applied to the active provider model, while the
explicit auditor `AgentSpec.model` resolved a separate model with default
settings. The local `configured_role_models()` helper now clones **both**
mock-routed model objects with the four pinned settings before ORBIT resolves
the roles. Raw Inspect regression tests check every provider and auditor
ModelEvent; the read-only trace verifier also rejects an uncapped or
non-high-reasoning event. This is a source-only gate. A future hosted runner
must configure its separate role model objects and validate the actual
outbound API requests before any call; the paid entrypoint remains closed.

This gap does **not** explain the prior PARTIAL014/PRESSURE016 live results.
The read-only forensic script in
`scripts/review_bilateral030_prior_model_config.py` reopened all eight saved
Inspect archives: five PARTIAL014 successful rows, two PRESSURE016 successful
rows, and one PRESSURE016 error row. Every one of their 68 saved ModelEvents
(24 Sol provider and 44 Sonnet auditor) requested `high`, `none`, `4096`, `0`.
PARTIAL014 reported 611 provider and 825 auditor reasoning tokens across 15
and 29 events. PRESSURE016 reported 561 provider and 716 auditor reasoning
tokens across 9 and 14 of 15 auditor events; the final error event lacks
usage. These token counts are provider-reported usage, not a measure of private
deliberation depth. Archive paths, SHA-256 hashes, and per-event settings are
recorded in
`artifacts/prospective/ERC8183_BILATERAL030/prior-live-model-config-review-2026-10-16.json`.

The auditor prompt now states the same economic objective and correctness duty
in every arm, including GOOD and adversarial stress. This fixes a separate
false-negative risk: a proper auditor previously had no explicit personal
compensation motive despite facing a provider-funded bonus. A researcher
prompted adversarial objective remains a separate stress condition.
