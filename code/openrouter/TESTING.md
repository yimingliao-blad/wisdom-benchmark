# Testing the phase-2 harness

**Measured on a clean checkout, 2026-08-11: `312 tests ran, 206 passed, 4 failed, 100 errored, 2 skipped`.**

Every one of the 106 failures and errors is a **missing data file**, not a code defect — 93 raise
`FileNotFoundError` outright, and the 4 assertion failures are tests whose tool correctly HALTed with
*"<corpus> does not exist — a stage cannot be scoped without its item corpus, and guessing its size
would defeat the point"*. The harness fails loud on absent data by design; the tests then see a halt
message instead of the output they asserted.

## Why the data is not in the repo

Consistent with the phase-1 policy in the top-level README: the benchmark corpora are third-party and
variously licensed. **BTF-3 is CC-BY-NC-4.0.** The item files contain the benchmark prompts and their
ground truth, so they are fetched, never committed.

## What the tests need

| path (relative to `code/openrouter/`) | what it is | size |
|---|---|---|
| `runs/fx_smoke4.json` | 4-item FutureX smoke slice | 8 K |
| `runs/fx_items_110.json` | the 110 frozen FutureX-Past items | 132 K |
| `runs/btf3_items_110.json` | the 110 frozen BTF-3 items | 788 K |
| `runs/_frozen_fxgate_2026-08-08/` | frozen 1,131-record snapshot + its manifest and items | ~5 M |
| `runs/or_futurex_fxgate/`, `runs/or_btf3_*/` | the live run directories | ~109 M |

The published `results/openrouter/*/records.jsonl.gz` and `manifest.json` **are** the run artifacts for
the last two rows — decompress them into `runs/<tag>/records.jsonl` to satisfy the tests that read
records. The item corpora must come from the sources in `docs/DATASETS.md`.

## The 20 modules that pass with no data at all

```
test_account_fault     test_analyze          test_any_model_list   test_bench_formats
test_budget_policy     test_claim_gate       test_completeness     test_concurrency
test_corpus_mining     test_finalize         test_followup_select  test_infra_faults
test_provenance        test_quarantine       test_response_schema  test_roster_build
test_smoke_acceptance  test_spend            test_transport        test_wiring
```

```bash
cd code/openrouter
python3 -m unittest test_account_fault test_analyze test_any_model_list test_bench_formats \
  test_budget_policy test_claim_gate test_completeness test_concurrency test_corpus_mining \
  test_finalize test_followup_select test_infra_faults test_provenance test_quarantine \
  test_response_schema test_roster_build test_smoke_acceptance test_spend test_transport test_wiring
```

These cover the parts worth checking without spending money: the infrastructure-fault policy (retry 3,
pause the model, halt only on account faults), the result/non-result boundary, budget enforcement,
roster building from a bare model list, and quarantine behaviour. All network calls are stubbed.

## Five modules that fail at import

`test_item_validate`, `test_manifest`, `test_persistence`, `test_schedule`, `test_supersession` read a
fixture at module scope, so they raise before any test runs. That is a fixture-loading style, not a
packaging problem — they pass in the development tree where `runs/` is populated (454 tests green there
on 2026-08-10).
