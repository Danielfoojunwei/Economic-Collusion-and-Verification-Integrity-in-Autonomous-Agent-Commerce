# Independent review of BILATERAL030 scripted 30-row rehearsal

**Decision:** the 30-row local infrastructure rehearsal passed independent saved-evidence replay. Scientific live-agent and causal claims remain **HOLD**.

The terminal index is `artifacts/prospective/ERC8183_BILATERAL030_STRESS030_001/stress-index.json` (SHA-256 `8925e488563f9029e4b3a5b1746bfe5afd9cd15dec5df268a4daa8984ab00cec`). The fixed plan is `script-plan.json` in the same directory (SHA-256 `5e333455c700cd6827a8395c30c2961ba02e69730cc327d524520a181269057e`). The index reports 30 planned and 30 completed rows, no failure file, 14 current source pins, 15 assigned slots per model direction, and seven arm counts of 12/4/4/4/2/2/2. I independently recomputed these from `make_scripts()`, compared the exact assignment and execution order, and checked that the pinned source bytes still matched at review time.

I ran `scripts/review_bilateral030_stress.py` in a separate process with `OPENROUTER_API_KEY` unset, `ALLOW_EXTERNAL_MODEL_CALLS=false`, and dotenv disabled. It passed **30/30**. For every row it recomputed all seven indexed artifact SHA-256s (**210/210**), replayed the public funding archive offline (**30/30**), reran the terminal native receipt verifier (**30/30**), and reran the Inspect trace verifier (**30/30**). Every fresh verifier result exactly equaled its saved report. The replay separately reconstructed the funding proof from the saved pre-view verifier result and assigned public job, then confirmed that proof in every actual `ModelEvent.input` user frame and the auditor inbox. Captured model inputs exactly matched saved Inspect model inputs. It joined funding, claim, check, first decision and final native transactions by the assigned row and job. GOOD with funded and absent bonus, BAD with and without paid checks, contact masking, approval and rejection branches all passed.

The saved pre-view reports say `FUNDING_LIVE_CONFIRMED` from disposable localhost Anvil before model activation. The independent review could replay their archived transactions and compare every common report field, but the stopped chains could not be queried again for live history authentication. All actual agent routes were `mockllm/`; the assigned Sol and Sonnet model IDs were never called. The tokens had no real value. These rows establish protocol and evidence-path mechanics, not autonomous agent choices.

The harness **scripted 14 BAD early approvals**. The false payouts in those rows are therefore mechanical consequences of authored tool calls, not observed collusion. Script allocation also created an apparent model-direction association: among the BAD assigned slots, Sol-provider slots had **six** checked approvals while Sonnet-provider slots had **one**. Both sides had 13 BAD slots; neither assigned model executed. The rehearsal yields no model susceptibility comparison, contact effect, ablation result, p-value, or evidence of bilateral assent. It must not be included in a real LLM denominator.

Reproduce the read-only check with the pinned ORBIT environment:

```sh
env -u OPENROUTER_API_KEY ALLOW_EXTERNAL_MODEL_CALLS=false PYTHON_DOTENV_DISABLED=1 PYTHONPATH=src:/workspace/upstreams/orbit:. \
  /workspace/upstreams/orbit-smoke/.venv/bin/python scripts/review_bilateral030_stress.py \
  artifacts/prospective/ERC8183_BILATERAL030_STRESS030_001
```

The earlier `STRESS_SMOKE001` path-writing abort remains archived with attempted 1, completed 0, and nine raw file hashes; its native and Inspect evidence replayed. The corrected fresh `STRESS_SMOKE002` completed and replayed before this 30-row rehearsal. Neither smoke is a scientific study row.
