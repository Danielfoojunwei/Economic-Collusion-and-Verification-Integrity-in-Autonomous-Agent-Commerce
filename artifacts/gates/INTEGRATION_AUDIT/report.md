# Integration audit — 2026-10-15

The cross-gate evidence index is [`docs/EVIDENCE_LEDGER_2026-10-15.md`](../../../docs/EVIDENCE_LEDGER_2026-10-15.md).
This report records an independent integration check of the in-progress
checkout. It makes no scientific effect claim.

## Checks performed

- `python scripts/validate_handover.py`: 111/111 original files passed size
  and SHA-256 verification. `sha256sum --check SHA256SUMS.txt` passed.
- `verify_evidence` reopened the final G1 `scripted-run-004` manifests and
  artifacts: 24, 21 and 21 valid events respectively, with three outcomes
  each. Both completed W05 pilot samples passed `verify_evidence` with 17
  events and one outcome each. G1 source SHA-256 values matched current code.
- The first W05 pilot's offline supplement verifier passed and recovered its
  USD 0.046460 conservative usage estimate from the immutable native Inspect
  log and pinned public pricing record. Four supplement tests passed.
- G2, G3, W07, W09 and W14 native evidence SHA-256 values matched their gate
  reports. The W14 MPP verifier re-read five saved local Tempo transaction
  receipts and checked 16 HTTP events against a live disposable chain.
- The W10 protected-receipt pair's original good and derived COMPLETE native
  logs had the same SHA-256; the bad native log matched its report. The read-only
  `scripts/compare_w10_pair.py` returned `verified: true`: public task,
  provider copy, submission view and **first** auditor input matched, while
  aggregate precheck model inputs differed. The good run's COMPLETE evidence
  was derived after its original exporter stopped; this is one good episode,
  not an additional paid run. Both fixed real-model verdicts agreed with the
  private oracle after one priced check, and neither ran a payment transaction.
- W10's 32-assignment freeze, native local auditor-fee funding and scripted
  isolation-control hashes matched their reports. At this earlier audit
  snapshot, the empty freeze analysis had zero completed economic treatment
  records. Those bulk ERC-20 fee transfers did not link a real verdict to
  task settlement; the later live pilot is recorded below.
- The W11/W12 read-only verifier returned `VERIFIED_METHODS_ONLY` for the final
  native scripted Inspect log and frozen market schedule. W13/G5's native
  branch evidence and six-test log matched their reported SHA-256 values;
  its two public tasks and scripted ACCEPT decisions do not measure defense
  effectiveness with live agents.
- The W17 coverage, manifest and opt-in cloud setup validation hashes matched
  the saved records. All 16 paths indexed in the W17 manifest still matched
  their SHA-256 values. W17 records ACP checkout schema/mock, A2A SDK
  transport and ERC-8004 registry behavior, with UCP+AP2 native composition
  explicitly SKIPped.
- W18's final ORBIT Meeting Scheduling calibration evidence matched SHA-256
  `3cb15d689c93ccaa45baa0d351234cd0b104a6f57b78a2af9df632278ffa3dcd`.
  Four focused tests passed; the source-version/hash guard and two ORBIT reward
  functions agreed over all 36 complete schedules. No model or payment was run
  for that case, and no holdout was opened.
- A high-confidence pattern scan of 135 artifact files found no PEM private
  key block, OpenRouter/GitHub token shape, AWS access key shape or bearer
  authorization header. This pattern scan cannot certify absence of every
  possible secret. Logs may contain private research fixture truth and should
  be shared with that scope in mind.

## Post-audit W10/G4 completion — 2026-10-15

The live pilot later executed all 32 preassigned fresh-pair R×S×P trials from
assignment-003 under the shared USD 20 cap. The [G4 report](../G4/report.md)
links the exact model, local ERC-20 auditor fee, ERC-8183 task settlement,
private oracle, original native Inspect logs and schema-v1 event/outcome files.
The [final read-only collection](../G4/collection-final-001/analysis.json),
SHA-256 `cc0d34db15a9a62731005ed07a33c8463fdd90ac3218a622cea51e1d4672f37f`,
reopened and validated all 32 saved logs with attachments resolved, each
native receipt and balance consequence, exact R/S/P exposure, source seals,
project ledger settlement, and every schema-v1 file hash. It found 32 valid
COMPLETE records, 0 pending and 0 evidence failures, with four assigned pair
clusters in each of eight cells. No channel tool was offered or used. All 32
auditors bought the feasible check; 16 good claims were accepted and paid,
and 16 bad claims rejected and refunded. The 32 model-use estimates
sum to USD 1.811760; the shared project ledger then showed USD 2.03895
settled and USD 17.96105 available. These are real remote-model behaviors
and native **local valueless** task-payment observations. They are not evidence
of an absent economic effect or a collusion rate beyond the four reused private
worlds and one model.

The [aggregate manifest](../G4/aggregate-pilot-001/aggregate_run_manifest.json),
SHA-256 `5170235c2125923515464daca5b1820b025a0dec7d46e81f141a02b001d9cdfd`,
reverified all 32 per-trial manifest/log/receipt/ledger links and supplied a
bounded, explicitly exploratory W19 calibration. G4 remains open for W11/W12
direct-offer, truly independent never-channel, longitudinal market, and
positive-control comparisons. The earlier audit's file-count pattern scan,
repository-status snapshot and full-suite test note are historical; this
addendum does not claim they were repeated after the 32 live trials.

## Repository and reproduction readiness

At audit time, `origin/main` was the initial README-only commit
`e953d182659f57072fc4cf9c65d323ef9d2217ba`; the implementation and
handover were still untracked on branch `work`. The saved cloud install
script needs these files available from a commit in its selected repository
ref before a fresh checkout can reproduce setup. The checkout used about
123 MiB locally, including about 97 MiB of ignored `protocols/mpp/node_modules`
and a 15 MiB original legacy ZIP. Git ignore rules exclude node modules and
Python caches; the package ZIP and original PDF remain intentional provenance
files. The current `scripts/setup_cloud_environment.sh` installs ORBIT/Inspect,
Foundry/solc, ERC-8183, x402, the isolated AP2 SDK and the official MPP SDK
with a pinned local Tempo image. Its `SETUP_W17_PROTOCOLS=true` extension adds
ACP schemas, A2A SDK and ERC-8004 local compiler inputs. The W17 report records
two successful opt-in setup runs. Setup installs dependencies and image bytes;
the per-gate test commands produce transaction evidence separately.

The first full Python discovery I ran encountered one W05 supplement test
error while another agent was updating its sidecar concurrently. The finalized
supplement verified and its four focused tests then passed. Run the final
shared suite after all agents stop editing; retain its exit status and counts.

## Final validation commands

From the repository root, after cloud setup and after writes to evidence and
reports finish:

```bash
python scripts/validate_handover.py
sha256sum --check SHA256SUMS.txt
PYTHONPATH=src PYTHON_DOTENV_DISABLED=1 \
  XDG_DATA_HOME=/workspace/.local/share \
  XDG_CACHE_HOME=/workspace/.cache \
  XDG_CONFIG_HOME=/workspace/.config \
  /workspace/upstreams/orbit-smoke/.venv/bin/python \
  -m unittest discover -s tests -p 'test_*.py' -q
PYTHONPATH=src /workspace/upstreams/orbit-smoke/.venv/bin/python \
  scripts/write_w05_supplement.py verify
git status --short
```

For the native protocol checks, use the per-gate commands in G2, G3, W14 and
W15 reports. `protocols/mpp/verify-evidence.mjs` compares archival receipts
with the **still-running original** local Tempo chain; on a fresh chain,
reproduce the MPP test first and treat its new evidence as a separate run.
